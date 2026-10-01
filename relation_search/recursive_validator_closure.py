"""Finite source closure of recursive validation helpers.

Vertices are source functions, not unfolded execution contexts. Edges retain
the exact guarded actual/formal transformation. An SCC is a least reachable
context closure, not a claim that its predicates hold or recursion terminates.
Production implementations are opaque and never become validation oracles.
"""
from __future__ import annotations

import hashlib
import json
import builtins

from anchor_retrieval.graph import _locally_rebound
from anchor_retrieval.index import Index
from anchor_retrieval.syntax import CALLS, Unit, call_parts, child, is_test_path, walk
from relation_search.admission import program_candidate
from relation_search.oracle_evidence import _modified_sources
from relation_search.test_role_summaries import (
    _testing_parameter, bind_fixed_prefix, direct_testing_failure,
    failure_guard_constraints,
)
from relation_search.test_roles import (
    NESTED, TRUSTED, _Analysis, _Context, _Ref, _guard_contexts, _owned,
)
from relational_gap.frontend import _exception_observations, _parameters


VERSION = 'recursive-validator-source-closure.v1'
GO_PREDECLARED_CALLABLES={'append','cap','clear','close','complex','copy','delete','imag','len','make','max','min',
                         'new','panic','print','println','real','recover'}
CLOSURE_SEMANTICS = '''Start with the fixed root test state and represented
fixture/callback entries. At a represented call site, evaluate its actual
expressions in the caller state at that site and bind the target formals.
Apply only transitions whose supplied lexical guards are reached normally.
Reachable states are the least set closed under these source transitions,
including recursive SCC edges; they are not a fixed-depth unfolding.
For each local check site, assess its passing predicate for EVERY state in this
reachable closure in which the check contributes to the test verdict. Respect
explicit matching exception consumption. Correctness is required only for
this reachable domain, not for every possible input to the helper.
This graph proves source-site representation, not path feasibility, termination,
callback scheduling, heap facts, or predicate truth. Missing validator dispatch
or bindings leave source closure partial. Ordinary production internals are
opaque and are not additional independent test expectations.'''


def _span(source,node):
    return dict(path=source.path,start_byte=node.start_byte,end_byte=node.end_byte)


def _inside(inner,outer):
    return inner['path']==outer['path'] and outer['start_byte']<=inner['start_byte']<=inner['end_byte']<=outer['end_byte']


def _source(source,node):
    return dict(namespace='modified',span=_span(source,node),code=source.text(node))


def _key(unit):
    return unit.source.path,unit.node.start_byte,unit.node.end_byte


def _same_position(left,right):
    return all(left[key]==right[key] for key in ('path','start_byte','end_byte'))


def _canonical(position,changes):
    def boundary(value,end=False):
        shift=0
        for row in sorted(changes,key=lambda row:row['span']['start_byte']):
            at,old=row['span'],row['original_span']
            if at['path']!=position['path']:
                continue
            if at['start_byte']<=value<at['end_byte']:
                return old['end_byte'] if end else old['start_byte']
            if value>=at['end_byte']:
                shift+=at['end_byte']-at['start_byte']-(old['end_byte']-old['start_byte'])
        return value-shift
    return dict(path=position['path'],start_byte=boundary(position['start_byte']),end_byte=boundary(position['end_byte'],True))


class _LocalSites(_Analysis):
    """Reuse v3 primitive/guard semantics while collecting one vertex once."""
    def visit(self,context,depth=0,ancestry=()):
        if depth==0:
            super().visit(context,depth,ancestry)


def _scc(vertices,edges):
    graph={vertex:[] for vertex in vertices}
    for edge in edges:
        graph[edge['caller']].append(edge['callee'])
    counter=0;indices={};low={};stack=[];active=set();groups=[]
    def visit(vertex):
        nonlocal counter
        indices[vertex]=low[vertex]=counter;counter+=1;stack.append(vertex);active.add(vertex)
        for target in sorted(set(graph[vertex])):
            if target not in indices:
                visit(target);low[vertex]=min(low[vertex],low[target])
            elif target in active:
                low[vertex]=min(low[vertex],indices[target])
        if low[vertex]==indices[vertex]:
            members=[]
            while True:
                member=stack.pop();active.remove(member);members.append(member)
                if member==vertex:
                    break
            groups.append(sorted(members))
    for vertex in sorted(vertices):
        if vertex not in indices:
            visit(vertex)
    return sorted(groups)


