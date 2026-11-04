"""Rooted behavior partitions with concrete occurrence domains.

These partitions share a combination query. They do not certify contextual
equivalence of arbitrary programs; concrete bindings stay in the partition.
"""
import re
from collections import defaultdict
from itertools import combinations
from .alignment_templates import NUMBERS
from .evidence import FUNCTION_NODES, STRINGS
from .relational_alignment import digest, ports
from .regions import OBJECTS,SEQUENCES


def observed_fields(patch):
    """Conservative field vocabulary from public changed-code text."""
    fields=set(re.findall(r'\.([A-Za-z_$][\w$]*)',patch))
    fields.update(m[1] for m in re.findall(r'\[([\'\"])([A-Za-z_$][\w$]*)\1\]',patch))
    return fields


def count_predicates(vectors,scalars):
    """Finite relational abstraction: counts versus scalar/collection bounds.

    Input names are role addresses supplied by the parser, not learned labels.
    All comparisons are generated; no field is selected using test outcomes.
    """
    result=[]
    bounds={('constant','zero'):0,('constant','one'):1}
    bounds.update({('scalar',*name):value for name,value in scalars.items()})
    bounds.update({('size',*name):len(values) for name,values in vectors.items()})
    for name,values in sorted(vectors.items()):
        for threshold,number in sorted(scalars.items()):
            counts=[sum(x<number for x in values),sum(x==number for x in values),sum(x>number for x in values)]
            for comparison,count in zip(['less','equal','greater'],counts):
                for bound,value in sorted(bounds.items()):
                    result.append((name,threshold,comparison,bound,
                                   'less' if count<value else 'equal' if count==value else 'greater'))
    return result


def predicate_basis(rows):
    """Keep a deterministic basis inducing the same partition on this pool."""
    columns=set().union(*(row.keys() for row in rows))
    blocks=[list(range(len(rows)))];basis=[]
    for column in sorted(columns,key=lambda c:(len(repr(c)),repr(c))):
        refined=[]
        for block in blocks:
            parts={}
            for identity in block:
                value=rows[identity].get(column,'not_evaluable')
                parts.setdefault(value,[]).append(identity)
            refined.extend(parts.values())
        if len(refined)>len(blocks):basis.append(column);blocks=refined
    return basis,blocks


