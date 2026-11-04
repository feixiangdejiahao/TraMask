"""Slice historical versions in their IO contexts; keep independent trials."""
import ast
from collections import defaultdict,deque
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re

from .anchors import SUFFIXES, STRINGS
from .artifacts import read_json, read_manifest, reference_path, relative_references, resolve_references, write_json
from .blobs import BlobStore
from .evidence import SourceGraph, IDENTS, MEMBERS
from .pre_slice import merge_ranges
from .targets import targets_from_collection, read_target_source
from .history import materials_from_manifest
from .material_entries import select_material_entries, MaterialConnections
from .slice_frontier import matching_statements, validation_groups, attached_comments, source_syntax
from .source_text import decode_material
from .shell import interpreter_entry
from .trajectory import TrajectoryGraph,SOURCE_USES
from .slice_behavior import (connect_calls, source_behavior, execution_context, material_links,
                             select_exported_behavior, write_behavior_graph, read_behavior_graph)


def source_role(path,event):
    argv=event['argv'];name=Path(argv[0]).name;arguments=argv[1:]
    if re.fullmatch(r'python[\d.]*',name) or name in {'node','nodejs','tsx','ts-node'}:
        kind,value,arguments=interpreter_entry(argv)
        if path.startswith('<stdin>') and kind!='stdin':return 'source_input'
        if kind in {'module','file'} and value is not None:name=Path(value).name
    if name in {'cat','grep','head','tail','sed'}:return 'source_input'
    if name in {'bandit','ruff','mypy','pyright'}:
        for argument in arguments:
            if argument.startswith('-'):continue
            target=posixpath.normpath(posixpath.join(event['cwd'],argument))
            if path==target or path.startswith(target.rstrip('/')+'/'):return 'source_input'
    return 'program'