class _Graph:
    def __init__(self,sources,owner,changes,*,max_units,max_edges):
        self.analysis=_LocalSites(sources,None,changes,max_depth=8,max_contexts=max_units+1)
        self.index=self.analysis.index;self.owner=owner;self.changes=changes
        self.max_units,self.max_edges=max_units,max_edges
        self.units={};self.vertices={};self.sites=[];self.edges=[];self.entries=[]
        self.unknowns=[];self.opaque=[];self.queue=[];self.seen=set();self.site_keys={};self.edge_keys=set()

    def unknown(self,code,**facts):
        row=dict(code=code,**facts)
        if row not in self.unknowns:
            self.unknowns.append(row)

    def validator(self,unit):
        return (unit.source.path==self.owner.path or is_test_path(unit.source.path) or unit.test
                or unit.id in self.analysis.failure_wrappers
                or bool(failure_guard_constraints(self.index,unit,self.analysis.failure_wrappers)))

    def add_unit(self,unit):
        key=_key(unit)
        if key in self.units:
            return self.units[key]
        if len(self.vertices)>=self.max_units:
            self.unknown('validator_unit_budget',source=_source(unit.source,unit.node));return None
        identifier='V'+str(len(self.vertices));self.units[key]=identifier
        # Lambda/arrow vertices are source identities; same-line names cannot
        # overwrite one another in the inherited Unit adapter's ID namespace.
        if unit.node.type in NESTED and unit.node.type not in {'function_definition','function_declaration','method_definition','method_declaration'}:
            unit.name='<callback@'+str(unit.node.start_byte)+'>'
        unit.params=[row['name'] for row in _parameters(unit) if row['name']]
        self.index.units[unit.id]=unit
        definition=unit.node.parent if unit.node.parent is not None and unit.node.parent.type=='decorated_definition' else unit.node
        self.vertices[identifier]=dict(id=identifier,unit_id=unit.id,source=_source(unit.source,definition),
            parameters=_parameters(unit),check_site_ids=[],outgoing_edge_ids=[])
        self.queue.append((identifier,unit));return identifier

    def add_site(self,vertex,unit,node,form,expression,guards,**facts):
        position=_span(unit.source,node);identity=(position['path'],position['start_byte'],position['end_byte'],form,expression)
        if identity in self.site_keys:
            return self.site_keys[identity]
        identifier='C'+str(len(self.sites));self.site_keys[identity]=identifier
        row=dict(id=identifier,vertex=vertex,canonical_span=_canonical(position,self.changes),
                 source=_source(unit.source,node),passing_predicate=dict(form=form,expression=expression),
                 guards=guards,**facts)
        self.sites.append(row);self.vertices[vertex]['check_site_ids'].append(identifier);return identifier

    def sites_for(self,vertex,unit):
        analysis=self.analysis
        starts=(len(analysis.assertion_records),len(analysis.guard_constraints))
        context=_Context(unit);analysis.visit(context)
        for row in analysis.assertion_records[starts[0]:]:
            node=next(node for node in walk(unit.body) if _same_position(_span(unit.source,node),row['span']))
            if node.type=='assert_statement':
                form,expression='assert_expression',unit.source.text(node.named_children[0])
            elif node.type=='if_statement':
                form,expression='negated_failure_guard',unit.source.text(child(node,'condition'))
            else:
                form,expression='primitive_assertion_call',unit.source.text(node)
            self.add_site(vertex,unit,node,form,expression,row['guard_contexts'],predicate=row['predicate'],
                operands=dict(actual=row.get('actual_span'),expected=row.get('expected_span')))
        for row in analysis.guard_constraints[starts[1]:]:
            node=next(node for node in walk(unit.body) if _same_position(_span(unit.source,node),row['statement_span']))
            guards=[guard for guard in row['guard_contexts'] if guard.get('span')!=row['statement_span']]
            self.add_site(vertex,unit,node,'negated_failure_guard',row['guard_text'],guards,
                          predicate=row.get('passing_relation'))
        for statement,observed,expected in _exception_observations(unit,list(_owned(unit.body))):
            body=child(statement,'body');header=[node for node in walk(statement) if node.type in CALLS and node.end_byte<=body.start_byte]
            if any(analysis.module_binding_conflict(unit.source,unit.source.text(call_parts(call)[0]).split('.')[0]) for call in header):
                self.unknown('exception_adapter_binding_unproved',source=_source(unit.source,statement));continue
            self.add_site(vertex,unit,statement,'expected_exception',unit.source.text(expected),
                _guard_contexts(unit.source,statement,unit.body),observed=_source(unit.source,observed))
        for call in _owned(unit.body):
            if call.type not in CALLS:
                continue
            sink=direct_testing_failure(unit,call)
            if sink is None and unit.source.language=='python':
                fn,_=call_parts(call);name=unit.source.text(fn);parts=name.split('.')
                imported=unit.source.imports.get(parts[0])
                if ((imported==('pytest',None) and parts[1:]==['fail']) or imported==('pytest','fail') and len(parts)==1):
                    if parts[0] not in unit.params and not _locally_rebound(unit,parts[0]) and not analysis.module_binding_conflict(unit.source,parts[0]):
                        sink=dict(kind='pytest_failure',import_identity=imported)
            if sink is not None and not any(site['vertex']==vertex and site['passing_predicate']['form']=='negated_failure_guard'
                                            and _inside(_span(unit.source,call),site['source']['span']) for site in self.sites):
                self.add_site(vertex,unit,call,'uncaught_test_failure','false',_guard_contexts(unit.source,call,unit.body),
                              failure_kind=sink['kind'])

    def callable_value(self,context,node):
        resolved=self.analysis.resolve_ref(_Ref(node,context));source=resolved.context.unit.source
        if resolved.node.type in NESTED:
            body=child(resolved.node,'body')
            return Unit(source,resolved.node,body,'<callback>') if body is not None else None
        if resolved.node.type not in {'identifier','attribute','member_expression','selector_expression'}:
            return None
        name=source.text(resolved.node)
        if self.analysis.module_binding_conflict(source,name.split('.')[0]):
            return None
        targets=[uid for uid,reason in self.index.resolve(resolved.context.unit,name) if reason in TRUSTED]
        return self.index.units[targets[0]] if len(targets)==1 else None

    def call(self,vertex,unit,node):
        fn,args=call_parts(node);context=_Context(unit);position=_span(unit.source,node)
        resolved=self.analysis.callee(_Ref(node,context))
        target=resolved.unit if resolved is not None else None
        if target is None and fn is not None and fn.type=='identifier' and unit.source.text(fn) not in unit.params:
            name=unit.source.text(fn)
            if not _locally_rebound(unit,name) and not self.analysis.module_binding_conflict(unit.source,name):
                choices=[uid for uid,reason in self.index.resolve(unit,name) if reason in TRUSTED]
                if len(choices)==1:
                    target=self.index.units[choices[0]]
        if target is not None and self.validator(target):
            callee=self.add_unit(target)
            if callee is not None:
                identity=(vertex,position['start_byte'],position['end_byte'],callee)
                if identity not in self.edge_keys:
                    if len(self.edges)>=self.max_edges:
                        self.unknown('validator_edge_budget',source=_source(unit.source,node));return
                    self.edge_keys.add(identity);binding=bind_fixed_prefix(target,args,unit.source)
                    transforms=[]
                    for row in binding['bindings']:
                        source=unit.source if row['origin']=='caller' else target.source
                        transforms.append(dict(formal=row['parameter'],parameter_index=row['parameter_index'],
                            value=_source(source,row['value_node']),origin=row['origin']))
                    edge=dict(id='E'+str(len(self.edges)),caller=vertex,callee=callee,source=_source(unit.source,node),
                        guards=_guard_contexts(unit.source,node,unit.body),binding_status=binding['status'],
                        transforms=transforms,variadic_tail=binding['variadic_tail'])
                    self.edges.append(edge);self.vertices[vertex]['outgoing_edge_ids'].append(edge['id'])
                    if binding['status']=='unknown':
                        self.unknown('validator_binding_unproved',edge_id=edge['id'],reason=binding['reason'])
                    if target.decorators:
                        self.unknown('decorated_validator_dispatch_unproved',edge_id=edge['id'],
                                     decorators=target.decorators)
        elif target is not None:
            self.opaque.append(dict(caller=vertex,source=_source(unit.source,node),kind='resolved_production_callee',
                declaration_header=_source(target.source,target.node)|{'code':target.source.data[target.node.start_byte:target.body.start_byte].decode(),
                    'span':dict(_span(target.source,target.node),end_byte=target.body.start_byte)}))
        else:
            contained=any(site['vertex']==vertex and _inside(position,site['source']['span']) for site in self.sites)
            value_use=node.parent is not None and node.parent.type!='expression_statement'
            name=unit.source.text(fn);root=name.split('.')[0]
            language_builtin=((unit.source.language=='python' and hasattr(builtins,name)
                               or unit.source.language=='go' and name in GO_PREDECLARED_CALLABLES)
                and fn is not None and fn.type=='identifier' and self.analysis.builtin_unshadowed(context,name))
            testing_receiver=_testing_parameter(unit,root) if unit.source.language=='go' else None
            formal_dispatch=fn is not None and fn.type=='identifier' and name in unit.params
            if formal_dispatch or (not contained and not value_use and not language_builtin and testing_receiver is None):
                self.unknown('validator_dispatch_unproved',caller=vertex,source=_source(unit.source,node),
                             callee_expression=name)
            self.opaque.append(dict(caller=vertex,source=_source(unit.source,node),kind='unresolved_value_or_external_operation',
                                    semantic_support='unconfirmed'))
        # Preserve known function-valued validation arguments even when their
        # scheduler or incoming formal dispatch cannot be resolved statically.
        for argument in args:
            value=child(argument,'value') if argument.type=='keyword_argument' else argument
            callback=self.callable_value(context,value)
            if callback is not None and self.validator(callback):
                identifier=self.add_unit(callback)
                if identifier is not None:
                    row=dict(kind='function_value_argument',vertex=identifier,caller=vertex,
                        call_source=_source(unit.source,node),argument_source=_source(unit.source,argument),
                        invocation_and_bindings='unproved')
                    if row not in self.entries:
                        self.entries.append(row)
                    self.unknown('callback_invocation_binding_unproved',vertex=identifier,caller=vertex,
                                 source=_source(unit.source,node))

    def fixtures(self,unit,vertex,ancestry=()):
        if unit.source.language!='python':
            return
        if _key(unit) in ancestry:
            self.unknown('fixture_dependency_cycle',vertex=vertex);return
        for row in _parameters(unit):
            if row['name'] in unit.parameter_values:
                decorators=unit.node.parent.named_children if unit.node.parent is not None and unit.node.parent.type=='decorated_definition' else []
                proven=False
                for decorator in decorators:
                    if decorator.type!='decorator' or decorator.named_children[0].type not in CALLS:
                        continue
                    fn=call_parts(decorator.named_children[0])[0]
                    parts=unit.source.text(fn).split('.');binding=unit.source.imports.get(parts[0])
                    proven|=((binding==('pytest',None) and parts[1:]==['mark','parametrize'])
                             or binding==('pytest','mark') and parts[1:]==['parametrize']) and not self.analysis.module_binding_conflict(unit.source,parts[0])
                if not proven:
                    self.unknown('parameter_adapter_identity_unproved',vertex=vertex,parameter=row['name'])
                self.entries.append(dict(kind='source_parameter_rows',vertex=vertex,parameter=row['name'],
                                         values=unit.parameter_values[row['name']],adapter_identity_proved=proven))
                continue
            choices=self.index.local_functions(unit,row['name'],fixture=True)
            if len(choices)!=1:
                self.unknown('fixture_source_or_binding_unproved',vertex=vertex,parameter=row['name']);continue
            fixture=choices[0]
            # The inherited search is only a candidate inventory: a decorator
            # substring alone is not sufficient proof of pytest identity.
            decorators=fixture.node.parent.named_children if fixture.node.parent is not None and fixture.node.parent.type=='decorated_definition' else []
            proven=False
            for decorator in decorators:
                if decorator.type!='decorator':
                    continue
                expression=decorator.named_children[0];fn=call_parts(expression)[0] if expression.type in CALLS else expression
                parts=fixture.source.text(fn).split('.');binding=fixture.source.imports.get(parts[0])
                proven|=((binding==('pytest',None) and parts[1:]==['fixture']) or binding==('pytest','fixture') and len(parts)==1) and not self.analysis.module_binding_conflict(fixture.source,parts[0])
            if not proven:
                self.unknown('fixture_adapter_identity_unproved',source=_source(fixture.source,fixture.node));continue
            target=self.add_unit(fixture)
            if target is not None:
                self.entries.append(dict(kind='source_pytest_fixture',vertex=target,root_vertex=vertex,
                    bound_parameter=row['name'],dependency_parameters=[parameter['name'] for parameter in _parameters(fixture)]))
                self.fixtures(fixture,target,ancestry+(_key(unit),))

    def run(self,root):
        root_id=self.add_unit(root)
        self.entries.append(dict(kind='fixed_root_test',vertex=root_id,
            parameters=_parameters(root),external_state='symbolic; constrained only by supplied task/test evidence'))
        self.fixtures(root,root_id)
        while self.queue:
            vertex,unit=self.queue.pop(0)
            if vertex in self.seen:
                continue
            self.seen.add(vertex)
            if unit.source.root.has_error:
                self.unknown('validator_source_parse_error',vertex=vertex);continue
            self.sites_for(vertex,unit)
            for node in _owned(unit.body):
                if node.type in CALLS:
                    self.call(vertex,unit,node)
        groups=_scc(self.vertices,self.edges);components=[]
        for index,members in enumerate(groups):
            inside=[edge['id'] for edge in self.edges if edge['caller'] in members and edge['callee'] in members]
            outgoing=[edge['id'] for edge in self.edges if edge['caller'] in members and edge['callee'] not in members]
            incoming=[edge['id'] for edge in self.edges if edge['caller'] not in members and edge['callee'] in members]
            recursive=len(members)>1 or any(edge['caller']==edge['callee'] and edge['caller'] in members for edge in self.edges)
            components.append(dict(id='S'+str(index),members=members,recursive=recursive,internal_edges=inside,
                outgoing_edges=outgoing,incoming_edges=incoming,
                check_sites=[site['id'] for site in self.sites if site['vertex'] in members]))
        return dict(root_vertex=root_id,vertices=list(self.vertices.values()),check_sites=self.sites,
            transitions=self.edges,sccs=components,entries=self.entries,opaque_boundaries=self.opaque,
            unknowns=self.unknowns,coverage=dict(source_complete=not self.unknowns,
                predicate_truth_proved=False,termination_proved=False,production_bodies_included=False,
                max_validator_units=self.max_units,max_validator_edges=self.max_edges))


