"""Role-anchored syntax alignment; differences are proposed edits, not API laws.

All coordinates refer to the complete original source. The local term cache is
shared across queries; emitted edits contain coordinates rather than copied ASTs.
"""
from collections import Counter,defaultdict
from dataclasses import dataclass
import re
from bisect import bisect_left

from .evidence import CALLS, IDENTS, MEMBERS, STRINGS


@dataclass(frozen=True)
class Term:
    kind: str
    value: str
    span: tuple
    children: tuple = ()


def _member_field(node):
    return next((node.child_by_field_name(k) for k in ('attribute', 'field', 'property')
                 if node.child_by_field_name(k) is not None), None)


class TermIndex:
    def __init__(self, graph):
        self.graph = graph
        self.cache = {}
        self.nodes = {}

    def term(self, span):
        key = tuple(span)
        if key in self.cache:
            return self.cache[key]
        node = self.graph.root.descendant_for_byte_range(key[0], key[1])
        if (node.start_byte, node.end_byte) != key:
            # A port can name a token inside a composite argument. Keeping the
            # supplied source interval avoids inventing an enclosing operation.
            result = Term('source_interval', self.graph.raw[key[0]:key[1]].decode(), key)
            self.cache[key] = result
            return result
        pending = [(node, False)]
        built = {}
        while pending:
            current, ready = pending.pop()
            current_key = current.start_byte, current.end_byte
            if current.id in self.nodes:
                built[current.id] = self.nodes[current.id]
                continue
            raw = self.graph.text(current)
            if current.type in STRINGS or not current.children:
                parent = current.parent
                fixed = (parent is not None and
                         (parent.type in MEMBERS and _member_field(parent) == current or
                          parent.type in CALLS and parent.child_by_field_name('function') == current or
                          parent.type in {'keyword_argument','pair','property_assignment'} and
                          (parent.child_by_field_name('name') == current or
                           parent.child_by_field_name('key') == current)))
                kind = 'reference' if current.type in IDENTS and not fixed else current.type
                value = raw
                if kind == 'reference':
                    scope_node = current.parent
                    while scope_node is not None and scope_node.id not in self.graph.scope_nodes:
                        scope_node = scope_node.parent
                    scope = self.graph.scope_nodes[scope_node.id] if scope_node is not None else 0
                    binding = self.graph._binding(scope, raw)
                    value = str(binding[0]) + ':' + binding[1]
                result = Term(kind, value, current_key)
            elif not ready:
                pending.append((current, True))
                pending.extend((child, False) for child in reversed(current.children)
                               if child.type not in {'comment','line_comment','block_comment'})
                continue
            else:
                children=[];counts=defaultdict(int)
                for i, child in enumerate(current.children):
                    if child.type in {'comment','line_comment','block_comment'}:
                        continue
                    field = current.field_name_for_child(i) or ('named' if child.is_named else child.type)
                    role = field + ':' + str(counts[field]);counts[field] += 1
                    children.append((role, built[child.id]))
                result = Term(current.type, '', current_key, tuple(children))
            built[current.id] = result
            self.nodes[current.id] = result
        self.cache[key] = built[node.id]
        return self.cache[key]


def term_key(term, *, rename=False):
    """Canonical syntax only. This does not erase identity or environment facts."""
    names={};out=[];pending=[term]
    while pending:
        item=pending.pop()
        if isinstance(item,str):
            out.append(item);continue
        value=item.value
        if rename and item.kind=='reference':
            if value not in names:names[value]=str(len(names))
            value=names[value]
        out.append((item.kind,value,len(item.children)))
        for role,child in reversed(item.children):
            pending.extend((child,role))
    return tuple(out)


