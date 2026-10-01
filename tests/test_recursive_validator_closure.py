"""Source closure tests; no provider, executions, or evaluation labels."""
import copy
import json

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from relation_search.recursive_validator_closure import analyze


def prepared(code,language='python',extra=None,before=None,after=None,**limits):
    path={'python':'tests/test_closure.py','go':'closure_test.go','typescript':'tests/closure.test.ts'}[language]
    sources=[Source(path,code,language)]+[Source(p,c,language) for p,c in (extra or {}).items()]
    frontend=extract_frontend(sources);corpus=to_emitter_corpus(frontend)
    tid=next(iter(corpus['tests']));edits=[]
    if before is not None:
        at=code.encode().index(before.encode(),corpus['tests'][tid]['span']['start_byte'])
        edits=[dict(span=dict(path=path,start_byte=at,end_byte=at+len(before.encode())),before=before,after=after,role='input')]
    candidate=dict(id='anonymous',base_test_id=tid,edits=edits,imports=[],source_test_ids=[])
    return analyze(corpus,frontend,candidate,**limits)


def recursive(result):
    return [component for component in result['sccs'] if component['recursive']]


def check_graph_closed(result):
    vertices={row['id']:row for row in result['vertices']}
    sites={row['id']:row for row in result['check_sites']}
    edges={row['id']:row for row in result['transitions']}
    assert len({vertex for group in result['sccs'] for vertex in group['members']})==len(vertices)
    for group in result['sccs']:
        assert set(group['check_sites'])=={key for key,row in sites.items() if row['vertex'] in group['members']}
        assert set(group['internal_edges'])=={key for key,row in edges.items() if row['caller'] in group['members'] and row['callee'] in group['members']}
        assert set(group['outgoing_edges'])=={key for key,row in edges.items() if row['caller'] in group['members'] and row['callee'] not in group['members']}


def test_direct_recursion_preserves_source_predicate_root_binding_and_progress():
    code='''def verify(xs):
    assert len(xs) >= 0
    if xs:
        verify(xs[1:])
def test_case():
    verify([1,2,3])
'''
    result=prepared(code)
    assert result['status']=='complete' and result['coverage']['source_complete']
    assert not result['alarm_eligible'] and result['semantic_validity']=='unconfirmed'
    assert len(recursive(result))==1 and len(result['vertices'])==2 and len(result['transitions'])==2
    edge=next(row for row in result['transitions'] if row['caller']==row['callee'])
    assert edge['transforms'][0]['value']['code']=='xs[1:]'
    assert edge['guards'][0]['condition_text']=='xs'
    root_edge=next(row for row in result['transitions'] if row['caller']==result['root_vertex'])
    assert root_edge['transforms'][0]['value']['code']=='[1,2,3]'
    assert result['check_sites'][0]['passing_predicate']['expression']=='len(xs) >= 0'
    check_graph_closed(result)


def test_mutual_recursion_covers_every_local_site_and_scc_outgoing_edge():
    code='''def leaf(value):
    assert value >= 0
def first(value):
    assert value != -1
    if value:
        second(value-1)
    leaf(value)
def second(value):
    assert value != -2
    if value:
        first(value-1)
def test_case():
    first(3)
'''
    result=prepared(code)
    assert result['status']=='complete'
    group=recursive(result)[0]
    assert len(group['members'])==2 and len(group['check_sites'])==2
    assert len(group['internal_edges'])==2 and len(group['outgoing_edges'])==1
    assert len(result['check_sites'])==3
    check_graph_closed(result)


def test_nested_map_list_comparator_has_finite_symbolic_element_transitions():
    code='''def compare(left,right):
    assert type(left) is type(right)
    if isinstance(left,dict):
        assert left.keys() == right.keys()
        for key in left:
            compare(left[key],right[key])
    elif isinstance(left,list):
        assert len(left) == len(right)
        for x,y in zip(left,right):
            compare(x,y)
    else:
        assert left == right
def test_case():
    compare({'x':[1,{'y':2}]},{'x':[1,{'y':2}]})
'''
    result=prepared(code)
    assert result['status']=='complete'
    assert len(recursive(result))==1 and len(result['check_sites'])==4
    edges=[row for row in result['transitions'] if row['caller']==row['callee']]
    assert [[binding['value']['code'] for binding in edge['transforms']] for edge in edges]==[['left[key]','right[key]'],['x','y']]
    assert all(any(guard['kind']=='for_statement' for guard in edge['guards']) for edge in edges)
    assert 'EVERY state' in result['closure_semantics']
    check_graph_closed(result)


def test_wrong_recursive_progress_is_retained_and_not_claimed_terminating():
    good=prepared('def check(n):\n    assert n >= 0\n    if n:\n        check(n-1)\ndef test_case():\n    check(2)\n')
    bad=prepared('def check(n):\n    assert n >= 0\n    if n:\n        check(n)\ndef test_case():\n    check(2)\n')
    assert good['status']==bad['status']=='complete'
    edge=next(row for row in bad['transitions'] if row['caller']==row['callee'])
    assert edge['transforms'][0]['value']['code']=='n'
    assert not bad['coverage']['termination_proved'] and not bad['coverage']['predicate_truth_proved']
    assert not bad['alarm_eligible']


