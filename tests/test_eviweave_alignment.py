"""Real parsed expressions exercise the structural alignment contract."""
from eviweave.alignment import AlignmentIndex, RegionAlignmentIndex, TermIndex, anti_unify
from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph


def source(text, name='source', path='test.py'):
    graph=SourceGraph({'id':name,'path':path,'raw':text.encode()})
    assert not graph.issues
    return graph,BehaviorIndex(graph)


def expression(text, needle):
    graph,_=source(text)
    start=text.index(needle)
    return TermIndex(graph).term([start,start+len(needle)])


def test_alpha_alignment_retains_shared_reference_topology():
    a=expression('def f(x):\n return use(x, x)\n','use(x, x)')
    b=expression('def g(y):\n return use(y, y)\n','use(y, y)')
    c=expression('def g(y,z):\n return use(y, z)\n','use(y, z)')
    assert anti_unify(a,b)['holes']==[]
    assert any(h['kind']=='binding_topology' for h in anti_unify(a,c)['holes'])


def test_different_operators_and_literals_are_real_differences():
    a=expression('result = consume(x + 1)\n','x + 1')
    b=expression('result = consume(y - 2)\n','y - 2')
    result=anti_unify(a,b)
    assert len(result['holes'])==2
    assert {h['left_kind'] for h in result['holes']}=={'+','integer'}


def test_setup_keyword_changes_are_preserved_as_edits():
    sources={'a':source('r=Response(content=body)\n','a'),
             'b':source('r=Response(stream=chunks)\n','b')}
    index=AlignmentIndex(sources)
    a=next(k for k,o in index.operations.items() if k[0]=='a' and o['name']=='Response')
    b=next(k for k,o in index.operations.items() if k[0]=='b' and o['name']=='Response')
    result=index.align(a,b)
    assert {(h['slot'],h['kind']) for h in result['deltas']}=={
        ('keyword:content','delete'),('keyword:stream','insert')}


def test_receiver_context_ranks_without_removing_other_contexts():
    sources={'a':source('r=Response(data)\nr.consume()\n','a'),
             'b':source('x=Response(other)\nx.consume()\n','b'),
             'c':source('q=Queue()\nq.consume()\n','c')}
    index=AlignmentIndex(sources)
    a=next(k for k,o in index.operations.items() if k[0]=='a' and o['kind']=='call' and o['name']=='consume')
    rows=index.query(a)
    assert [row['key'][0] for row in rows]==['b','c']


def test_expression_ports_keep_creation_separate_from_consumption():
    graph,behavior=source('r=Response(body)\nlist(r.iter_multipart())\n')
    calls={op['name']:op for op in behavior.operations if op['kind']=='call'}
    assert calls['list']['expression_range']!=calls['iter_multipart']['expression_range']
    assert calls['list']['statement']==calls['iter_multipart']['statement']
    assert calls['list']['arguments'][0]['range']==calls['iter_multipart']['expression_range']


def test_nested_field_and_key_are_fixed_structure_not_alpha_names():
    a=expression("consume({'duration': row.value})\n","{'duration': row.value}")
    b=expression("consume({'duration': item.size})\n","{'duration': item.size}")
    result=anti_unify(a,b)
    assert len(result['holes'])==1
    assert result['holes'][0]['left_kind']=='identifier'


def test_region_query_retains_field_instead_of_outer_test_registration():
    code="test('one',()=>{const value={a:true}; use(value);});\ntest('two',()=>{const value={x:1,y:2}; use(value);});"
    index=RegionAlignmentIndex({'s':source(code,'s','test.ts')})
    start=code.index('a:true');result=index.query('s',start,start+len('a:true'))
    assert result['selection']['status']=='exact'
    assert result['selection']['selected'][0]['kind']=='field'
    target=code.index('{x:1,y:2}')
    assert any(r['range']==[target,target+len('{x:1,y:2}')] for r in result['channels']['structural_role'])


def test_operation_query_retrieves_observation_through_nested_receiver():
    code='def first():\n    r = Response(body)\n    list(r.parts())\ndef second():\n    s = Response(other)\n    list(s.parts())\n    assert s.closed\n'
    index=RegionAlignmentIndex({'s':source(code,'s')})
    start=code.index('list(r.parts())');result=index.query('s',start,start+len('list(r.parts())'))
    observed=code.index('assert s.closed')
    assert any(r['range']==[observed,observed+len('assert s.closed')]
               for r in result['channels']['observation_transfer'])


def test_return_shape_has_separate_method_call_channel():
    code="class Reporter:\n    def report(self):\n        return {'count': 1}\ndef check(reporter):\n    data=reporter.report()\n    assert data['count']==1\n"
    index=RegionAlignmentIndex({'s':source(code,'s')})
    start=code.index("return {'count': 1}")
    result=index.query('s',start,start+len("return {'count': 1}"))
    call=code.index('reporter.report()')
    assert any(r['range']==[call,call+len('reporter.report()')]
               for r in result['channels']['producer_consumer'])
