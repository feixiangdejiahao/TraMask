from eviweave.behavior import BehaviorIndex
from eviweave.behavior_clusters import BehaviorClusterIndex,BehaviorTable,cluster_queries,count_predicates,predicate_basis,observed_fields
from eviweave.evidence import SourceGraph
from eviweave.port_admission import PortAdmissionIndex


def build(text,path='test.py',fields=()):
    graph=SourceGraph({'id':'s','path':path,'raw':text.encode()})
    assert not graph.issues
    behavior=BehaviorIndex(graph)
    index=PortAdmissionIndex({'s':(graph,behavior)},{'s':set(range(len(graph.nodes)))})
    records=index.view_features({'id':0,'source':'s','nodes':set(range(len(graph.nodes))),'anchors':set()})
    return index,BehaviorClusterIndex(index,fields),records


def test_extra_consumers_are_variants_of_the_provider_not_new_provider_classes():
    index,cluster,rows=build('a=make(1)\nconsume(a)\nb=make(2)\nother(b)\n')
    rr=[r for r in rows if index.operations[r['key']]['name']=='make']
    assert cluster.signature(rr[0],'relations')==cluster.signature(rr[1],'relations')
    assert cluster.facts(rr[0])!=cluster.facts(rr[1])


def test_object_depth_separates_scalar_from_nested_object_conditions():
    index,cluster,rows=build('send({"a":True})\nsend({"a":{"x":1}})\n')
    rr=[r for r in rows if index.operations[r['key']]['name']=='send']
    assert cluster.signature(rr[0],'relations')!=cluster.signature(rr[1],'relations')


def test_numeric_order_is_not_erased_by_clustering():
    index,cluster,rows=build('send(1,10)\nsend(2,20)\nsend(11,10)\n')
    rr=[r for r in rows if index.operations[r['key']]['name']=='send']
    assert cluster.signature(rr[0],'relations')==cluster.signature(rr[1],'relations')
    assert cluster.signature(rr[0],'relations')!=cluster.signature(rr[2],'relations')


def test_embedded_program_is_retained_as_an_opaque_distinction():
    index,cluster,rows=build('send("n=1; use(n)")\nsend("n=2; use(n)")\n')
    rr=[r for r in rows if index.operations[r['key']]['name']=='send']
    assert cluster.signature(rr[0],'relations')!=cluster.signature(rr[1],'relations')


def test_selected_field_owner_distinguishes_object_from_returned_object():
    _,cluster,rows=build('''const a={reason:'x',report:function(){return {count:3}}};
const b={report:function(){return {reason:'x',count:3}}};
use(a);use(b);
''','test.ts',{'reason','report','count'})
    rr=[r for r in rows if r['interface']==('call','use')]
    assert cluster.signature(rr[0],'relations')!=cluster.signature(rr[1],'relations')


def test_joint_support_does_not_invent_cross_member_history():
    table=BehaviorTable()
    table.add('provider','A',{('mode','fast'),('bound',True)})
    table.add('provider','B',{('mode','slow'),('bound',False)})
    assert table.support('provider',{('mode','fast')})==1
    assert table.support('provider',{('bound',False)})==2
    assert table.support('provider',{('mode','fast'),('bound',False)})==0
    assert table.origins==['A','B']


def test_count_predicates_recognize_two_different_constructions():
    first=count_predicates({('duration',):[400,103,54,100]},{('threshold',):150,('shards',):2})
    second=count_predicates({('duration',):[400,300,200,100]},{('threshold',):350,('shards',):2})
    original=count_predicates({('duration',):[400,300,200,100]},{('threshold',):150,('shards',):2})
    key=lambda row:row[1]==('threshold',) and row[2]=='greater' and row[3]==('scalar','shards')
    assert list(filter(key,first))==list(filter(key,second))
    assert list(filter(key,first))!=list(filter(key,original))


def test_field_vocabulary_uses_attributes_and_literal_selectors():
    assert {'reason','count'}<=observed_fields('obj.reason; other["count"]')


def test_predicate_basis_preserves_the_full_input_partition():
    rows=[{'a':0,'b':0,'copy_a':0,'constant':1},{'a':1,'b':0,'copy_a':1,'constant':1},
          {'a':1,'b':1,'copy_a':1,'constant':1},{'a':1,'b':1,'copy_a':1,'constant':1}]
    basis,blocks=predicate_basis(rows)
    assert set(basis)=={'a','b'}
    assert sorted(map(tuple,blocks))==[(0,),(1,),(2,3)]


def test_nested_equal_values_are_not_merged_with_unequal_values():
    index,cluster,rows=build('''const a={entities:[{traits:{a:{x:1}}}]};
const b={entities:[{traits:{a:{x:1}},relations:{}}]};
const c={entities:[{traits:{a:{x:2}},relations:{}}]};
use(a,b);use(a,c);
''','test.ts')
    rr=[r for r in rows if r['interface']==('call','use')]
    assert cluster.signature(rr[0],'relations')!=cluster.signature(rr[1],'relations')


def test_interpolated_strings_do_not_establish_constant_content_equality():
    index,cluster,rows=build('send(f"{next_value()}",f"{next_value()}")\n')
    rr=next(r for r in rows if r['interface']==('call','send'))
    assert not cluster.literal_relations(rr['key'])


def test_query_can_start_at_a_constructor_on_the_entry_dependency_chain():
    index,_,_=build('def base():\n a=make()\n consume(a)\ndef donor():\n b=make()\n other(b)\n')
    entry=next(k for k,o in index.operations.items() if o['name']=='consume')
    records=index.view_features({'id':0,'source':'s','nodes':set(range(len(index.sources['s'][0].nodes))),'anchors':{entry}})
    assignments={(r['view'],*r['key']):i for i,r in enumerate(records)}
    makers=[r for r in records if r['interface']==('call','make')]
    first=next(r for r in makers if r['flow_anchor']);second=next(r for r in makers if not r['flow_anchor'])
    assert not first['anchor']
    edges=cluster_queries(index,records,assignments)
    assert (assignments[first['view'],*first['key']],assignments[second['view'],*second['key']]) in edges