class ContextProgram:
    """Static interprocedural dependencies qualified by observed file versions.

    Calls, framework setup and global effects are inferred. File reads and
    generated materials come from the separate trajectory graph.
    """
    def __init__(self,materials,context,cache,read_source):
        self.materials=materials;self.context=context;self.cache=cache;self.read_source=read_source
        self.modules={};self.imports={};self.calls=defaultdict(set);self.prepared=set()
        self.extra=defaultdict(set);self.unresolved=set()
        self.version_alternatives=defaultdict(set)
        self.sites=defaultdict(set);self.resolved=set();self.caller_sites={};self.node_effects={};self.summaries={}

    @classmethod
    def from_source(cls, graph):
        """One immutable source version without an observed execution."""
        source=graph.source['id'];path=graph.source['path'];digest=hashlib.sha256(graph.raw).hexdigest()
        materials={source:{'kind':'file','path':path,'sha256':digest}}
        context={'execution':None,'source_versions':{path:[source]},'input_versions':{},
                 'source_basis':{source:'static_single_source'},'unresolved_versions':{},'unresolved_bytecode_sources':[]}
        return cls(materials,context,{(path,digest):graph},lambda info:(graph.raw,None))

    def load(self,material):
        if material not in self.modules:
            info=self.materials[material];key=info['path'],info['sha256']
            if key not in self.cache:
                raw,error=self.read_source(info)
                self.cache[key]=SourceGraph({'id':info['path']+'@'+info['sha256'],'path':info['path'],'raw':raw},source_error=error)
            self.modules[material]=self.cache[key]
        return self.modules[material]

    def module_paths(self,origin,name,level=0):
        current=self.materials[origin]['path'];suffix=PurePosixPath(current).suffix
        root=posixpath.dirname(current)
        if suffix=='.py':
            if level:
                for _ in range(level-1):root=posixpath.dirname(root)
                bases=[posixpath.join(root,name.replace('.','/'))]
            else:bases=[name.replace('.','/')]
            ends=[b+'.py' for b in bases]+[b+'/__init__.py' for b in bases]
        else:
            base=posixpath.normpath(posixpath.join(root,name)) if name.startswith('.') else name
            ends=[base] if PurePosixPath(base).suffix in SUFFIXES else [base+s for s in sorted(SUFFIXES)]+[base+'/index'+s for s in ('.ts','.js')]
        return sorted({m for path,versions in self.context['source_versions'].items()
                       if any(path==end or (not level and not name.startswith('.') and path.endswith('/'+end)) for end in ends)
                       for m in versions})

    def bindings(self,material):
        if material in self.imports:return self.imports[material]
        g=self.load(material);bindings={};suffix=PurePosixPath(self.materials[material]['path']).suffix
        for n in g.nodes:
            node=n['ast'];text=g.text(node)
            if suffix=='.py' and node.type in {'import_statement','import_from_statement'}:
                statement=ast.parse(text).body[0]
                if isinstance(statement,ast.Import):
                    for name in statement.names:
                        alias=name.asname or name.name.split('.')[0]
                        bindings[g._binding(n['scope'],alias)]=(self.module_paths(material,name.name),None)
                else:
                    for name in statement.names:
                        if name.name=='*':self.unresolved.add('star_import');continue
                        if statement.module is None:
                            paths=self.module_paths(material,name.name,statement.level);export=None
                        else:paths=self.module_paths(material,statement.module,statement.level);export=name.name
                        bindings[g._binding(n['scope'],name.asname or name.name)]=(paths,export)
            elif suffix in {'.js','.jsx','.ts','.tsx','.mjs','.cjs'} and node.type=='import_statement':
                match=re.search(r'\bfrom\s+[\'"]([^\'"]+)[\'"]',text)
                if match is None:continue
                paths=self.module_paths(material,match[1]);named=re.search(r'\{([^}]+)\}',text)
                if named:
                    for part in named[1].split(','):
                        names=part.strip().removeprefix('type ').split(' as ')
                        if names[0]:bindings[g._binding(n['scope'],names[-1])]=(paths,names[0])
                namespace=re.search(r'\*\s+as\s+(\w+)',text)
                if namespace:bindings[g._binding(n['scope'],namespace[1])]=(paths,None)
                default=re.match(r'import\s+(\w+)\s*(?:,|from)',text)
                if default:bindings[g._binding(n['scope'],default[1])]=(paths,'default')
            elif suffix=='.go' and node.type=='import_spec':
                path=g.text(node.child_by_field_name('path')).strip('"`')
                alias=g.text(node.child_by_field_name('name')) or path.rsplit('/',1)[-1]
                paths=[m for p,versions in self.context['source_versions'].items() if p.endswith('.go') and posixpath.dirname(p).endswith('/'+path) for m in versions]
                bindings[g._binding(n['scope'],alias)]=(paths,None)
        self.imports[material]=bindings
        return bindings

    def functions(self,material,name):
        g=self.load(material)
        for issue in g.issues:self.unresolved.add(issue['kind']+':'+self.materials[material]['path'])
        return {(material,s['id']) for s in g.scopes if s['kind']=='function' and
                (s['name']==name or (name=='default' and s['ast'].parent is not None and
                                    g.text(s['ast'].parent).startswith('export default')))}

    def resolve(self,material,nid):
        if (material,nid) in self.resolved:return self.calls[material,nid]
        self.resolved.add((material,nid))
        g=self.load(material);node=g.nodes[nid];targets=set()
        for call,scope,kind in g.call_sites[nid]:
            targets.add((material,scope));self.sites[material,nid].add((call.start_byte,call.end_byte,material,scope,kind))
            if kind=='callable_value' and g.scopes[scope]['params']:self.unresolved.add('callback_parameters_not_observed')
        imports=self.bindings(material)
        for name,callee,call in node['calls']:
            if callee is None:continue
            paths=[];export=name
            if callee.type in IDENTS:
                binding=g._binding(node['scope'],g.text(callee))
                if binding in imports:paths,export=imports[binding]
                elif PurePosixPath(self.materials[material]['path']).suffix=='.go':
                    parent=posixpath.dirname(self.materials[material]['path'])
                    paths=[m for p,versions in self.context['source_versions'].items() if p.endswith('.go') and posixpath.dirname(p)==parent for m in versions]
            elif callee.type in MEMBERS:
                base=callee.child_by_field_name('object') or callee.child_by_field_name('operand') or callee.child_by_field_name('value')
                if base is not None:
                    binding=g._binding(node['scope'],g.text(base))
                    if binding in imports:paths=imports[binding][0]
                    elif g.text(base) in {'self','cls'}:
                        scope=g.scopes[node['scope']]['parent']
                        if scope is not None and g.scopes[scope]['kind']=='class':
                            for s in g.scopes:
                                if s['parent']==scope and s['name']==name:
                                    targets.add((material,s['id']))
                                    self.sites[material,nid].add((call.start_byte,call.end_byte,material,s['id'],'bound_method'))
            elif callee.type=='scoped_identifier':
                parts=g.text(callee).split('::')
                if len(parts)==2:paths=self.module_paths(material,'./'+parts[0]);export=parts[1]
            versions=defaultdict(set)
            for target in paths:versions[self.materials[target]['path']].add(self.materials[target]['sha256'])
            for target in paths:
                for resolved in self.functions(target,export):
                    if len(versions[self.materials[target]['path']])>1:
                        self.version_alternatives[material,nid,call.start_byte,call.end_byte,'direct'].add(resolved)
                        self.unresolved.add('source_version_not_bound:'+self.materials[target]['path'])
                        continue
                    targets.add(resolved);self.sites[material,nid].add((call.start_byte,call.end_byte,*resolved,'direct'))
        self.calls[material,nid].update(targets)
        return targets

    def prepare(self,material,scope):
        todo=[(material,scope)];added=set()
        while todo:
            key=todo.pop()
            if key in self.prepared:continue
            self.prepared.add(key);added.add(key);g=self.load(key[0])
            for nid in g.scopes[key[1]]['nodes']:todo.extend(self.resolve(key[0],nid))
        if added:self.effects(added)

    def free_effects(self,material,nid,scope):
        if (material,nid,scope) in self.node_effects:return self.node_effects[material,nid,scope]
        g=self.load(material);n=g.nodes[nid]
        owned=set();todo=[scope]
        while todo:
            sid=todo.pop();owned.add(sid);todo.extend(s['id'] for s in g.scopes if s['parent']==sid)
        reads={(material,s,name) for s,name in n['uses'] if s not in owned}
        writes={(material,s,name) for s,name in n['defs'] if s not in owned}
        if n['calls']:writes.update((material,s,name) for s,name in n['objects'] if s not in owned)
        self.node_effects[material,nid,scope]=reads,writes
        return reads,writes

    def effects(self,seeds):
        summaries=self.summaries;callers=defaultdict(set)
        for key in self.prepared:
            summaries.setdefault(key,(set(),set()))
            for nid in self.load(key[0]).scopes[key[1]]['nodes']:
                for callee in self.calls[key[0],nid]:callers[callee].add(key)
        pending=deque(seeds);queued=set(seeds);affected=set(seeds)
        while pending:
            key=pending.popleft();queued.remove(key)
            reads,writes=set(),set();g=self.load(key[0])
            for nid in g.scopes[key[1]]['nodes']:
                a,b=self.free_effects(key[0],nid,key[1]);reads.update(a);writes.update(b)
                for callee in self.calls[key[0],nid]:
                    a,b=summaries[callee];reads.update(a);writes.update(b)
            if (reads,writes)!=summaries[key]:
                summaries[key]=reads,writes
                for caller in callers[key]:
                    affected.add(caller)
                    if caller not in queued:queued.add(caller);pending.append(caller)
        for material,scope in affected:
            g=self.load(material);ids=g.scopes[scope]['nodes'];reaching={n:{} for n in ids}
            for nid in ids:self.extra[material,nid].clear()
            stable=False
            while not stable:
                stable=True
                for nid in ids:
                    node=g.nodes[nid];incoming=defaultdict(set)
                    for pred in node['pred']:
                        for key,values in reaching[pred].items():incoming[key].update(values)
                    a,b=self.free_effects(material,nid,scope);reads,writes=set(a),set(b)
                    for callee in self.calls[material,nid]:
                        a,b=summaries[callee];reads.update(a);writes.update(b)
                    for key in reads:self.extra[material,nid].update(incoming[key])
                    new={key:set(v) for key,v in incoming.items() if v}
                    # A callback can read a variable local to its caller. Its
                    # reaching value is defined here even though it is not a
                    # free effect of the caller's own function.
                    writes.update((material,s,name) for s,name in node['defs'])
                    for key in writes:new[key]={(material,nid)}
                    if new!=reaching[nid]:reaching[nid]=new;stable=False

    def setup_call(self,material,header,target):
        if target in self.calls[material,header]:return
        self.calls[material,header].add(target);self.prepare(*target)
        owner=material,self.load(material).nodes[header]['scope']
        if owner in self.prepared:self.effects({owner})

    def hooks(self,material,scope):
        g=self.load(material);ancestors=set();parent=g.scopes[scope]['parent']
        if g.scopes[scope]['kind']!='function':return set()
        while parent is not None:ancestors.add(parent);parent=g.scopes[parent]['parent']
        result=set()
        for n in g.nodes:
            if n['scope'] in ancestors and any(name in {'beforeEach','beforeAll','before','setup'} for name,_,_ in n['calls']):
                result.add((material,n['id']));self.prepare(material,n['scope'])
        parent=g.scopes[scope]['parent']
        if parent is not None and g.scopes[parent]['kind']=='class':
            for s in g.scopes:
                if s['parent']==parent and s['name'] in {'setUp','setup_method'}:
                    header=g.scopes[scope]['header'];self.setup_call(material,header,(material,s['id']))
                    result.add((material,header))
        if PurePosixPath(self.materials[material]['path']).suffix=='.py':
            parameters=g.scopes[scope]['params'];paths={material}
            directory=posixpath.dirname(self.materials[material]['path'])
            paths.update(m for p,versions in self.context['source_versions'].items() if p.endswith('/conftest.py') and
                         (directory==posixpath.dirname(p) or directory.startswith(posixpath.dirname(p)+'/')) for m in versions)
            versions=defaultdict(set)
            for other in paths:versions[self.materials[other]['path']].add(self.materials[other]['sha256'])
            for other in paths:
                module=self.load(other)
                for s in module.scopes:
                    if s['kind']!='function' or s['header'] is None:continue
                    header=module.nodes[s['header']];text=''.join(module.raw[a:b].decode() for a,b in header['ranges'])
                    definition=s['ast'];parent=definition.parent
                    decorators=[] if parent is None or parent.type!='decorated_definition' else [c for c in parent.named_children if c.type=='decorator']
                    fixture=any(re.search(r'(?:^|\.)fixture(?:\(|$)',module.text(d.named_children[0])) for d in decorators)
                    if fixture and (s['name'] in parameters or re.search(r'autouse\s*=\s*True',text)):
                        header=g.scopes[scope]['header']
                        if len(versions[self.materials[other]['path']])>1:
                            start,end=g.nodes[header]['ranges'][0]
                            self.version_alternatives[material,header,start,end,'framework_setup'].add((other,s['id']))
                            self.unresolved.add('source_version_not_bound:'+self.materials[other]['path'])
                            result.add((material,header));continue
                        self.setup_call(material,header,(other,s['id']));result.add((material,header))
        return result

    def dependencies(self,material,nid):
        g=self.load(material);n=g.nodes[nid];ancestors={n['scope']};parent=g.scopes[n['scope']]['parent']
        while parent is not None:ancestors.add(parent);parent=g.scopes[parent]['parent']
        base={(material,i) for i in n['data']|n['state']|n['control'] if g.nodes[i]['scope'] in ancestors}
        return base|self.extra[material,nid]

    def callers(self,material,scope):
        if (material,scope) in self.caller_sites:return self.caller_sites[material,scope]
        name=self.load(material).scopes[scope]['name'];result=set()
        candidates={material}
        domain=self.context['source_versions'] if self.context['execution'] is None else self.context['input_versions']
        for path,versions in domain.items():
            if name.startswith('<'):continue
            if PurePosixPath(path).suffix not in SUFFIXES:continue
            for candidate in versions:
                info=self.materials[candidate];key=info['path'],info['sha256']
                raw=self.cache[key].raw if key in self.cache else self.read_source(info)[0]
                if name.encode() in raw:candidates.add(candidate)
        for source in candidates:
            g=self.load(source)
            for n in list(g.nodes):
                if not n['calls']:continue
                targets=self.resolve(source,n['id'])
                if (material,scope) in targets and scope not in (n['callback_scopes'] if source==material else set()):
                    self.prepare(source,n['scope']);result.add((source,n['id']))
        self.caller_sites[material,scope]=result
        return result

    def slice(self,material,seed):
        return self.slice_many([(material,seed)])

    def grouped_slices(self,material,seeds):
        """Share all dependence endpoints in each validation test's view."""
        graph=self.load(material)
        scopes={graph.header_scopes[n] if n in graph.header_scopes and
                graph.scopes[graph.header_scopes[n]]['kind']=='function' else graph.nodes[n]['scope'] for n in seeds}
        for scope in sorted(scopes):self.prepare(material,scope)
        for scope in sorted(scopes):self.hooks(material,scope)
        dependencies={n['id']:{p for m,p in self.dependencies(material,n['id']) if m==material} for n in graph.nodes}
        groups=validation_groups(graph,seeds,dependencies=dependencies)
        result=[]
        for group in groups:
            view=self.slice_many([(material,n) for n in group['frontier']])
            for file in view['files']:
                module=self.load(file['material'])
                ranges=attached_comments(module,file['ranges'])
                file['ranges']=source_syntax(module,file['nodes']+file['context_nodes'],ranges)
            view['embedded_inputs']=self.embedded(view)
            result.append({'group':group,'view':view})
        return result

    def slice_many(self,seeds):
        """Recover one view for related ports, sharing the dependence traversal."""
        entries=set(seeds);pending=list(entries);setup=set();entry_scopes={}
        while pending:
            source,nid=pending.pop();g=self.load(source);scope=g.nodes[nid]['scope']
            if nid in g.header_scopes and g.scopes[g.header_scopes[nid]]['kind']=='function':scope=g.header_scopes[nid]
            entry_scopes[source,nid]=scope
            self.prepare(source,scope);setup.update(self.hooks(source,scope))
            setup.update((source,n) for n in g.scopes[scope]['cleanup'])
            for caller in self.callers(source,scope):
                if caller not in entries:entries.add(caller);pending.append(caller)
        # Caller discovery may add global effects. Build successors only after
        # that discovery is complete, so query order does not change the slice.
        forward=set();scope_successors={}
        for (source,nid),scope in entry_scopes.items():
            g=self.load(source);key=source,scope
            if key not in scope_successors:
                successors=defaultdict(set)
                for node in g.scopes[scope]['nodes']:
                    for dep in self.dependencies(source,node):successors[dep].add((source,node))
                scope_successors[key]=successors
            successors=scope_successors[key]
            todo=[(source,nid)]
            while todo:
                current=todo.pop()
                if current in forward:continue
                forward.add(current);todo.extend(successors[current]-forward)
        selected=set();todo=list(forward|setup);bindings=set();context=set()
        while todo:
            source,nid=todo.pop()
            if (source,nid) in selected:continue
            selected.add((source,nid));g=self.load(source);node=g.nodes[nid]
            todo.extend(self.dependencies(source,nid))
            parent=node['scope']
            while parent is not None:
                s=g.scopes[parent]
                if s['header'] is not None:todo.append((source,s['header']))
                if 'creator' in s:context.add((source,s['creator']))
                parent=s['parent']
            for target,scope in self.calls[source,nid]:
                self.prepare(target,scope);module=self.load(target);s=module.scopes[scope]
                bindings.add((source,nid,target,scope))
                effects=s['returns']|s['cleanup']|{i for i in s['nodes'] if module.nodes[i]['observation'] or module.nodes[i]['objects'] or
                                         any(owner!=scope for owner,name in module.nodes[i]['defs'])}
                if s['header'] is not None:effects.add(s['header'])
                todo.extend((target,i) for i in effects)
        files=[]
        for source in sorted({m for m,n in selected|context}):
            g=self.load(source);ids=sorted(n for m,n in selected if m==source);headers=sorted(n for m,n in context-selected if m==source)
            ranges=merge_ranges(span for n in ids+headers for span in g.nodes[n]['ranges'])
            files.append({'material':source,'path':self.materials[source]['path'],
                          'nodes':ids,'context_nodes':headers,'ranges':ranges,'issues':g.issues,
                          'binding':self.context['source_basis'].get(source,'static_source')})
        calls=[]
        for source,nid,target,scope in sorted(bindings):
            node=self.load(source).nodes[nid];callee=self.load(target).scopes[scope]
            sites=[s for s in self.sites[source,nid] if s[2:4]==(target,scope)]
            if not sites:
                caller_scope=self.load(source).header_scopes[nid]
                calls.append({'site':[source,nid],'callee':[target,scope],'parameters':callee['parameter_order'],
                              'arguments':[],'kind':'framework_setup','basis':'framework_rule',
                              'provided_parameter':callee['name'] if callee['name'] in self.load(source).scopes[caller_scope]['params'] else None})
            for start,end,_,_,kind in sorted(sites):
                graph=self.load(source);call=next(c for _,_,c in node['calls'] if c.start_byte==start and c.end_byte==end)
                args=call.child_by_field_name('arguments');arguments=[] if args is None else args.named_children
                mapping=[];parameters=callee['parameter_order'];kinds=callee['parameter_kinds']
                receiver=parameters[0] if kind=='bound_method' and parameters and parameters[0] in {'self','cls'} else None
                positional=[p for p in parameters if kinds[p] in {'positional_only','positional_or_keyword'} and p!=receiver]
                rest=next((p for p in parameters if kinds[p]=='var_positional'),None)
                keywords=next((p for p in parameters if kinds[p]=='var_keyword'),None)
                position=0;unpacked=False
                for argument in arguments:
                    keyword=argument.child_by_field_name('name') if argument.type=='keyword_argument' else None
                    splat=argument.type in {'list_splat','dictionary_splat','spread_element'}
                    if keyword is not None:
                        name=graph.text(keyword)
                        formal=name if name in kinds and kinds[name] in {'positional_or_keyword','keyword_only'} else keywords
                    elif splat:
                        formal=None;unpacked=True;self.unresolved.add('argument_unpacking_unresolved')
                    else:
                        formal=(positional[position] if position<len(positional) else rest) if not unpacked else None
                        position+=1
                    mapping.append({'parameter':formal if kind in {'direct','bound_method'} else None,'range':[argument.start_byte,argument.end_byte]})
                calls.append({'site':[source,nid],'callee':[target,scope],'call_range':[start,end],
                              'parameters':parameters,'arguments':mapping,'kind':kind,'basis':'static_resolution',
                              'bound_receiver':receiver})
        result = {'entries':[list(e) for e in sorted(entries)],'files':files,'calls':calls,
                'version_alternatives':[{'site':[source,nid],'range':[start,end],'kind':kind,
                                         'callees':[list(c) for c in sorted(callees)]}
                                        for (source,nid,start,end,kind),callees in sorted(self.version_alternatives.items()) if (source,nid) in selected],
                'state_dependencies':[[list(a),list(b)] for b in sorted(selected) for a in sorted(self.extra[b]) if a in selected],
                'unresolved':sorted(self.unresolved),'execution':self.context['execution'],
                'unresolved_versions':self.context['unresolved_versions'],
                'unresolved_bytecode_sources':self.context['unresolved_bytecode_sources']}
        connect_calls(result, self)
        return result

    def embedded(self,view):
        """Literal program inputs: retain bytes plus separately parsed slices."""
        result=[]
        for file in view['files']:
            source=file['material'];g=self.load(source);suffix=PurePosixPath(file['path']).suffix
            for nid in file['nodes']:
                for name,callee,call in g.nodes[nid]['calls']:
                    if name not in {'eval','exec','compile','parse','loads'}:continue
                    args=call.child_by_field_name('arguments')
                    if args is None or not args.named_children:continue
                    argument=args.named_children[0]
                    if argument.type not in STRINGS:
                        result.append({'site':[source,nid],'call':[call.start_byte,call.end_byte],
                                       'reason':'embedded_value_not_observed; outer dependencies retained'});continue
                    text=g.text(argument)
                    if text.startswith('`') and suffix!='.py':value=text[1:-1]
                    else:
                        try:value=ast.literal_eval(text)
                        except (ValueError,SyntaxError):
                            result.append({'site':[source,nid],'reason':'literal_encoding_not_supported'});continue
                    if not isinstance(value,str):continue
                    binding=g._binding(g.nodes[nid]['scope'],g.text(callee)) if callee is not None else None
                    builtin=callee is not None and callee.type in IDENTS and not g.definitions[binding]
                    mode='exec' if name in {'eval','exec','compile'} and builtin else 'source_input'
                    language=('.py' if suffix=='.py' and (builtin or (callee is not None and g.text(callee)=='ast.parse'))
                              else '.js' if suffix in {'.js','.jsx','.ts','.tsx'} and builtin and name=='eval' else None)
                    item={'site':[source,nid],'range':[argument.start_byte,argument.end_byte],
                          'text':value,'mode':mode,'language':language,'basis':'static_literal'}
                    if language is not None:
                        inner=SourceGraph({'id':'embedded','path':'<embedded>'+language,'raw':value.encode()})
                        seeds=[n['id'] for n in inner.nodes if n['calls'] or n['observation'] or n['kind'] in {'return','yield'}]
                        if not seeds and inner.nodes:seeds=[inner.nodes[-1]['id']]
                        item.update(graph=inner.export_nodes(),issues=inner.issues,
                                    slices=[inner.slice(n) for n in seeds] if mode=='exec' else [])
                    elif callee is not None and g.text(callee)=='json.loads':
                        try:item['structure']=json.loads(value)
                        except json.JSONDecodeError as error:item['issue']=str(error)
                    else:item['reason']='embedded_language_unresolved; input retained'
                    result.append(item)
        return result