class BehaviorClusterIndex:
    def __init__(self, index, field_names=()):
        self.index = index
        self.field_names=set(field_names)
        self.cache = {}
        self.values = {}
        self.paths = {}
        self.fact_cache = {}
        self.shape_cache = {}
        self.literal_cache = {}
        self.equality_cache = {}

    def literal(self,source,term):
        key=source,term.span
        if key in self.literal_cache:return self.literal_cache[key]
        children={}
        if term.kind in {'object','dictionary'}:
            fields=[c for _,c in term.children if c.kind in {'pair','property_assignment','keyed_element'}]
            for field in fields:
                keys=[c for role,c in field.children if role.startswith(('key:','field:'))]
                values=[c for role,c in field.children if role.startswith('value:')]
                if len(keys)==len(values)==1:
                    key_term=keys[0]
                    fixed=key_term.kind in {'property_identifier','identifier','field_identifier'}
                    literal=key_term.kind in NUMBERS|STRINGS and self.literal(source,key_term)[0] is not None
                    if fixed or literal:children[key_term.value.strip('\'"`')]=values[0]
            # Duplicate/spread/computed fields are not closed literal values.
            actual=[c for role,c in term.children if role.startswith('named:')]
            parsed=[self.literal(source,c)[0] for c in children.values()]
            value=('object',tuple(sorted(zip(children,parsed)))) if len(actual)==len(fields)==len(children) and all(x is not None for x in parsed) else None
        elif term.kind in SEQUENCES:
            elements=[c for role,c in term.children if role.startswith('named:')]
            children={str(i):c for i,c in enumerate(elements)}
            parsed=[self.literal(source,c)[0] for c in elements]
            value=(term.kind,tuple(parsed)) if all(x is not None for x in parsed) else None
        elif term.kind in NUMBERS|STRINGS|{'true','false','null','nil','none','boolean_literal'}:
            interpolation='${' in term.value or re.match(r'(?i)^(?:[rub]*f|f[rub]*)[\'\"]',term.value)
            value=None if interpolation else (term.kind,term.value)
        else:value=None
        result=value,children
        self.literal_cache[key]=result
        return result

    def literal_relations(self,key):
        if key in self.equality_cache:return self.equality_cache[key]
        index=self.index;source=key[0];resolved=[]
        for p in ports(index.operations[key]):
            span=p['range']
            if len(p['definition_versions'])==1:
                d=index.definitions[source,p['definition_versions'][0]]
                if d['value_range'] is not None:span=d['value_range']
            resolved.append((p['role'],index.terms[source].term(span)))
        rows=[]
        for (ar,a),(br,b) in combinations(resolved,2):
            pending=[((),a,b)]
            while pending:
                path,aa,bb=pending.pop();av,ac=self.literal(source,aa);bv,bc=self.literal(source,bb)
                if av is not None and bv is not None:
                    equal=av==bv
                    rows.append((ar,br,path,aa.kind,bb.kind,'same_closed_literal' if equal else 'literal_difference'))
                    if equal:continue
                pending.extend(((*path,name),ac[name],bc[name]) for name in sorted(ac.keys()&bc.keys()))
        result=tuple(sorted(rows,key=repr));self.equality_cache[key]=result
        return result

    def value_shapes(self,key):
        if key in self.shape_cache:return self.shape_cache[key]
        index=self.index;source=key[0];result=[]
        for p in ports(index.operations[key]):
            spans=[p['range']]
            if len(p['definition_versions'])==1:
                d=index.definitions[source,p['definition_versions'][0]]
                if d['value_range'] is not None:spans.append(d['value_range'])
            descriptions=[]
            for span in spans:
                term=index.terms[source].term(span)
                pending=[(term,())];containers=set();opaque=set();flags=set();owners=set()
                while pending:
                    node,path=pending.pop()
                    if node.kind in OBJECTS|SEQUENCES:
                        path=(*path,node.kind);containers.add(path)
                    elif node.kind in FUNCTION_NODES|{'return_statement','return_expression'}:
                        path=(*path,node.kind)
                    if node.kind in {'pair','field_initializer','property_assignment','keyed_element'}:
                        keys=[child.value.strip('\'"`') for role,child in node.children if role.startswith(('key:','field:'))]
                        for name in keys:
                            if name in self.field_names:owners.add((path,name))
                    if node.kind in STRINGS and any(c in node.value for c in ['\\n','\n','{','}', ';','\\x1b','(module']):
                        opaque.add(node.value)
                    if node.kind in {'true','false','boolean','boolean_literal'}:flags.add((node.kind,node.value))
                    pending.extend((child,path) for _,child in node.children)
                # Cardinality at the actual argument boundary matters for
                # registrations and collections. Nested payload fields retain
                # their concrete domain without making new provider classes.
                arity=sum(child.kind not in {'{','}','[',']',','} for _,child in term.children) if term.kind in OBJECTS|SEQUENCES else None
                descriptions.append((term.kind,arity,sorted(containers),sorted(opaque),sorted(flags),sorted(owners)))
            result.append((p['role'],descriptions))
        self.shape_cache[key]=result
        return result


    def input_paths(self, key, depth):
        cache_key=key,depth
        if cache_key in self.paths:
            return self.paths[cache_key]
        edges=self.index.feature(key)['inputs']
        result=set()
        for role,other in edges:
            if role=='callee':continue
            step=(role,self.index.descriptor(other))
            result.add((step,))
            if depth>1:
                result.update((step,*path) for path in self.input_paths(other,depth-1))
        self.paths[cache_key]=tuple(sorted(result,key=repr))
        return self.paths[cache_key]

    def skeleton(self, source, span):
        """Abstract payloads, retaining selectors, booleans and program text."""
        cache_key = source, tuple(span)
        if cache_key in self.values:
            return self.values[cache_key]
        term = self.index.terms[source].term(span)
        pending = [(term, False)]; result = []; names = {}
        while pending:
            item, selector = pending.pop()
            if isinstance(item, str):
                result.append(item)
                continue
            value = item.value
            if item.kind == 'reference':
                value = names.setdefault(value,len(names))
            elif item.kind in NUMBERS and not selector:
                value = '<number>'
            elif item.kind in STRINGS and not selector:
                # Multi-line/source-like inputs remain opaque programs. Their
                # exact text remains a distinguishing feature until parsed.
                program = any(c in value for c in ['\\n','\n','{','}', ';','\\x1b','(module'])
                value = value if program else '<string>'
            result.append((item.kind,value,len(item.children)))
            for role,child in reversed(item.children):
                fixed = selector or role.startswith(('index:', 'subscript:', 'slice:', 'key:', 'field:',
                                                      'attribute:', 'property:', 'function:'))
                pending.extend([((child,fixed)),((role,False))])
        result = digest(result)
        self.values[cache_key] = result
        return result

    def signature(self, record, mode):
        cache_key = record['key'],mode
        if cache_key in self.cache:
            return self.cache[cache_key]
        index = self.index;source = record['key'][0]
        op = index.operations[record['key']]
        pp = ports(op)
        base = [record['interface'],record['field'],
                tuple((p['role'],p['ast_type']) for p in pp)]
        if mode != 'ports':
            names={};topology=[]
            for p in pp:
                cells=[p['binding']]+[r['binding'] for r in p['reads']]
                topology.append((p['role'],[names.setdefault(tuple(c),len(names)) if c is not None else None for c in cells]))
            guards=[(g['polarity'],self.skeleton(source,g['range'])) for g in op['guards']]
            frames=[(f['kind'],f.get('branch'),f.get('mode')) for f in op['frames']]
            base.extend([record['identity_relations'],record['value_relations'],topology,guards,frames])
            base.append(self.value_shapes(record['key']))
            base.append(self.literal_relations(record['key']))
        if mode in {'flow','boundary'}:
            base.append(self.input_paths(record['key'],2))
        if mode == 'boundary':
            # Syntax at the actual operand boundary distinguishes different
            # field/state constructions without hashing every reaching body.
            expressions=[]
            for p in pp:
                spans=[p['range']]
                if len(p['definition_versions']) == 1:
                    d=index.definitions[source,p['definition_versions'][0]]
                    if d['value_range'] is not None:
                        spans.append(d['value_range'])
                expressions.append((p['role'],tuple(self.skeleton(source,span) for span in spans)))
            base.append(expressions)
        result=digest(base)
        self.cache[cache_key]=result
        return result

    def facts(self, record):
        """Relational alternatives attached to a shared interface cluster.

        Each fact retains a supporting occurrence. Querying multiple facts
        intersects those support sets; unioning unrelated facts is not a joint
        historical witness.
        """
        if record['key'] in self.fact_cache:
            return self.fact_cache[record['key']]
        index=self.index;source=record['key'][0];op=index.operations[record['key']]
        rows=[]
        # Concrete expression contents belong to the member binding domain.
        # Planning queries ask for input properties, not every source spelling.
        for role,shape in self.value_shapes(record['key']):
            rows.append((('input',role),shape))
        for a,b,value in record['identity_relations']:
            rows.append((('identity',a,b),value))
        for a,b,value in record['value_relations']:
            rows.append((('numeric_relation',a,b),value))
        for a,b,path,ak,bk,value in self.literal_relations(record['key']):
            rows.append((('literal_relation',a,b,path,ak,bk),value))
        for direction in ['inputs','outputs']:
            for role,other in record[direction]:
                if role!='callee':rows.append(((direction,role,*index.descriptor(other)),True))
        for consumer,event,position,*certainty in record['consumer_state']:
            rows.append((('order',index.descriptor(consumer),index.descriptor(event)),(position,*certainty)))
        for guard in op['guards']:
            rows.append((('guard',self.skeleton(source,guard['range'])),guard['polarity']))
        result=frozenset((digest(address),digest(value)) for address,value in rows)
        self.fact_cache[record['key']]=result
        return result


