"""Guarded source obligations without a provider or hidden/heldout labels."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from relation_search import guarded_admission as admission


def setup(language,code,before=None,after=None,extra=None):
    path={'python':'tests/test_guarded.py','go':'guarded_test.go','typescript':'tests/guarded.test.ts'}[language]
    sources=[Source(path,code,language)]+[Source(p,c,language) for p,c in (extra or {}).items()]
    f=extract_frontend(sources);c=to_emitter_corpus(f)
    tid=next(iter(c['tests']));edits=[]
    if before is not None:
        at=code.encode().index(before.encode(),c['tests'][tid]['span']['start_byte'])
        edits=[dict(span=dict(path=path,start_byte=at,end_byte=at+len(before.encode())),
                    before=before,after=after,role='input')]
    return c,f,dict(id='anonymous',base_test_id=tid,edits=edits,imports=[],source_test_ids=[])


def prepared(*args,issue='Implement the documented task contract.'):
    result=admission.prepare(*args,issue)
    assert result['status']=='prepared',result
    return result['request'],json.loads(result['request']['prompt'])


def qs(wire):
    return [value for key,value in wire['checks'].items() if key!='P']


def instances(wire):
    return [wire['observations'][instance['observation_ref']]|{'invocation_ref':instance['invocation_ref']}
            for row in qs(wire) for instance in row['instances']]


def resolve(wire,row):
    if 'code' in row:
        return row['code']
    reference=row['source_ref'];value=wire
    for part in reference['context'].split('/'):
        value=value[int(part)] if isinstance(value,list) else value[part]
    code=value if isinstance(value,str) else value['code']
    return code.encode()[reference['start_byte']:reference['end_byte']].decode()


def invocation(wire,instance):
    value=wire['invocations'][instance['invocation_ref']]
    bindings=[]
    for ref in value['binding_refs']:
        binding=wire['argument_bindings'][ref]
        if 'values' in binding:
            binding=binding|dict(fixed_bindings=[dict(parameter=name,value=source) for name,source in binding['values'].items()])
        bindings.append(binding)
    return dict(call_path=[wire['call_sites'][ref] for ref in value['call_path_refs']],
                argument_bindings=bindings)


def absolute_span(wire,row):
    if 'span' in row:
        return row['span']
    reference=row['source_ref'];value=wire
    for part in reference['context'].split('/'):
        value=value[int(part)] if isinstance(value,list) else value[part]
    span=(wire['test_locations'][reference['context'].removesuffix('_test')]['span']
          if isinstance(value,str) else value['span'])
    return dict(path=span['path'],start_byte=span['start_byte']+reference['start_byte'],
                end_byte=span['start_byte']+reference['end_byte'])


def test_expected_exception_and_dormant_assertion_are_separate_guarded_obligations():
    code='''import pytest
def explode():raise ValueError('intentional')
def test_case():
    with pytest.raises(ValueError):
        explode()
        assert 2 == []
    assert 1 == 1
'''
    req,wire=prepared(*setup('python',code),issue='The operation must raise ValueError.')
    assert len(qs(wire))==3
    dormant=next(row for row in instances(wire) if resolve(wire,row['source'])=='assert 2 == []')
    assert any(wire['guards'][ref]['kind']=='with_statement' for ref in dormant['guards']['assertion_refs'])
    assert dormant['guards']['reachability']=='only_if_normal_execution_reaches_this_assertion'
    assert any(row['observation_type']=='exception' for row in instances(wire))
    assert 'guard => predicate' in req['system']
    assert wire['checks']['P']['scope']=='transformed_setup_and_call_applicability_only'
    decision=admission.decide(req,{key:'supported' for key in req['check_ids']})
    assert decision['alarm_eligible']


def test_one_helper_source_span_has_multiple_instantiated_call_contexts():
    code='''package demo
import "testing"
func check(t *testing.T, value int) {
 if value > 0 { if value != 1 {t.Fatal(value)} }
}
func TestCase(t *testing.T) {check(t,1);check(t,2)}
'''
    req,wire=prepared(*setup('go',code))
    assert req['check_ids']==['P','Q0']
    group=qs(wire)[0]
    assert len(group['instances'])==2
    assert all(row['predicate']=='==' for row in instances(wire))
    assert all(row['passing_predicate']==dict(form='negated_failure_guard',expression='value != 1') for row in instances(wire))
    assert all(any(wire['guards'][ref]['condition_text']=='value > 0' for ref in row['guards']['assertion_refs']) for row in instances(wire))
    bound=[resolve(wire,invocation(wire,row)['argument_bindings'][0]['fixed_bindings'][1]['value']) for row in group['instances']]
    assert bound==['1','2']


def test_implicit_failure_wrapper_guard_is_not_its_own_execution_precondition():
    code='''package demo
import "testing"
func fail(t *testing.T, message string){t.Fatalf(message)}
func verify(t *testing.T, left int, right int){if left!=right {fail(t,"bad")}}
func TestCase(t *testing.T){verify(t,1,1)}
'''
    _,wire=prepared(*setup('go',code))
    implicit=next(row for row in instances(wire) if row['kind']=='failure_guard')
    assert implicit['passing_predicate']==dict(form='negated_failure_guard',expression='left!=right')
    assert not any(wire['guards'][ref].get('condition_text')=='left!=right' for ref in implicit['guards']['assertion_refs'])
    assert resolve(wire,invocation(wire,implicit)['argument_bindings'][0]['fixed_bindings'][1]['value'])=='1'


def test_assertion_after_input_edit_uses_distinct_original_and_modified_namespaces():
    code='''def test_case():
    value = 1
    assert value == 1
'''
    c,f,k=setup('python',code,'value = 1','value = 1000')
    req,wire=prepared(c,f,k)
    row=qs(wire)[0];current=instances(wire)[0]['source']
    old_start=code.index('assert value')
    assert row['canonical_namespace']=='original'
    assert row['canonical_span']['start_byte']==old_start
    assert current['namespace']=='modified' and absolute_span(wire,current)['start_byte']==old_start+3
    assert 'value = 1000' in wire['modified_test'] and 'value = 1\n' in wire['original_test']
    assert admission.verify_snapshot(req,c,k)


def test_complete_replaced_assertion_retains_original_canonical_identity():
    code='def test_case():\n    assert value == 1\n'
    c,f,k=setup('python',code,'assert value == 1','assert value == 1000')
    k['edits'][0]['role']='semantic_expected'
    _,wire=prepared(c,f,k)
    row=qs(wire)[0]
    assert row['canonical_span']['end_byte']==code.index('assert value == 1')+len('assert value == 1')
    assert resolve(wire,instances(wire)[0]['source'])=='assert value == 1000'


def test_source_operand_order_is_preserved_even_if_actual_expected_roles_swap():
    _,wire=prepared(*setup('python','def test_case():\n    assert 0 < result\n'))
    row=instances(wire)[0]
    assert row['passing_predicate']==dict(form='assert_expression',expression='0 < result')


def test_same_assertion_text_at_two_source_positions_is_not_merged():
    req,wire=prepared(*setup('python','def test_case():\n    assert value == 1\n    assert value == 1\n'))
    assert req['check_ids']==['P','Q0','Q1']
    assert qs(wire)[0]['canonical_span']!=qs(wire)[1]['canonical_span']


def test_production_internal_assertion_and_body_are_not_exported_as_test_helpers():
    extra={'library.py':'def compute(value):\n    assert 1 == []\n    return CANDIDATE_BODY_SENTINEL\n'}
    c,f,k=setup('python','from library import compute\ndef test_case():\n    assert compute(1) == 1\n',extra=extra)
    req,wire=prepared(c,f,k)
    assert req['check_ids']==['P','Q0']
    assert all(row['canonical_span']['path']=='tests/test_guarded.py' for row in qs(wire))
    assert 'CANDIDATE_BODY_SENTINEL' not in req['prompt']
    assert 'def compute(value):' in req['prompt']
    assert not any(row['span']['path']=='library.py' for row in wire['validation_helpers'])
    assert req['coverage']['internal_assertions']
    assert req['coverage']['production_bodies_included'] is False


def test_ordinary_production_callee_is_not_helper_merely_because_support_says_so():
    extra={'src/library.ts':'export function create(value:number):number{return BUGGY_IMPLEMENTATION_SENTINEL;}' }
    code="import {create} from '../src/library';test('case',()=>{expect(create(1)).toBe(1)});"
    _,wire=prepared(*setup('typescript',code,extra=extra))
    assert not wire['validation_helpers']
    assert 'BUGGY_IMPLEMENTATION_SENTINEL' not in json.dumps(wire)
    assert any('function create(value:number):number' in row['code'] for row in wire['candidate_contract_headers'])


def test_trajectory_origin_does_not_turn_agent_production_code_into_validator():
    extra={'library.py':'def compute(value):\n    assert 1 == []\n    return AGENT_PRODUCTION_SENTINEL\n'}
    c,f,k=setup('python','from library import compute\ndef test_case():\n    assert compute(1) == 1\n',extra=extra)
    c['sources']['library.py']['origin']='trajectory'
    f['sources']['library.py']['origin']='trajectory'
    req,wire=prepared(c,f,k)
    assert req['check_ids']==['P','Q0']
    assert 'AGENT_PRODUCTION_SENTINEL' not in req['prompt']
    assert not any(row['span']['path']=='library.py' for row in wire['validation_helpers'])


def test_complete_validation_helper_body_and_later_assertions_are_retained():
    code='''def observe(value):
    if value:
        assert value == 1
def test_case():
    observe(1)
    assert tail == 3
    assert final == 5
'''
    _,wire=prepared(*setup('python',code))
    assert len(qs(wire))==3
    assert any('def observe(value)' in row['code'] and 'assert value == 1' in row['code'] for row in wire['validation_helpers'])
    assert 'assert tail == 3' in wire['modified_test'] and 'assert final == 5' in wire['modified_test']


def test_helper_expected_exception_boundary_is_an_implicit_q():
    code='''import pytest
def verify():
    with pytest.raises(ValueError):
        explode()
def test_case():
    verify()
    assert result == 1
'''
    _,wire=prepared(*setup('python',code))
    assert any(row['observation_type']=='exception' and invocation(wire,row)['call_path'] for row in instances(wire))


def test_original_source_control_is_complete_and_tagged_separately():
    code='''def test_case():
    assert value == 1
def test_control():
    setup = "full prerequisite"
    assert donor == 2
'''
    c,f,k=setup('python',code)
    k['source_test_ids']=[tid for tid in c['tests'] if tid!=k['base_test_id']]
    _,wire=prepared(c,f,k)
    assert len(wire['source_controls'])==1
    control=wire['source_controls'][0]
    assert control['namespace']=='original'
    assert 'full prerequisite' in control['code'] and 'assert donor == 2' in control['code']


def test_unknown_does_not_swallow_a_clear_unsupported_check():
    req,_=prepared(*setup('python','def test_case():\n    assert result == 1\n    assert later == 2\n'))
    assert admission.decide(req,{'P':'unknown','Q0':'unsupported','Q1':'unknown'})['status']=='semantic_rejected'
    assert admission.decide(req,{'P':'supported','Q0':'supported','Q1':'unknown'})['status']=='unknown'


def test_partial_and_truncated_model_response_never_certify_a_test():
    req,_=prepared(*setup('python','def test_case():\n    assert result == 1\n'))
    assert req['thinking']=='disabled' and req['max_tokens']==2048
    assert req['query_sha256']==req['id']
    assert req['no_execution_outcomes'] and req['no_evaluation_labels']
    assert admission.decide(req,{'P':'supported'})['status']=='unknown'
    assert admission.decide(req,{key:'supported' for key in req['check_ids']},finish_reason='length')['status']=='unknown'


def test_prompt_budget_refuses_complete_request_without_truncating_programs():
    c,f,k=setup('python','def test_case():\n    assert result == 1\n')
    result=admission.prepare(c,f,k,'Required result is one.',max_prompt_bytes=1)
    assert result['status']=='unknown_prompt_budget' and result['request'] is None
    assert result['truncated'] is False


@pytest.mark.parametrize('value',[None,True,1,[],{}])
def test_non_enum_provider_values_are_unknown(value):
    req,_=prepared(*setup('python','def test_case():\n    assert result == 1\n'))
    response={key:'supported' for key in req['check_ids']};response['Q0']=value
    assert admission.decide(req,response)['status']=='unknown'


def test_request_preparation_is_deterministic_and_does_not_mutate_sources():
    c,f,k=setup('typescript',"test('case',()=>{expect(result).toBe(1)});")
    frozen=copy.deepcopy((c,f,k))
    first=admission.prepare(c,f,k,'Return one.')
    assert admission.prepare(c,f,k,'Return one.')==first
    assert (c,f,k)==frozen


def test_recursive_validation_helper_makes_obligation_collection_incomplete():
    code='''def verify(value):
    assert value == 1
    if value > 0:
        verify(value - 1)
def test_case():
    verify(1)
'''
    req,wire=prepared(*setup('python',code))
    assert any(row['code']=='call_context_budget_or_recursion' for row in req['coverage']['missing_core'])
    assert not req['coverage']['core_complete']
    assert admission.decide(req,{key:'supported' for key in req['check_ids']})['reason']=='incomplete_obligation_coverage'
    assert admission.decide(req,{key:'unsupported' for key in req['check_ids']})['status']=='semantic_rejected'


def test_recursive_production_body_does_not_globally_hide_test_obligations():
    code='from library import compute\ndef test_case():\n    assert compute(1) == 1\n'
    extra={'library.py':'def compute(value):\n    if value > 0:\n        return compute(value-1)\n    return 1\n'}
    req,wire=prepared(*setup('python',code,extra=extra))
    assert req['coverage']['core_complete'] and not req['coverage']['missing_core']
    assert req['check_ids']==['P','Q0']
    assert 'return compute' not in req['prompt']


def test_transitive_helper_expected_exception_only_is_not_silently_omitted():
    code='''import pytest
def verify():
    with pytest.raises(ValueError):
        explode()
def outer():
    verify()
def test_case():
    outer()
    assert result == 1
'''
    req,wire=prepared(*setup('python',code))
    boundary=next(row for row in instances(wire) if row['observation_type']=='exception')
    assert len(invocation(wire,boundary)['call_path'])==2
    assert any('def verify()' in row['code'] for row in wire['validation_helpers'])
    assert req['coverage']['core_complete']


def test_multiple_assertions_share_one_exact_invocation_binding():
    code='''def verify(value):
    assert value == 1
    assert value < 2
def test_case():
    verify(1)
'''
    _,wire=prepared(*setup('python',code))
    assert len(qs(wire))==2
    assert len(wire['invocations'])==1
    assert all(row['invocation_ref']==0 for row in instances(wire))
    assert resolve(wire,invocation(wire,instances(wire)[0])['argument_bindings'][0]['fixed_bindings'][0]['value'])=='1'


def test_imported_conditional_failure_comparator_is_source_proved_validator():
    code='''package demo
import "testing"
import "demo/checks"
func TestCase(t *testing.T){checks.Compare(t,1,1)}
'''
    extra={'checks/checks.go':'''package checks
import "testing"
func Compare(t *testing.T,left int,right int){if left!=right{t.Fatal("mismatch")}}
'''}
    req,wire=prepared(*setup('go',code,extra=extra))
    assert any(row['passing_predicate']['form']=='negated_failure_guard' for row in instances(wire))
    assert any(row['span']['path']=='checks/checks.go' for row in wire['validation_helpers'])
    assert req['coverage']['core_complete']


def test_named_test_callback_to_opaque_api_keeps_conditional_checks_and_unknown_bindings():
    code='''from engine import invoke
def check(value):
    assert value == 999
def test_case():
    invoke(check)
    assert tail == 1
'''
    extra={'engine.py':'def invoke(callback):\n    callback(BUGGY_CALLBACK_ARGUMENT)\n'}
    req,wire=prepared(*setup('python',code,extra=extra))
    callback=next(row for row in instances(wire) if resolve(wire,row['source'])=='assert value == 999')
    value=invocation(wire,callback)
    assert value['call_path'][0]['invocation_precision']=='opaque_function_value_argument'
    assert value['argument_bindings'][0]['status']=='unknown'
    assert 'BUGGY_CALLBACK_ARGUMENT' not in req['prompt']
    assert any('def check(value)' in row['code'] for row in wire['validation_helpers'])


def test_two_same_line_anonymous_callbacks_keep_distinct_source_predicates():
    code="test('case',()=>{invoke(()=>{expect(first).toBe(1)},()=>{expect(second).toBe(2)});});"
    req,wire=prepared(*setup('typescript',code))
    assert len(qs(wire))==2
    assert len({tuple(row['canonical_span'].values()) for row in qs(wire)})==2
    assert any('first' in resolve(wire,row['source']) for row in instances(wire))
    assert any('second' in resolve(wire,row['source']) for row in instances(wire))
    assert all(invocation(wire,row)['call_path'] for row in instances(wire))
    assert all(invocation(wire,row)['argument_bindings'][0]['status']=='unknown' for row in instances(wire))


@pytest.mark.parametrize('language,code',[
    ('go','package demo\nimport "testing"\nfunc TestCase(t *testing.T){t.Fatal("forced");if tail!=1{t.Fatal(tail)}}\n'),
    ('python','import pytest\ndef test_case():\n    pytest.fail("forced")\n    assert tail == 1\n'),
])
def test_standalone_primitive_failure_is_not_silently_dormant(language,code):
    req,wire=prepared(*setup(language,code))
    failure=next(row for row in instances(wire) if row['observation_type']=='explicit_test_failure')
    assert failure['passing_predicate']==dict(form='uncaught_test_failure',expression='false')
    assert len(qs(wire))==2


def test_reassigned_pytest_import_is_not_source_proof_of_exception_adapter():
    code='''import pytest
pytest = replacement
def test_case():
    with pytest.raises(ValueError):
        explode()
    assert tail == 1
'''
    req,wire=prepared(*setup('python',code))
    assert not any(row['observation_type']=='exception' for row in instances(wire))
    assert not req['coverage']['core_complete']
    assert admission.decide(req,{key:'supported' for key in req['check_ids']})['status']=='unknown'
