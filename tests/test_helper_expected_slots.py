import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from experimental.go_assertion_helper import HelperIndex
from experimental.helper_expected_slots import apply_response, inventory, prepare_request
from relation_search.oracle import preview
from relational_gap.frontend import extract_frontend,to_emitter_corpus


CODE='''package slots
import "testing"
type Box struct{value string}
func compare(t *testing.T, b *Box, desired string) {
    // 原始辅助函数 UTF-8.
    value,err:=read(b.value)
    if err!=nil {t.Fatal(err)}
    if value!=desired {t.Errorf("got %q, expected %q",value,desired)}
}
func TestSlots(t *testing.T) {
    b:=&Box{value:"input"}
    compare(t,b,"old")
    compare(t,b,"old")
    actual:=b.value
    if actual!="old" {t.Error("ordinary")}
}
'''


def fixture(code=CODE):
    front=extract_frontend([Source('pkg/slots_test.go',code,'go')])
    corpus=to_emitter_corpus(front)
    candidate=dict(id='fixed',base_test_id=next(iter(corpus['tests'])),edits=[])
    return corpus,front,candidate


def modify(corpus,candidate,before,after):
    owner=corpus['tests'][candidate['base_test_id']]['span']
    begin=corpus['sources'][owner['path']]['code'].encode().index(before.encode(),owner['start_byte'])
    candidate['edits'].append(dict(span=dict(path=owner['path'],start_byte=begin,end_byte=begin+len(before.encode())),before=before,after=after,role='input'))


def decisions(rows,changes=None):
    changes=changes or {}
    return {'decisions':[dict(id=row['id'],status='adapt',expected=changes[row['id']]) if row['id'] in changes else dict(id=row['id'],status='preserve') for row in rows if row['editable']]}


def test_joint_inventory_retains_regular_readonly_calls_and_each_helper_instance():
    corpus,front,candidate=fixture();frozen=copy.deepcopy((corpus,front,candidate))
    rows=inventory(corpus,front,candidate)
    helper=[row for row in rows if row['kind']=='helper_expected_call']
    assert [row['id'] for row in helper]==['H0','H1']
    assert all(row['editable'] for row in helper)
    assert helper[0]['slot']['target_span']!=helper[1]['slot']['target_span']
    assert sum(row['editable'] for row in rows if row['kind']=='ordinary_assertion')==1
    assert sum(not row['editable'] for row in rows if row['kind']=='ordinary_assertion')==2
    assert helper[0]['helper_call']['helper']['prerequisite_guards'][0]['failure_methods']==['Fatal']
    assert (corpus,front,candidate)==frozen


def test_request_contains_full_original_modified_test_helper_and_contract():
    corpus,front,candidate=fixture();modify(corpus,candidate,'"input"','"组合输入"')
    prepared=prepare_request(corpus,front,candidate,'Required output: new')
    request=prepared['request'];payload=json.loads(request['prompt'])
    assert payload['modified_test']==preview(corpus,candidate)
    assert '"input"' in payload['original_test'] and '"组合输入"' in payload['modified_test']
    assert payload['issue_contract']=='Required output: new'
    declaration,=payload['helper_declarations']
    assert declaration['code'].startswith('func compare(')
    assert 'if err!=nil {t.Fatal(err)}' in declaration['code']
    assert request['thinking']=='enabled' and request['oracle_validity']=='unconfirmed'


def test_helpers_and_regular_assertion_are_applied_only_at_expected_literal_positions():
    corpus,front,candidate=fixture();modify(corpus,candidate,'"input"','"changed input"')
    request=prepare_request(corpus,front,candidate,'Output new')['request']
    rows=request['inventory'];ordinary=next(row for row in rows if row['kind']=='ordinary_assertion' and row['editable'])
    answer=decisions(rows,{'H0':'"first"','H1':'"second"',ordinary['id']:'"ordinary new"'})
    result=apply_response(request,answer,corpus,front)
    assert result['status']=='adapt'
    expected=preview(corpus,candidate).replace('compare(t,b,"old")','compare(t,b,"first")',1)
    expected=expected.replace('compare(t,b,"old")','compare(t,b,"second")',1).replace('actual!="old"','actual!="ordinary new"')
    assert result['modified_test']==preview(corpus,result['candidate'])==expected
    assert result['candidate']['semantic_revision']['validity']=='unconfirmed'
    assert 'b:=&Box{value:"changed input"}' in result['modified_test']
    assert 't.Error("ordinary")' in result['modified_test']
    assert corpus['sources']['pkg/slots_test.go']['code']==CODE