def analyze(corpus,frontend,candidate,*,max_units=256,max_edges=2048):
    """Return a finite guarded validator graph, never semantic admission."""
    result=dict(version=VERSION,status='unknown',alarm_eligible=False,semantic_validity='unconfirmed',
                closure_semantics=CLOSURE_SEMANTICS)
    try:
        candidate=program_candidate(candidate)
        sources,owner,changes,_,unknowns=_modified_sources(corpus,candidate)
        graph=_Graph(sources,owner,changes,max_units=max_units,max_edges=max_edges)
        selected=corpus['tests'][candidate['base_test_id']];definition=selected.get('definition_span',selected['span'])
        roots=[unit for unit in graph.index.units.values() if unit.source.path==owner.path and unit.test
               and unit.node.start_byte==definition['start_byte']]
        if len(roots)!=1:
            raise ValueError('modified root test not recovered')
        for unknown in unknowns:
            graph.unknown('modified_import_binding_unproved',**unknown)
        result.update(graph.run(roots[0]))
        result.update(status='complete' if result['coverage']['source_complete'] else 'partial',
            candidate_id=candidate['id'],changes=changes,
            source_sha256={source.path:hashlib.sha256(source.data).hexdigest() for source in sources},
            imported_source_rebind_unknowns=unknowns)
    except (KeyError,ValueError,TypeError,AttributeError,RecursionError,StopIteration) as error:
        result.update(status='unknown',coverage=dict(source_complete=False),
                      unknowns=[dict(code='source_closure_unavailable',detail=str(error))])
    finally:
        for method in (Index.module_paths,Index.reach,Index.field_factors):
            method.cache_clear()
    return result