def anti_unify(left, right):
    """Preserve ordered AST roles and emit minimal structural differences.

    A repeated reference must have a consistent bidirectional alpha mapping.
    A hole is not an independent semantic factor; callers may group holes.
    """
    pending=[((),left,right)];holes=[];mapping={};inverse={};matched=0
    while pending:
        path,a,b=pending.pop()
        if a.kind==b.kind=='reference':
            conflict=(a.value in mapping and mapping[a.value]!=b.value or
                      b.value in inverse and inverse[b.value]!=a.value)
            if conflict:
                holes.append({'role':list(path),'left':list(a.span),'right':list(b.span),
                              'kind':'binding_topology','left_kind':a.kind,'right_kind':b.kind})
            else:
                mapping[a.value]=b.value;inverse[b.value]=a.value;matched+=1
            continue
        if a.kind!=b.kind or a.value!=b.value:
            holes.append({'role':list(path),'left':list(a.span),'right':list(b.span),
                          'kind':'replace','left_kind':a.kind,'right_kind':b.kind})
            continue
        matched+=1
        ac=dict(a.children);bc=dict(b.children)
        for role in reversed(sorted(ac.keys()|bc.keys())):
            if role in ac and role in bc:
                pending.append(((*path,role),ac[role],bc[role]))
            else:
                holes.append({'role':list((*path,role)),
                              'left':list(ac[role].span) if role in ac else None,
                              'right':list(bc[role].span) if role in bc else None,
                              'kind':'insert' if role in bc else 'delete',
                              'left_kind':ac[role].kind if role in ac else None,
                              'right_kind':bc[role].kind if role in bc else None})
    return {'holes':sorted(holes,key=lambda h:h['role']),
            'references':sorted(mapping.items()),'matched_nodes':matched}


def _context_names(graph, operation):
    """Visible receiver construction names; ranking evidence, never must-type."""
    receiver=operation['receiver']
    if receiver is None or receiver['binding'] is None:
        return ()
    key=tuple(receiver['binding']);node=graph.nodes[operation['statement']]
    definitions=[i for i in node['data'] if key in graph.nodes[i]['defs']]
    if not definitions:
        definitions=[i for i in graph.definitions[key]
                     if graph.nodes[i]['start']<=operation['expression_range'][0]]
    names=set()
    for identity in definitions:
        names.update(name for name,_,_ in graph.nodes[identity]['calls'] if name)
    return tuple(sorted(names))


def _frame_key(operation):
    return (tuple((frame['kind'],frame['branch'] if frame['kind']=='try' else '')
                  for frame in operation['frames']),
            tuple(guard['polarity'] for guard in operation['guards']))