@pytest.mark.parametrize('new',['consume()','actual','int(2)','2; panic(1)','[]string{"x"}'])
def test_new_expected_is_literal_only_and_cannot_edit_input_or_call(new):
    corpus,front,candidate=fixture();request=prepare_request(corpus,front,candidate,'x')['request']
    result=apply_response(request,decisions(request['inventory'],{'H0':new}),corpus,front)
    assert result['status']=='unknown' and result['candidate'] is None


@pytest.mark.parametrize('old',['saveAndReturn()','cached','string("old")'])
def test_effectful_named_or_wrapped_existing_helper_argument_is_readonly(old):
    corpus,front,candidate=fixture(CODE.replace('compare(t,b,"old")','compare(t,b,'+old+')',1))
    row=next(row for row in inventory(corpus,front,candidate) if row['id']=='H0')
    assert not row['editable'] and row['reason']=='expected_not_scalar_literal'


def test_missing_any_editable_regular_or_helper_answer_is_not_preserve():
    corpus,front,candidate=fixture();request=prepare_request(corpus,front,candidate,'x')['request']
    answer=decisions(request['inventory']);answer['decisions']=answer['decisions'][:-1]
    result=apply_response(request,answer,corpus,front)
    assert result['status']=='unknown' and result['reason']=='missing_joint_decisions'
    answer=decisions(request['inventory']);answer['decisions'][0]['status']='unknown'
    assert apply_response(request,answer,corpus,front)['reason']=='joint_oracle_incomplete'


def test_ordinary_assertion_keeps_existing_operand_guard_even_with_independent_helper_validator():
    corpus,front,candidate=fixture('package p\nimport "testing"\nfunc TestSlots(t *testing.T){if 1!=2{t.Error("bad")}}')
    request=prepare_request(corpus,front,candidate,'x')['request']
    row=next(row for row in request['inventory'] if row['editable'])
    answer=decisions(request['inventory'],{row['id']:row['observed']})
    assert apply_response(request,answer,corpus,front)['reason']=='ordinary_operand_guard_rejected'


@pytest.mark.parametrize('payload', ['{', {'decisions':[None]}, {'decisions':[{'id':[],'status':[]}]},
    {'decisions':[{'id':'H0','status':'adapt','expected':[]}]}, {'decisions':{}}, {'status':'unknown'}])
def test_malformed_answers_and_uncertainty_are_unknown_without_exception(payload):
    corpus,front,candidate=fixture();request=prepare_request(corpus,front,candidate,'x')['request']
    result=apply_response(request,payload,corpus,front)
    assert result['status']=='unknown' and result['candidate'] is None


def test_duplicate_or_unoffered_slot_or_full_code_is_rejected():
    corpus,front,candidate=fixture();request=prepare_request(corpus,front,candidate,'x')['request']
    answer=decisions(request['inventory']);answer['decisions'].append(answer['decisions'][0])
    assert apply_response(request,answer,corpus,front)['reason']=='invalid_or_duplicate_slot'
    answer=decisions(request['inventory']);answer['decisions'][0]['code']='panic(1)'
    assert apply_response(request,answer,corpus,front)['reason']=='invalid_decision_fields'


def test_literal_inside_whole_call_input_edit_is_spliced_without_overlapping_original_edits():
    corpus,front,candidate=fixture();modify(corpus,candidate,'compare(t,b,"old")','compare(t,other,"stale")')
    request=prepare_request(corpus,front,candidate,'required')['request']
    h0=next(row for row in request['inventory'] if row['id']=='H0')
    assert h0['slot']['location']['container_edit_index']==0
    result=apply_response(request,decisions(request['inventory'],{'H0':'"required"'}),corpus,front)
    assert result['status']=='adapt'
    assert result['candidate']['edits'][0]['after']=='compare(t,other,"required")'
    assert result['candidate']['edits'][0]['before']=='compare(t,b,"old")'
    assert preview(corpus,result['candidate'])==preview(corpus,candidate).replace('compare(t,other,"stale")','compare(t,other,"required")')