def test_source_proved_go_failure_guard_and_recursive_helper_are_one_scc():
    code='''package demo
import "testing"
func verify(t *testing.T, xs []int){
 if len(xs)>0 {if xs[0]<0 {t.Fatal(xs[0])};verify(t,xs[1:])}
}
func TestCase(t *testing.T){verify(t,[]int{1,2})}
'''
    result=prepared(code,'go')
    assert result['status']=='complete'
    site=next(row for row in result['check_sites'] if row['passing_predicate']['form']=='negated_failure_guard')
    assert site['passing_predicate']['expression']=='xs[0]<0'
    assert any(guard['condition_text']=='len(xs)>0' for guard in site['guards'])
    assert len(recursive(result))==1
    check_graph_closed(result)


def test_standalone_source_testing_failure_is_an_explicit_local_site():
    result=prepared('package demo\nimport "testing"\nfunc stop(t *testing.T){t.Fatal("bad")}\nfunc TestCase(t *testing.T){stop(t)}\n','go')
    assert result['status']=='complete'
    assert any(site['passing_predicate']==dict(form='uncaught_test_failure',expression='false') for site in result['check_sites'])


def test_ordinary_production_recursion_is_opaque_and_has_no_oracle_sites_or_body():
    code='from library import compute\ndef test_case():\n    assert compute(2) == 1\n'
    extra={'library.py':'def compute(n):\n    assert PRODUCTION_ASSERT_SENTINEL\n    return compute(n-1) if n else PRODUCTION_BODY_SENTINEL\n'}
    result=prepared(code,extra=extra)
    assert result['status']=='complete' and not recursive(result)
    assert len(result['check_sites'])==1 and len(result['vertices'])==1
    serialized=json.dumps(result)
    assert 'PRODUCTION_ASSERT_SENTINEL' not in serialized and 'PRODUCTION_BODY_SENTINEL' not in serialized
    assert 'def compute(n):' in serialized


def test_missing_standalone_validator_source_is_partial():
    result=prepared('from helpers import verify\ndef test_case():\n    verify(1)\n    assert tail == 1\n')
    assert result['status']=='partial'
    assert any(row['code']=='validator_dispatch_unproved' for row in result['unknowns'])
    assert not result['coverage']['source_complete']


def test_dynamic_method_validator_dispatch_is_partial():
    result=prepared('def verify(obj):\n    obj.inspect()\n    assert tail == 1\ndef test_case():\n    verify(subject)\n')
    assert result['status']=='partial'
    assert any(row.get('callee_expression')=='obj.inspect' for row in result['unknowns'])


def test_named_callback_in_opaque_production_api_keeps_sites_and_unknown_binding():
    code='''from engine import invoke
def check(value):
    assert value == 1
def test_case():
    invoke(check)
    assert tail == 2
'''
    result=prepared(code,extra={'engine.py':'def invoke(callback):\n    callback(BUGGY_CALLBACK_ARGUMENT)\n'})
    assert result['status']=='partial' and len(result['check_sites'])==2
    assert any(row['kind']=='function_value_argument' for row in result['entries'])
    assert any(row['code']=='callback_invocation_binding_unproved' for row in result['unknowns'])
    assert 'BUGGY_CALLBACK_ARGUMENT' not in json.dumps(result)


def test_formal_callback_dispatch_is_not_declared_closed_without_points_to_proof():
    code='''def call(fn,value):
    fn(value)
def check(value):
    assert value == 1
def test_case():
    call(check,1)
'''
    result=prepared(code)
    assert result['status']=='partial'
    assert any(row.get('callee_expression')=='fn' for row in result['unknowns'])
    assert any(site['source']['code']=='assert value == 1' for site in result['check_sites'])


def test_source_fixture_checks_are_preserved_before_root_test():
    code='''import pytest
@pytest.fixture
def seed():
    assert initial == 1
    return 2
def test_case(seed):
    assert seed == 2
'''
    result=prepared(code)
    assert result['status']=='complete' and len(result['check_sites'])==2
    fixture=next(row for row in result['entries'] if row['kind']=='source_pytest_fixture')
    assert fixture['bound_parameter']=='seed'
    assert any('@pytest.fixture' in row['source']['code'] for row in result['vertices'])


def test_missing_fixture_source_and_reassigned_decorator_are_partial():
    missing=prepared('def test_case(seed):\n    assert seed == 1\n')
    rebound=prepared('import pytest\npytest=replacement\n@pytest.fixture\ndef seed():return 1\ndef test_case(seed):\n    assert seed == 1\n')
    assert missing['status']==rebound['status']=='partial'
    assert any(row['code']=='fixture_adapter_identity_unproved' for row in rebound['unknowns'])