class AlignmentIndex:
    """Index expression occurrences, retaining weak matches as an explicit tier."""
    def __init__(self, sources):
        # sources: source ID -> (SourceGraph, BehaviorIndex)
        self.sources=sources
        self.terms={key:TermIndex(graph) for key,(graph,_) in sources.items()}
        self.by_name=defaultdict(list)
        self.operations={}
        self.receiver_context={}
        self.alignment_cache={}
        self.definitions={key:{d['id']:d for d in behavior.definitions}
                          for key,(_,behavior) in sources.items()}
        for source,(graph,behavior) in sources.items():
            for operation in behavior.operations:
                key=(source,operation['id'])
                self.operations[key]=operation
                if operation['name']:
                    self.by_name[operation['kind'],operation['name']].append(key)
                self.receiver_context[key]=_context_names(graph,operation)
        for keys in self.by_name.values():keys.sort()

    def boundary_ports(self,key):
        """Follow nested operands to their receivers, preserving expression roles."""
        result=[];pending=[('',self.operations[key])];seen=set()
        while pending:
            prefix,op=pending.pop()
            if op['id'] in seen:continue
            seen.add(op['id'])
            ports=op['arguments']+([op['receiver']] if op['receiver'] else [])
            for port in ports:
                role=prefix+port['role'];result.append((role,port))
                for producer in port.get('producer_operations',[]):
                    pending.append((role+'/output/',self.operations[key[0],producer]))
        return dict(result)

    def construction_differences(self,left_key,right_key):
        left=self.boundary_ports(left_key);right=self.boundary_ports(right_key);differences=[]
        for role in sorted(left.keys()&right.keys()):
            a=left[role]['definition_versions'];b=right[role]['definition_versions']
            if len(a)!=1 or len(b)!=1:continue
            ad=self.definitions[left_key[0]][a[0]];bd=self.definitions[right_key[0]][b[0]]
            if ad['value_range'] is None or bd['value_range'] is None:continue
            result=anti_unify(self.terms[left_key[0]].term(ad['value_range']),
                              self.terms[right_key[0]].term(bd['value_range']))
            if result['holes']:
                differences.append({'role':role,'left_definition':a[0],'right_definition':b[0],
                                    'left_range':ad['value_range'],'right_range':bd['value_range'],
                                    'difference':result})
        return differences

    def align(self,left_key,right_key):
        key=left_key,right_key
        if key in self.alignment_cache:return self.alignment_cache[key]
        a=self.operations[left_key];b=self.operations[right_key]
        slots=[]
        if a['receiver'] is not None and b['receiver'] is not None:
            slots.append(('receiver',a['receiver'],b['receiver']))
        ap={p['role']:p for p in a['arguments']};bp={p['role']:p for p in b['arguments']}
        for role in sorted(ap.keys()&bp.keys()):slots.append((role,ap[role],bp[role]))
        deltas=[];references=[];shared=0;binding_conflicts=[]
        forward={};backward={}
        for role,x,y in slots:
            result=anti_unify(self.terms[left_key[0]].term(x['range']),
                              self.terms[right_key[0]].term(y['range']))
            shared+=result['matched_nodes']
            for hole in result['holes']:deltas.append({'slot':role,**hole})
            for first,second in result['references']:
                if ((first in forward and forward[first]!=second) or
                    (second in backward and backward[second]!=first)):
                    binding_conflicts.append([first,second])
                else:forward[first]=second;backward[second]=first
                references.append([role,first,second])
        for role in sorted(ap.keys()^bp.keys()):
            deltas.append({'slot':role,'role':[],
                           'left':ap[role]['range'] if role in ap else None,
                           'right':bp[role]['range'] if role in bp else None,
                           'kind':'insert' if role in bp else 'delete',
                           'left_kind':ap[role]['ast_type'] if role in ap else None,
                           'right_kind':bp[role]['ast_type'] if role in bp else None})
        ac=self.receiver_context[left_key];bc=self.receiver_context[right_key]
        result={'left':list(left_key),'right':list(right_key),
                'same_operation_name':a['kind']==b['kind'] and a['name']==b['name'],
                'aligned_roles':[slot[0] for slot in slots],
                'deltas':deltas,'reference_mapping':references,'binding_conflicts':binding_conflicts,
                'matched_nodes':shared,'same_receiver_context':bool(ac and bc and set(ac)&set(bc)),
                'receiver_contexts':[list(ac),list(bc)],
                'same_control_frame':_frame_key(a)==_frame_key(b),
                'same_signature':set(ap)==set(bp),
                'construction_differences':self.construction_differences(left_key,right_key),
                'unknowns':sorted(set(a['unknowns']+b['unknowns'])),
                'interpretation':'structural_correspondence_not_semantic_equivalence'}
        self.alignment_cache[key]=result
        return result

    def query(self,left_key,*,mode='roles',sources=None):
        a=self.operations[left_key]
        candidates=[key for key in self.by_name[a['kind'],a['name']]
                    if key!=left_key and (sources is None or key[0] in sources)]
        if mode=='name':return [{'key':list(key),'score':0} for key in candidates]
        results=[]
        left_nested={self.operations[left_key[0],producer]['name']
                     for port in self.boundary_ports(left_key).values()
                     for producer in port.get('producer_operations',[])}
        for key in candidates:
            aligned=self.align(left_key,key)
            right_nested={self.operations[key[0],producer]['name']
                          for port in self.boundary_ports(key).values()
                          for producer in port.get('producer_operations',[])}
            # Context is a ranking signal. It cannot discard a replacement
            # constructor or a corresponding API with different semantics.
            score=(int(not aligned['binding_conflicts']),
                   len(left_nested&right_nested),
                   int(aligned['same_receiver_context']),
                   int(bool(aligned['deltas'] or aligned['construction_differences'])),
                   int(aligned['same_signature']),
                   len(aligned['aligned_roles']),
                   int(aligned['same_control_frame']),
                   aligned['matched_nodes'])
            results.append({'key':list(key),'score':list(score)})
        return sorted(results,key=lambda r:(tuple(-x for x in r['score']),tuple(r['key'])))


def region_term(value):
    """Adapt a shared region syntax tree to the local anti-unification terms."""
    built={};pending=[(value,False)]
    while pending:
        item,ready=pending.pop()
        if id(item) in built:continue
        if not ready and item['children']:
            pending.append((item,True))
            pending.extend((child,False) for _,child in reversed(item['children']))
        else:
            built[id(item)]=Term(item['kind'],item['value'],tuple(item['span']),
                                tuple((role,built[id(child)]) for role,child in item['children']))
    return built[id(value)]


