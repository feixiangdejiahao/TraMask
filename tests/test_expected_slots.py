import json

from relation_search import expected_slots
from tests.test_review_repair import fixture


def test_masked_expected_value_is_filled_without_changing_the_input():
    corpus,frontend,candidate,_,_=fixture()
    request=expected_slots.prepare(corpus,frontend,candidate,'Return the number of list items.')['request']
    wire=json.loads(request['prompt'])
    assert 'assert result == __EXPECTED_E0__' in wire['modified_test_with_expected_slots']
    assert 'assert result == 1' not in request['prompt']
    result=expected_slots.validate(request,dict(status='derived',expected={'E0':'2'},basis='The list has two items.'),corpus)
    assert result['changed']
    assert result['candidate']['edits'][0]==candidate['edits'][0]
    assert result['candidate']['edits'][1]['after']=='assert result == 2'


def test_new_calls_and_missing_operands_cannot_escape_the_slot():
    corpus,frontend,candidate,_,_=fixture()
    request=expected_slots.prepare(corpus,frontend,candidate,'Count items.')['request']
    for expected in ({},{'E0':'clear()'},{'E0':'2; xs.clear()'}):
        result=expected_slots.validate(request,dict(status='derived',expected=expected,basis='A claim.'),corpus)
        assert result['candidate'] is None


def test_go_failure_guard_and_predicate_slots_preserve_diagnostics():
    code='if got != want { t.Fatalf("got %s, want %s", got, want) }'
    found=expected_slots.slot(code,'got','go')
    assert expected_slots.fill(code,found,'"new"','go')=='if got != "new" { t.Fatalf("got %s, want %s", got, want) }'
    code='require.NoError(t, err, "message")'
    found=expected_slots.slot(code,'err','go')
    assert expected_slots.fill(code,found,'Error','go')=='require.Error(t, err, "message")'


def test_python_identity_to_value_uses_equality_and_keeps_message():
    code='assert value is None, "diagnostic"'
    found=expected_slots.slot(code,'value','python')
    result=expected_slots.fill(code,found,'"filled"','python')
    assert result=="assert value == 'filled', 'diagnostic'"


def test_typescript_expected_container_cannot_replace_observed_call():
    code='expect(read()).toEqual([1]);'
    found=expected_slots.slot(code,'read()','typescript')
    assert expected_slots.fill(code,found,'[1, 2]','typescript')=='expect(read()).toEqual([1, 2]);'


def test_complete_rankings_deduplicate_without_changing_first_occurrence_order():
    from scripts.run_expected_slot_search import normalized_ranking
    request=dict(aliases={'C0':'a','C1':'b','C2':'c'},budget=2)
    result=normalized_ranking(request,'{"ranking":["C1","C1","C2","C0"]}','stop')
    assert result['selected']==['b','c']
    assert result['duplicate_aliases_removed']==1
    assert not normalized_ranking(request,'{"ranking":["C1","missing"]}','stop')['selected']
    assert not normalized_ranking(request,'{"ranking":["C1"]}','length')['selected']