class TrajectorySlicer:
    def __init__(self,manifest_path):
        self.manifest_path=Path(manifest_path).resolve();self.manifest=read_manifest(self.manifest_path)
        self.trajectory=TrajectoryGraph(self.manifest['trajectory']);self.cache={};self.programs={};self.views={};self.sources={};self.closures={}
        self.source_contents={};self.store=BlobStore(self.trajectory.path.parent/'blobs')
        self.documents={str(self.manifest_path):self.manifest,str(self.trajectory.path):self.trajectory.data}
        self.material_refs={};self.code_versions=defaultdict(list)
        self.execution_contexts = {}
        for identity,material in self.trajectory.materials.items():
            if 'source' in material:self.material_refs[material['source']]=identity
            if material['kind'] in {'file','code_input'}:self.code_versions[material['sha256']].append(identity)

    def program_source(self,info):
        """Decode each immutable program version once across execution contexts."""
        key=info['path'],info['sha256']
        if key not in self.source_contents:
            raw=self.store.read(info['sha256']);error=None
            if info['kind']=='file':
                try:text,error=decode_material(info['path'],raw)
                except UnicodeDecodeError as failure:text,error=None,str(failure)
                if text is not None:raw=text.encode()
            self.source_contents[key]=raw,error
        return self.source_contents[key]

    def source(self,reference,*,base=None):
        if base is not None:reference=reference_path(reference,base)
        if reference not in self.sources:
            if reference in self.material_refs:
                entry=self.trajectory.materials[self.material_refs[reference]]
                raw,_=self.program_source(entry)
                self.sources[reference]=entry['path'],entry['sha256'],raw
                return self.sources[reference]
            filename,_,fragment=reference.partition('#/')
            if filename not in self.documents:self.documents[filename]=read_json(filename)
            collection,index=fragment.split('/')
            entry=self.documents[filename][collection][index if collection=='materials' else int(index)]
            if filename==str(self.trajectory.path) and collection=='materials':self.material_refs[reference]=index
            info=entry if collection=='materials' else {'kind':'file',**entry}
            raw,_=self.program_source(info);path=entry['path']
            self.sources[reference]=path,entry['sha256'],raw
        return self.sources[reference]

    def command_references(self,unit,digest):
        """Bind a decoded command literal to its observed material occurrences."""
        action=Path(unit['source']).parent.name;result=[]
        for identity in self.code_versions[digest]:
            info=self.trajectory.materials[identity]
            if 'inline' in unit:
                matches=info['kind']=='code_input' and PurePosixPath(info['path']).suffix==PurePosixPath(unit['path']).suffix
            else:matches=info['kind']=='file' and info['path']==unit['path']
            if not matches:continue
            producer=info['producer']
            owner=(None if producer is None else producer if self.trajectory.events[producer]['kind']=='action'
                   else self.trajectory.events[producer]['action'])
            generated=owner==action
            consumed=any(self.trajectory.events[e]['action']==action for e,k in self.trajectory.after[identity] if k in SOURCE_USES)
            if generated or consumed:result.append(str(self.trajectory.path)+'#/materials/'+identity)
        return result

    def static_groups(self,source,graph,ports,*,material=None):
        if material is None:
            program=ContextProgram.from_source(graph);root=graph.source['id']
        else:
            program=ContextProgram(self.trajectory.materials,self.trajectory.static_context(material),self.cache,
                                   self.program_source);root=material
        rows=[]
        for row in program.grouped_slices(root,[p['node'] for p in ports]):
            view=row['view'];view.update(source=source,mode='static_program',reason='no_observed_consumer')
            if material is None:
                file,=view.pop('files')
                view['static_slice']={k:file[k] for k in ('nodes','context_nodes','ranges')};view['issues']=file['issues']
                view['_source_key'] = [graph.source['path'], hashlib.sha256(graph.raw).hexdigest()]
            else:
                view.update(material=material,**self.episode([material],[f['material'] for f in view['files']],False))
            rows.append({'group':row['group'],'view':view})
        return rows

    def grouped_locations(self,source,ports):
        """Slice related public ports together, separately in each execution."""
        path,digest,raw=self.source(source);consumers=self.trajectory.consumers(path,digest)
        if source in self.material_refs:
            consumers=[e for e,k in self.trajectory.after[self.material_refs[source]] if k in SOURCE_USES]
        if (path,digest) not in self.cache:self.cache[path,digest]=SourceGraph({'id':source,'path':path,'raw':raw})
        contexts={}
        for event in consumers:contexts.setdefault(self.trajectory.events[event]['execution'],event)
        if not contexts:
            candidates=([self.material_refs[source]] if source in self.material_refs else
                        [m for m in self.code_versions[digest] if self.trajectory.materials[m]['path']==path])
            if candidates:
                return [row for material in candidates for row in self.static_groups(source,self.cache[path,digest],ports,material=material)]
            return self.static_groups(source,self.cache[path,digest],ports)
        results=[]
        for execution,event in contexts.items():
            root=next(m for m,k in self.trajectory.before[event] if k in SOURCE_USES and
                      self.trajectory.materials[m]['path']==path and self.trajectory.materials[m]['sha256']==digest)
            mode=source_role(path,self.trajectory.events[execution])
            if mode=='source_input':
                results.append({'group':{'matches':[p['node'] for p in ports],'frontier':[],
                                         'boundary':['source_input',root]},
                                'view':{'source':source,'material':root,'mode':mode,'execution':execution,'consumer':event,
                                        'range':[0,len(raw)],**self.episode([event],[root],False)}})
                continue
            if execution not in self.programs:
                self.programs[execution]=ContextProgram(self.trajectory.materials,self.trajectory.context(event),self.cache,
                                                       self.program_source)
            program=self.programs[execution]
            for row in program.grouped_slices(root,[p['node'] for p in ports]):
                view=row['view'];inputs=[f['material'] for f in view['files']]
                view.update(source=source,mode='program',consumer=event,basis='static_dependencies_in_observed_IO_context',
                            **self.episode([event],inputs,False))
                self.attach_execution(view, program)
                results.append(row)
        return results

    def attach_execution(self, view, program):
        execution = view['execution']
        if execution not in self.execution_contexts:
            self.execution_contexts[execution] = execution_context(self.trajectory, execution)
        context = self.execution_contexts[execution]
        view['material_links'] = material_links(view, program, context, self.trajectory.materials)
        # The full inventory is shared per execution, never copied per view.
        view['execution_context'] = execution

    def static(self,source,path,raw,digest,start,end):
        if PurePosixPath(path).suffix not in SUFFIXES:
            return {'source':source,'range':[start,end],'execution':None,'mode':'data','reason':'no_observed_consumer'}
        key=path,digest
        if key not in self.cache:self.cache[key]=SourceGraph({'id':str(source),'path':path,'raw':raw})
        g=self.cache[key];criterion=g.criterion(start,end)
        return {'source':source,'criterion':criterion,'execution':None,'reason':'no_observed_consumer',
                'static_slice':g.slice(criterion['node']) if criterion is not None else None,'issues':g.issues}

    def episode(self,seeds,inputs,expand):
        if not expand:return {'trajectory_criterion':{'seeds':list(seeds),'inputs':list(inputs)}}
        key=tuple(seeds),tuple(sorted(inputs))
        if key not in self.closures:self.closures[key]=self.trajectory.slice(seeds,inputs=inputs)
        return {'trajectory':self.closures[key]}

    def location(self,source,start,end,*,consumer=None,expand_trajectory=True,base=None):
        if base is not None:source=reference_path(source,base)
        trajectory=self.trajectory;path,digest,raw=self.source(source);consumers=trajectory.consumers(path,digest)
        if source in self.material_refs:
            consumers=[e for e,k in trajectory.after[self.material_refs[source]] if k in SOURCE_USES]
        assert 0<=start<end<=len(raw),'Criterion uses bytes of the decoded UTF-8 source'
        if source in self.material_refs and trajectory.materials[self.material_refs[source]]['kind'] not in {'file','code_input'}:
            root=self.material_refs[source];info=trajectory.materials[root]
            return [{'mode':'data','material':root,'source':source,'range':[start,end],
                     'origin':info['origin'] if 'origin' in info else 'replay',**self.episode([root],[],expand_trajectory)}]
        if consumer is not None:
            assert consumer in consumers,'Criterion must belong to a version actually consumed at this event'
            consumers=[consumer]
        contexts={}
        for event in consumers:contexts.setdefault(trajectory.events[event]['execution'],event)
        results=[]
        for execution,event in contexts.items():
            root=next(m for m,kind in trajectory.before[event] if kind in SOURCE_USES and
                      trajectory.materials[m]['path']==path and trajectory.materials[m]['sha256']==digest)
            mode=source_role(path,trajectory.events[execution])
            if PurePosixPath(path).suffix not in SUFFIXES or mode=='source_input':
                data={'consumer':event,'source':source,'range':[start,end],'execution':execution,'mode':mode,
                      'material':root,**self.episode([event],[root],expand_trajectory)}
                if PurePosixPath(path).suffix not in SUFFIXES:data['mode']='data'
                if PurePosixPath(path).suffix=='.json':
                    try:data['structure']=json.loads(raw)
                    except json.JSONDecodeError as error:data['issue']=str(error)
                results.append(data);continue
            key=execution
            if key not in self.programs:self.programs[key]=ContextProgram(trajectory.materials,trajectory.context(event),self.cache,self.program_source)
            program=self.programs[key];g=program.load(root);criterion=g.criterion(start,end)
            if criterion is None:
                results.append({'consumer':event,'source':source,'range':[start,end],'issues':g.issues or ['criterion_not_mapped']});continue
            work=(key,root,criterion['node'])
            if work not in self.views:
                result=program.slice(root,criterion['node']);result['embedded_inputs']=program.embedded(result)
                self.attach_execution(result, program)
                self.views[work]=result
            result=self.views[work];roots=[m['material'] for m in result['files']]
            results.append({**result,**self.episode([event],roots,expand_trajectory),
                            'consumer':event,'source':source,'criterion':criterion,'mode':'program',
                            'basis':'static_dependencies_in_observed_IO_context'})
        if not contexts:
            view=self.static(source,path,raw,digest,start,end)
            if source in self.material_refs:
                material=self.material_refs[source]
                inputs = []
                if PurePosixPath(path).suffix in SUFFIXES and view['criterion'] is not None:
                    program = ContextProgram(trajectory.materials, trajectory.static_context(material), self.cache,
                                             self.program_source)
                    criterion = view['criterion']
                    view = program.slice(material, criterion['node'])
                    view.update(source=source, criterion=criterion, mode='static_program', reason='no_observed_consumer')
                    view['embedded_inputs'] = program.embedded(view)
                    inputs = [file['material'] for file in view['files']]
                view.update(material=material,**self.episode([material],inputs,expand_trajectory))
            results.append(view)
        return results