class BehaviorTable:
    """Fact posting lists over original, correlated historical rows."""
    def __init__(self):
        self.origins=[]
        self.classes={}
        self.postings={}

    def add(self,cluster,origin,facts):
        identity=len(self.origins);self.origins.append(origin);bit=1<<identity
        self.classes[cluster]=self.classes.get(cluster,0)|bit
        for fact in facts:self.postings[fact]=self.postings.get(fact,0)|bit
        return identity

    def support(self,cluster,conditions):
        result=self.classes[cluster]
        for fact in conditions:result&=self.postings.get(fact,0)
        return result


def cluster_queries(index,records,assignments):
    """Activate provider classes connected to a D entry in the retained view.

    This registers a query domain, not a claim that every pair is compatible.
    Concrete port/condition bindings are selected from the member table.
    """
    members={};seeds={}
    for row in records:
        op=index.operations[row['key']]
        family=op['kind'],op['name']
        identity=assignments[row['view'],*row['key']]
        members.setdefault(family,set()).add(identity)
        if row['anchor'] or row['flow_anchor']:seeds.setdefault(family,set()).add(identity)
    return {(a,b) for family,left in seeds.items() for a in left for b in members[family]}


def candidate_materials(class_pair,memberships,view_links):
    """Read a candidate's attached documents with their supporting views.

    Inputs use integer class/view IDs. The class and operation domains stay
    unchanged; attachments are selected through actual member views.
    """
    support=defaultdict(set)
    for cluster in class_pair:
        for view,_,_ in memberships[cluster]:
            for link in view_links[view]:
                support[link['material']].add((view,link['relation'],link['via']))
    return {material:[{'view':view,'relation':relation,'via':via}
                      for view,relation,via in sorted(rows)]
            for material,rows in sorted(support.items())}