def test_fixture_dependency_cycle_is_explicit_partial_not_host_recursion_failure():
    code='''import pytest
@pytest.fixture
def left(right):return right
@pytest.fixture
def right(left):return left
def test_case(left):assert left == 1
'''
    result=prepared(code)
    assert result['status']=='partial'
    assert any(row['code']=='fixture_dependency_cycle' for row in result['unknowns'])


def test_missing_fixed_binding_and_spread_are_partial_with_represented_target_sites():
    result=prepared('def verify(left,right):\n    assert left == right\ndef test_case():\n    verify(1)\n')
    spread=prepared('def verify(left,right):\n    assert left == right\ndef test_case():\n    verify(*values)\n')
    for graph in (result,spread):
        assert graph['status']=='partial' and len(graph['check_sites'])==1
        assert any(row['code']=='validator_binding_unproved' for row in graph['unknowns'])


def test_source_budget_is_partial_and_never_silently_complete():
    result=prepared('def verify(value):\n    assert value == 1\ndef test_case():\n    verify(1)\n',max_units=1)
    assert result['status']=='partial' and not result['coverage']['source_complete']
    assert any(row['code']=='validator_unit_budget' for row in result['unknowns'])


def test_assertion_byte_identity_survives_edited_root_input_size():
    code='def verify(value):\n    assert value == 1\ndef test_case():\n    value = 1\n    assert value == 1\n    verify(value)\n'
    result=prepared(code,before='value = 1',after='value = 1000')
    root=next(site for site in result['check_sites'] if site['vertex']==result['root_vertex'])
    assert root['source']['span']['start_byte']==root['canonical_span']['start_byte']+3
    assert root['canonical_span']['start_byte']==code.rindex('assert value')


def test_preparation_is_deterministic_and_has_no_semantic_acceptance():
    code='def verify(n):\n    assert n >= 0\n    if n:verify(n-1)\ndef test_case():verify(1)\n'
    first=prepared(code)
    assert prepared(code)==first
    assert first['semantic_validity']=='unconfirmed' and not first['alarm_eligible']
    assert first['coverage']['predicate_truth_proved'] is False


def test_rebound_validator_symbol_is_partial_not_a_source_resolved_edge():
    code='''def verify(value):
    assert value == 1
verify = factory()
def test_case():
    verify(1)
    assert tail == 1
'''
    result=prepared(code)
    assert result['status']=='partial'
    assert not result['transitions']


def test_arbitrary_decorator_does_not_prove_underlying_validator_dispatch():
    result=prepared('@decorate\ndef verify(value):\n    assert value == 1\ndef test_case():verify(1)\n')
    assert result['status']=='partial'
    assert any(row['code']=='decorated_validator_dispatch_unproved' for row in result['unknowns'])


def test_generated_import_shadowing_keeps_source_closure_partial():
    sources=[Source('tests/test_closure.py','from old import verify\ndef test_case():\n    verify(1)\n','python'),
             Source('old.py','def verify(value):\n    assert value == 1\n','python'),
             Source('new.py','def verify(value):\n    assert value == 2\n','python')]
    frontend=extract_frontend(sources);corpus=to_emitter_corpus(frontend)
    candidate=dict(id='shadowed',base_test_id=next(iter(corpus['tests'])),edits=[],source_test_ids=[],
                   imports=[dict(name='verify',module='new',imported_name='verify')])
    result=analyze(corpus,frontend,candidate)
    assert result['status']=='partial' and not result['coverage']['source_complete']
    assert any(row['code']=='modified_import_binding_unproved' for row in result['unknowns'])


def test_typescript_recursive_helper_keeps_native_expect_and_child_binding():
    code="import {expect,test} from 'vitest';function check(xs:number[]){expect(xs.length).toBeGreaterThanOrEqual(0);if(xs.length){check(xs.slice(1));}}test('case',()=>{check([1,2,3]);});"
    result=prepared(code,'typescript')
    assert result['status']=='complete' and len(result['check_sites'])==1
    assert result['check_sites'][0]['passing_predicate']['expression']=='expect(xs.length).toBeGreaterThanOrEqual(0)'
    edge=next(row for row in result['transitions'] if row['caller']==row['callee'])
    assert edge['transforms'][0]['value']['code']=='xs.slice(1)'
    assert len(recursive(result))==1
    check_graph_closed(result)


def test_parameter_rows_require_source_proved_decorator_identity():
    good=prepared('import pytest\n@pytest.mark.parametrize("value",[1,2])\ndef test_case(value):assert value > 0\n')
    fake=prepared('@custom.parametrize("value",[1,2])\ndef test_case(value):assert value > 0\n')
    rebound=prepared('import pytest\npytest=replacement\n@pytest.mark.parametrize("value",[1,2])\ndef test_case(value):assert value > 0\n')
    assert good['status']=='complete'
    assert fake['status']==rebound['status']=='partial'
    assert any(row['code']=='parameter_adapter_identity_unproved' for row in fake['unknowns'])
    assert all(row['adapter_identity_proved'] for row in good['entries'] if row['kind']=='source_parameter_rows')