def slice_location(manifest_path,source,start,end,*,consumer=None,base=None):
    slicer = TrajectorySlicer(manifest_path)
    views = slicer.location(source,start,end,consumer=consumer,base=base)
    for view in views:
        for file in view.get('files', []):
            info = slicer.trajectory.materials[file['material']]
            graph = slicer.cache[info['path'], info['sha256']]
            file['source'] = str(slicer.trajectory.path) + '#/materials/' + file['material']
            file['behavior'] = source_behavior(graph, file['nodes'] + file['context_nodes'])
        if 'execution_context' in view:
            view['execution_context'] = slicer.execution_contexts[view['execution_context']]
        if view.get('static_slice') is not None:
            path, digest, _ = slicer.source(view['source'])
            view['behavior'] = source_behavior(slicer.cache[path,digest], view['static_slice']['nodes'])
    return views


def slice_targets(manifest_path,out):
    """D → grouped program views plus command/output/data material entries."""
    out=Path(out);out.mkdir(parents=True)
    slicer=TrajectorySlicer(manifest_path)
    materials=materials_from_manifest(slicer.manifest_path,slicer.manifest,slicer.trajectory.data)
    actions=[{'id':m['action_id'],'command':m['text'],'expected':m['expected']}
             for m in materials if m['kind']=='command']
    connections=MaterialConnections(materials,actions,root='/app')
    command_actions={m['source']:m['action_id'] for m in materials if m['kind']=='command'}
    used_materials=set();execution_materials={}
    targets=targets_from_collection(slicer.manifest_path,slicer.manifest,materials,slicer.trajectory.data)
    write_json(out/'targets.json',relative_references(targets,out))
    units_by_source=defaultdict(list)
    for index,unit in enumerate(targets['units']):
        if unit['anchors']:units_by_source[unit['source'],unit.get('inline'),unit.get('write')].append((index,unit))
    local_queries={(row['source'],row.get('inline'),row.get('write')):row['points'] for row in targets['local_queries']}
    pending=[];closures={};work_views={};group_count=0;matched_count=0;view_count=0
    graph_files = {}; graph_origins = {}; context_files = {}
    paths=set();action_ids=set()

    def graph_reference(path, digest, origin):
        key = path, digest
        if key not in graph_files:
            graph_files[key] = 'graphs/' + f'{len(graph_files):06}.json.gz'
            graph_origins[key] = origin
        return graph_files[key]

    def save(source,by_node,row,action,root_graph):
        nonlocal group_count,view_count
        group=row['group'];view=row['view']
        entries=view.pop('entries') if view['mode'] in {'program','static_program'} else None
        source_views=[];owners=set() if action is None else {action}
        if view['execution'] is not None:
            owners.add(slicer.trajectory.events[view['execution']]['action'])
        for file in view.get('files', []):
            info = slicer.trajectory.materials[file['material']]
            graph=slicer.cache[info['path'],info['sha256']]
            source_views.append((graph,file['ranges']))
            producer=info['producer']
            if producer is not None:
                event=slicer.trajectory.events[producer]
                owners.add(producer if event['kind']=='action' else event['action'])
            origin = str(slicer.trajectory.path) + '#/materials/' + file['material']
            file['source'] = origin
            file['graph'] = graph_reference(info['path'], info['sha256'], origin)
        if 'static_slice' in view:
            path, digest = view.pop('_source_key')
            source_views.append((slicer.cache[path,digest],view['static_slice']['ranges']))
            view['graph'] = graph_reference(path, digest, source)
        view['candidate_material_links']=connections.links(source_views,actions=owners)
        used_materials.update(link['material'] for link in view['candidate_material_links'])
        execution=view['execution']
        if execution is not None and execution not in execution_materials:
            if execution not in slicer.execution_contexts:
                slicer.execution_contexts[execution]=execution_context(slicer.trajectory,execution)
            links=connections.observed_links(slicer.execution_contexts[execution],slicer.trajectory.materials,
                                             str(slicer.trajectory.path))
            execution_materials[execution]=links
            used_materials.update(link['material'] for link in links)
        if 'execution_context' in view:
            execution = view.pop('execution_context')
            if execution not in context_files:
                filename = 'contexts/' + str(len(context_files)) + '.json'
                write_json(out / filename, slicer.execution_contexts[execution])
                context_files[execution] = filename
            view['execution_context_ref'] = context_files[execution]
        if 'trajectory_criterion' in view:
            closure=view.pop('trajectory_criterion');signature=hashlib.sha256(json.dumps(closure,sort_keys=True).encode()).hexdigest()
            if signature not in closures:
                filename='episodes/'+str(len(closures))+'.json'
                write_json(out/filename,closure);closures[signature]=filename
            view['trajectory_ref']=closures[signature]
        signature=hashlib.sha256(json.dumps(view,sort_keys=True).encode()).hexdigest()
        if signature not in work_views:
            filename='views/'+str(len(work_views))+'.json'
            write_json(out/filename,relative_references(view,out));work_views[signature]=filename
        selected=[by_node[n] for n in group['matches']]
        result={'source':source,'graph':root_graph,
                'ports':selected,'group':group,'views':[work_views[signature]]}
        if entries is not None:result['program_entries']=entries
        write_json(out/'slices'/f'{group_count:06}.json',relative_references(result,out))
        group_count+=1;view_count+=1

    for (reference,inline,write),units in units_by_source.items():
        unit=units[0][1];path=unit['path'];command=inline is not None or write is not None
        source={k:unit[k] for k in ('source','inline','write') if k in unit} if command else reference
        if command:
            raw=read_target_source(unit).encode();digest=hashlib.sha256(raw).hexdigest()
        else:path,digest,raw=slicer.source(reference)
        key=path,digest
        if key not in slicer.cache:slicer.cache[key]=SourceGraph({'id':str(source),'path':path,'raw':raw})
        graph=slicer.cache[key]
        root_graph=graph_reference(path, digest, source)
        query_points=local_queries.get((reference,inline,write),[])
        ports,unmapped=matching_statements(graph,units,query_points)
        if unmapped:pending.append({'source':source,'reason':'criterion_not_mapped','locations':unmapped,'issues':graph.issues})
        if not ports:
            pending.append({'source':source,'entries':[i for i,u in units],'reason':'no_call_or_source_input_match'})
            continue
        matched_count+=len(ports);paths.add(path)
        by_node={p['node']:p for p in ports}
        if command:action_ids.add(Path(reference).parent.name)
        references=slicer.command_references(unit,digest) if command else [reference]
        action=command_actions[reference] if command else None
        if references:
            for ref in references:
                for row in slicer.grouped_locations(ref,ports):save(source,by_node,row,action,root_graph)
        else:
            for row in slicer.static_groups(source,graph,ports):save(source,by_node,row,action,root_graph)
    file_materials={str(slicer.trajectory.path)+'#/materials/'+identity:m
                    for identity,m in slicer.trajectory.materials.items() if m['kind']=='file'}
    files=[{'source':source,'path':m['path']} for source,m in file_materials.items()]
    carriers=select_material_entries(actions,targets['targets'],targets['changed_paths'],paths,action_ids,files)
    selected_actions={a['action'] for a in carriers['actions']}
    selected_files={(file_materials[f['source']]['path'],file_materials[f['source']]['sha256']) for f in carriers['files']}
    selected_sources={m['source'] for m in materials
                      if m['kind'] in {'command','output'} and m['action_id'] in selected_actions
                      or m['kind']=='file' and (m['path'],m['sha256']) in selected_files}
    carriers['records']=[r['id'] for r in targets['records'] if r['source'] in selected_sources]
    write_json(out/'material_entries.json',relative_references(carriers,out))
    write_behavior_graph(out/'candidate_materials.json.gz',{
        'documents':relative_references([connections.documents[m] for m in sorted(used_materials)],out),
        'executions':execution_materials})
    for (path,digest), graph in slicer.cache.items():
        key = path, digest
        if key not in graph_files:
            material = next(m for m in slicer.code_versions[digest] if slicer.trajectory.materials[m]['path'] == path)
            graph_reference(path, digest, str(slicer.trajectory.path) + '#/materials/' + material)
        write_behavior_graph(out / graph_files[key], {
            'path':path, 'sha256':digest, 'origin':relative_references({'source':graph_origins[key]},out)['source'],
            'nodes':graph.export_nodes(), 'issues':graph.issues,
            'behavior':source_behavior(graph, [node['id'] for node in graph.nodes]),
        })
    summary={'entry_groups':group_count,'matched_statements':matched_count,'views':view_count,'source_graphs':len(slicer.cache),
             'shared_views':len(work_views),'shared_episodes':len(closures),'pending_roots':pending,
             'material_entries':'material_entries.json',
             'candidate_materials':'candidate_materials.json.gz',
             'linked_candidate_materials':len(used_materials),
             'shared_material_executions':len(execution_materials),
             'material_entry_counts':{key:len(carriers[key]) for key in ('actions','files','records')},
             'trajectory':str(slicer.trajectory.path),'manifest':str(slicer.manifest_path),'retained_B_records':len(targets['records']),
             'shared_execution_contexts': len(context_files),
             'trajectory_mode':'criteria_on_shared_graph','new_llm_calls':0}
    write_json(out/'summary.json',relative_references(summary,out))
    return summary