def read_candidate_materials(directory,class_pair,*,member_views=None,partition='ports'):
    """Read attached documents for an existing class pair or concrete binding."""
    from pathlib import Path
    from .slice_behavior import read_behavior_graph
    directory=Path(directory)
    pairs=read_behavior_graph(directory/'cluster_pairs.json.gz')['original'][partition]
    assert list(class_pair) in pairs, 'The requested class pair must be an existing candidate'
    memberships={int(c):rows for c,rows in read_behavior_graph(directory/'memberships.json.gz')[partition].items()}
    if member_views is not None:
        selected={cluster:{v for c,v in zip(class_pair,member_views) if c==cluster} for cluster in class_pair}
        for cluster,view in zip(class_pair,member_views):
            assert any(row[0]==view for row in memberships[cluster]), 'The selected view must belong to this class'
        memberships={cluster:[r for r in memberships[cluster] if r[0] in selected[cluster]] for cluster in selected}
    bundle=read_behavior_graph(directory/'candidate_materials.json.gz')
    # Execution observations are optional for archived, non-replayed sources.
    # Expand shared groups only for the selected candidate's member views.
    executions=bundle.get('view_executions',{})
    selected_views={view for cluster in class_pair for view,_,_ in memberships[cluster]}
    view_links={view:list(bundle['views'][str(view)]) for view in selected_views}
    for view in selected_views:
        if str(view) in executions:
            view_links[view].extend(bundle['executions'][executions[str(view)]])
    support=candidate_materials(class_pair,memberships,view_links)
    documents={d['id']:d for d in bundle['documents']}
    return {'class_pair':list(class_pair),'partition':partition,'member_views':member_views,
            'candidate_materials':[documents[m] for m in support],'material_support':support}
