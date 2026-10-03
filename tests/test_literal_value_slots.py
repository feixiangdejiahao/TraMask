import json
import pytest

from relation_search import expected_slots,literal_value_slots
from tests.test_review_repair import fixture


def test_json_numbers_become_language_literals_without_model_generated_code():
    corpus,frontend,candidate,_,_=fixture()
    raw=expected_slots.prepare(corpus,frontend,candidate,'Count items.')['request']
    request=literal_value_slots.from_raw(raw,corpus)
    result=literal_value_slots.validate(request,dict(status='derived',
        expected={'E0':dict(kind='number',value=2)},basis='Two items.'),corpus)
    assert result['candidate']['edits'][1]['after']=='assert result == 2'
    assert result['candidate']['edits'][0]==candidate['edits'][0]


def test_string_newlines_are_quoted_by_the_program():
    descriptor=dict(kinds=['string'])
    assert literal_value_slots.encode(dict(kind='string',value='ours\n'),'go',descriptor,'"old"')=='"ours\\n"'
    assert literal_value_slots.encode(dict(kind='string',value='hello\n'),'python',descriptor,"'old'")=="'hello\\n'"


def test_effectful_and_relational_expected_expressions_remain_fixed():
    code="assert current == previous['cycle'] + 1"
    slot=expected_slots.slot(code,'current','python')
    assert literal_value_slots._descriptor(code,slot,'python') is None


def test_existing_go_conversion_keeps_its_name():
    code='require.Equal(t, int64(3), got)'
    slot=expected_slots.slot(code,'got','go')
    descriptor=literal_value_slots._descriptor(code,slot,'go')
    assert literal_value_slots.encode(dict(kind='number',value=4),'go',descriptor,'int64(3)')=='int64(4)'


def test_echoed_retained_reference_must_match_the_unchanged_source_exactly():
    descriptor=dict(kinds=['same'])
    assert literal_value_slots.encode(dict(kind='same',source_reference='previous'),'python',descriptor,'previous')=='previous'
    with pytest.raises(ValueError):
        literal_value_slots.encode(dict(kind='same',source_reference='other'),'python',descriptor,'previous')