class SliceEvidenceReader:
    """Reuse the trajectory and source facts when preparing multiple LLM inputs."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.summary = resolve_references(read_json(self.directory / 'summary.json'), self.directory)
        self.trajectory = TrajectoryGraph(self.summary['trajectory'])
        self.graphs, self.episodes = {}, {}
        pool=read_behavior_graph(self.directory/self.summary['candidate_materials'])
        self.candidate_documents={d['id']:d for d in resolve_references(pool['documents'],self.directory)}
        self.execution_materials=pool['executions']

    def graph(self, reference):
        if reference not in self.graphs:
            self.graphs[reference] = read_behavior_graph(self.directory / reference)
        return self.graphs[reference]

    def read(self, view_path):
        directory, trajectory = self.directory, self.trajectory
        view = resolve_references(read_json(directory / view_path), directory)
        files = view.get('files', [])
        if 'static_slice' in view:
            graph = self.graph(view['graph'])
            selected = view['static_slice']
            files = [{'path': graph['path'], 'graph': view['graph'],
                      'nodes': selected['nodes'], 'context_nodes': selected['context_nodes'], 'ranges': selected['ranges']}]
        sources = []
        for file in files:
            graph = self.graph(file['graph'])
            origin = (file['source'] if 'source' in file else
                      resolve_references({'source': graph['origin']}, directory)['source'])
            facts = select_exported_behavior(graph['behavior'], file['nodes'] + file['context_nodes'])
            sources.append({**file, 'source': origin, 'behavior': facts, 'issues': graph['issues']})
        view['behavior_sources'] = sources
        if view['execution'] is not None:
            view['candidate_material_links'].extend(self.execution_materials[view['execution']])
        selected={link['material'] for link in view['candidate_material_links']}
        view['candidate_materials']=[self.candidate_documents[m] for m in sorted(selected)]
        if 'execution_context_ref' in view:
            view['execution_context'] = read_json(directory / view['execution_context_ref'])
        if 'trajectory_ref' in view:
            reference = view['trajectory_ref']
            if reference not in self.episodes:
                criterion = read_json(directory / reference)
                self.episodes[reference] = trajectory.slice(criterion['seeds'], inputs=criterion['inputs'])
            view['trajectory'] = self.episodes[reference]
            view['events'] = [{'id': event, **trajectory.events[event]} for event in view['trajectory']['events']]
            view['materials'] = [{**trajectory.materials[m], 'material': m,
                                  'source': str(trajectory.path) + '#/materials/' + m}
                                 for m in view['trajectory']['materials']]
        alternatives = {m for alternative in view.get('version_alternatives', []) for m, _ in alternative['callees']}
        view['alternative_sources'] = [{'material': m, **trajectory.materials[m],
                                        'source': str(trajectory.path) + '#/materials/' + m}
                                       for m in sorted(alternatives)]
        view['complete_history'] = str(directory / 'targets.json')
        view['material_entries'] = str(directory / 'material_entries.json')
        view['collection'] = self.summary['manifest']
        return view


def read_slice_evidence(directory, view_path):
    """Read one view; sources remain readable through B/D's source APIs."""
    return SliceEvidenceReader(directory).read(view_path)