def test_multiple_call_literals_inside_one_replacement_and_inserted_call_roundtrip():
    corpus,front,candidate=fixture();modify(corpus,candidate,'compare(t,b,"old")','compare(t,other,"old");compare(t,other,"fresh")')
    request=prepare_request(corpus,front,candidate,'required')['request']
    result=apply_response(request,decisions(request['inventory'],{'H0':'"甲"','H1':'"乙"'}),corpus,front)
    assert result['status']=='adapt' and 'compare(t,other,"甲");compare(t,other,"乙")' in result['modified_test']
    corpus,front,candidate=fixture();modify(corpus,candidate,'compare(t,b,"old")','compare(t,b,"old")')
    extent=candidate['edits'][0]['span'];candidate['edits']=[dict(span=dict(extent,end_byte=extent['start_byte']),before='',after='compare(t,other,"inserted");',role='input')]
    request=prepare_request(corpus,front,candidate,'required')['request']
    result=apply_response(request,decisions(request['inventory'],{'H0':'"新"'}),corpus,front)
    assert result['status']=='adapt' and 'compare(t,other,"新");' in preview(corpus,result['candidate'])


def test_cached_index_does_not_reuse_equal_length_modified_call_binding():
    code=CODE.replace('func TestSlots','func bravo(desired string,t *testing.T,b *Box){if b.value!=desired {t.Error(desired)}}\nfunc TestSlots')
    corpus,front,first=fixture(code);index=HelperIndex(corpus)
    second=copy.deepcopy(first);second['id']='second'
    modify(corpus,second,'compare(t,b,"old")','bravo("old",t,b)')
    inventory(corpus,front,first,index=index)
    row=next(row for row in inventory(corpus,front,second,index=index) if row['id']=='H0')
    assert row['helper_call']['helper']['helper']=='bravo'
    assert row['helper_call']['expected_argument_index']==0
    assert row['slot']['expected']=='"old"'


def test_reparse_helper_declaration_after_test_when_program_edit_shifts_its_span():
    code=CODE[:CODE.index('func compare')]+CODE[CODE.index('func TestSlots'):]+CODE[CODE.index('func compare'):CODE.index('func TestSlots')]
    corpus,front,candidate=fixture(code);index=HelperIndex(corpus)
    modify(corpus,candidate,'"input"','"much longer new input"')
    request=prepare_request(corpus,front,candidate,'required',index=index)['request']
    declaration=json.loads(request['prompt'])['helper_declarations'][0]
    assert declaration['span']['start_byte']>code.encode().index(b'func compare')
    assert declaration['code'].startswith('func compare(')
    assert apply_response(request,decisions(request['inventory'],{'H0':'"new"'}),corpus,front)['status']=='adapt'


def test_source_candidate_inventory_tampering_and_budget_are_explicit_unknown():
    corpus,front,candidate=fixture();request=prepare_request(corpus,front,candidate,'x')['request']
    for field in ['source','candidate','inventory']:
        changed=copy.deepcopy(request);data=copy.deepcopy(corpus)
        if field=='source':data['sources']['pkg/slots_test.go']['code']+='\n'
        elif field=='candidate':changed['candidate']['id']='tampered'
        else:changed['inventory'][0]['editable']=True
        assert apply_response(changed,decisions(request['inventory']),data,front)['status']=='unknown'
    limited=prepare_request(corpus,front,candidate,'x',max_bytes=1)
    assert limited['request'] is None and limited['record']['status']=='unknown_context_budget'
    assert limited['record']['truncated'] is False


def test_runtime_probes_removed_and_historical_expected_snapshot_rejected():
    corpus,front,candidate=fixture();candidate.update(program_edits=[],instrumentation={'status':'instrumented'},
        edits=[dict(role='relation_runtime_probe',after='not source')])
    request=prepare_request(corpus,front,candidate,'x')['request']
    assert request is not None and 'not source' not in json.loads(request['prompt'])['modified_test']
    result=apply_response(request,decisions(request['inventory'],{'H0':'"new"'}),corpus,front)
    assert result['status']=='adapt' and 'instrumentation' not in result['candidate']
    candidate['program_edits']=[dict(role='semantic_expected')]
    assert prepare_request(corpus,front,candidate,'x')['request'] is None