class RegionAlignmentIndex:
    """Keep syntax, data-flow and observation correspondence as separate channels.

    Generic structure is retained as a weak tier. Neither a shared field name
    nor a local method symbol proves cross-file dispatch or an API law.
    """
    def __init__(self,sources):
        from .regions import RegionIndex
        from .relations import RelationIndex
        self.sources=sources
        self.regions={key:RegionIndex(graph) for key,(graph,_) in sources.items()}
        self.relations={key:RelationIndex(graph,behavior) for key,(graph,behavior) in sources.items()}
        self.calls=AlignmentIndex(sources)
        self.pool={};self.groups=defaultdict(list);self.by_call=defaultdict(list)
        self.op_starts={};self.source_operations={};self.profiles={}
        self.scope_calls=defaultdict(set)
        self.token_frequency=Counter()
        self.observers=defaultdict(set)
        self.pool_by_span=defaultdict(list)
        for source,(graph,behavior) in sources.items():
            ordered=sorted(behavior.operations,key=lambda op:op['expression_range'][0])
            self.source_operations[source]=ordered
            self.op_starts[source]=[op['expression_range'][0] for op in ordered]
            for op in ordered:
                if op['kind']=='call' and op['name']:
                    self.scope_calls[source,op['scope']].add(op['name'])
            regions=self.regions[source]
            for region in regions.regions:
                self.token_frequency.update(self._tokens(value for values in region['features'].values() for value in values))
            for region in regions.regions:
                if not region['candidate']:continue
                kind=region['kind']
                if kind not in {'call','member','field','object_literal','sequence_literal',
                                'composite_literal','statement','return','input_string'}:
                    continue
                key=source,region['id'];self.pool[key]=region;self.groups[kind].append(key)
                self.pool_by_span[source,tuple(region['range'])].append(key)
                for name in region['features']['calls']:self.by_call[name].append(key)
            by_definition=defaultdict(set)
            for edge in self.relations[source].edges:
                if edge['kind']=='definition_to_observation':by_definition[edge['from']].add(edge['to'])
                elif edge['kind']=='operation_observation_candidate':
                    self.observers[source,edge['from']].add(edge['to'])
            for op in ordered:
                for definition in op['result']['definitions']:
                    self.observers[source,op['id']].update(by_definition[definition])
        for group in self.groups.values():group.sort()
        for group in self.by_call.values():group.sort()

    @staticmethod
    def _tokens(values):
        return {token.lower() for value in values for token in
                re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+',value)
                if len(token)>1}

    def _operations_in(self,source,region):
        a,b=region['range'];ordered=self.source_operations[source]
        start=bisect_left(self.op_starts[source],a)
        result=[]
        for position in range(start,len(ordered)):
            op=ordered[position]
            if op['expression_range'][0]>=b:break
            if op['expression_range'][1]<=b and op['scope']==region['scope']:
                result.append(op)
        return result

    def profile(self,source,region):
        key=source,region['id']
        if key in self.profiles:return self.profiles[key]
        features=self.regions[source].features(region)
        result={k:set(v) for k,v in features.items()}
        for kind in ('related_operation_names','receiver_constructors','observation_fields'):
            result[kind]=set()
        result['unknowns']=set(region['unknowns'])
        result['observations']=set()
        result['result_names']=set()
        for op in self._operations_in(source,region):
            f=self.relations[source].operation_features[op['id']]
            for kind in ('related_operation_names','receiver_constructors','observation_fields'):
                result[kind].update(f[kind])
            result['unknowns'].update(f['unknowns'])
            for definition in op['result']['definitions']:
                result['result_names'].add(self.relations[source].definitions[definition]['binding'][1])
            if op['observation'] is not None:result['observations'].add(op['id'])
        result['scope_calls']=self.scope_calls[source,region['scope']]
        result['role_tokens']=self._tokens(result['members']|result['keys']|result['observation_fields']|result['result_names'])
        self.profiles[key]=result
        return result

    def select(self,source,start,end):
        return self.regions[source].select(start,end)

    def _query_profile(self,source,selection):
        result=defaultdict(set)
        for region in selection['selected']:
            for kind,values in self.profile(source,region).items():result[kind].update(values)
        return result

    def query(self,source,start,end):
        selection=self.select(source,start,end)
        if selection['status'] in {'opaque','fragment'}:
            return {'selection':selection,'channels':{},'unknowns':['input_region_has_no_behavior_parser']}
        q=self._query_profile(source,selection)
        selected={r['id'] for r in selection['selected']}
        names=q['calls'];kinds={r['kind'] for r in selection['selected']}
        candidates=defaultdict(set)
        for name in names:
            candidates['same_operation'].update(self.by_call[name])
        for kind in kinds:
            candidates['structural_role'].update(self.groups[kind])
        if 'field' in kinds:
            candidates['structural_role'].update(self.groups['object_literal'])
            candidates['structural_role'].update(self.groups['composite_literal'])
        # A returned region can be attached to calls of the containing method.
        # Cross-file receiver resolution remains an explicit open condition.
        for region in selection['selected']:
            if region['kind']=='return':
                graph=self.sources[source][0];scope=graph.scopes[region['scope']]
                candidates['producer_consumer'].update(self.by_call[scope['name']])
        for key,region in self.pool.items():
            profile=self.profile(key[0],region)
            related=bool((q['related_operation_names']|names)&profile['related_operation_names'])
            fields=bool((q['members']|q['observation_fields'])&(profile['members']|profile['observation_fields']))
            receiver=bool(q['receiver_constructors']&profile['receiver_constructors'])
            token_match=bool(q['role_tokens']&profile['role_tokens'])
            if profile['observations'] and (related or fields or receiver or token_match):
                candidates['observation_transfer'].add(key)
            # Shared lexical bindings in the same source/frame are a temporal
            # retrieval signal, not proof that file/state effects are known.
            if key[0]==source and any(region['scope']==r['scope'] for r in selection['selected']):
                if q['identifiers']&profile['identifiers']:
                    candidates['temporal_extension'].add(key)
        candidates['temporal_extension'].update(candidates['same_operation'])
        # Follow the actual returned-definition link from a temporal event to
        # its check. This retains a call+check region without joining by names.
        for key in list(candidates['temporal_extension']):
            for op in self._operations_in(key[0],self.pool[key]):
                for observer in self.observers[key[0],op['id']]:
                    observed=self.relations[key[0]].operations[observer]
                    candidates['temporal_extension'].update(
                        self.pool_by_span[key[0],tuple(observed['expression_range'])])
        channels={}
        for channel,keys in candidates.items():
            rows=[]
            for key in keys:
                if key[0]==source and key[1] in selected:continue
                region=self.pool[key];p=self.profile(key[0],region)
                overlap=len(names&p['calls'])
                shared_fields=len((q['members']|q['keys'])&(p['members']|p['keys']))
                shared_flow=len((q['related_operation_names']|names)&p['related_operation_names'])
                same_shape=int(region['kind'] in kinds)
                tokens=q['role_tokens']&p['role_tokens']
                token_weight=sum(1/self.token_frequency[t] for t in sorted(tokens))
                score=(overlap,token_weight,shared_flow,shared_fields,same_shape,
                       len(q['scope_calls']&p['scope_calls']),-len(p['calls']-names))
                if channel=='structural_role':
                    score=(shared_fields,same_shape,overlap,len(q['scope_calls']&p['scope_calls']),shared_flow)
                basis=[]
                if shared_flow:basis.append('shared_local_flow_operation_names')
                if shared_fields:basis.append('same_field_spelling')
                if tokens:basis.append('identifier_tokens')
                rows.append({'key':list(key),'range':region['range'],'kind':region['kind'],
                             'score':list(score),'basis':basis,'unknowns':sorted(p['unknowns'])})
            channels[channel]=sorted(rows,key=lambda r:(tuple(-x for x in r['score']),tuple(r['key'])))
        return {'selection':selection,'channels':channels,
                'unknowns':sorted(q['unknowns'])}

    def difference(self,left_source,left_selection,right_source,right_selection):
        def make(source,selection):
            parts=[region_term(self.regions[source].term(r)) for r in selection['selected']]
            if len(parts)==1:return parts[0]
            return Term('region_sequence','',tuple(selection['range']),
                        tuple(('statement:'+str(i),part) for i,part in enumerate(parts)))
        return anti_unify(make(left_source,left_selection),make(right_source,right_selection))
