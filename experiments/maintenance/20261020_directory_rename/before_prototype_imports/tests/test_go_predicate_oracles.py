"""Framework predicate polarity is an oracle slot, not a new test operation."""
import json

import pytest

from experimental.assertion_operand_guard import valid_assertion
from experimental.singleton_oracle_slots import adapt_response, expected_slot
from test_singleton_oracle_slots import adapted
from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.impact_selection import select


@pytest.mark.parametrize('positive,negative', [
    ('NoError', 'Error'), ('Nil', 'NotNil'), ('Empty', 'NotEmpty'), ('True', 'False')])
@pytest.mark.parametrize('receiver', ['require', 'assert'])
def test_same_observation_can_change_standard_predicate_polarity(positive, negative, receiver):
    old = f'{receiver}.{positive}(t, read(), "雪: %v", diagnostic())'
    new = old.replace('.'+positive+'(', '.'+negative+'(')
    assert valid_assertion(old, old, 'read()', 'go')
    assert valid_assertion(new, old, 'read()', 'go')
    assert valid_assertion(old, new, 'read()', 'go')


@pytest.mark.parametrize('replacement', [
    'assert.Error(t, read(), "same", details)',
    'require.Error(t, other(), "same", details)',
    'require.Error(t, read(), "different", details)',
    'require.Error(otherT, read(), "same", details)',
    'require.Error(t, read(), "same", details, read())',
    'require.Error(t, read())',
    'require.NotNil(t, read(), "same", details)',
    'require.ErrorIs(t, read(), "same", details)',
    'require.Equal(t, true, read())',
    'require.Error(t, read(), "same", details); reset()',
])
def test_predicate_edit_keeps_receiver_observation_messages_and_family(replacement):
    old = 'require.NoError(t, read(), "same", details)'
    assert not valid_assertion(replacement, old, 'read()', 'go')


def test_joint_error_and_value_changes_reach_production_validator():
    checks = [('require.NoError(t, err, "读取失败: %v", err)', 'err'),
              ('require.Equal(t, "previous", contents)', 'contents')]
    prepared, original, corpus, _ = adapted('go', checks)
    request = prepared['request']
    wire = json.loads(request['prompt'])
    assert wire['editable_assertions'][0]['allowed_predicates'] == ['NoError', 'Error']
    slot = request['slots']['A0']
    assert slot['kind'] == 'go_predicate' and slot['expected'] == 'NoError'
    response = adapt_response(request, {'decisions': [
        {'id': 'A0', 'status': 'adapt', 'expected': 'Error'},
        {'id': 'A1', 'status': 'adapt', 'expected': '""'}]}, corpus)
    assert response['status'] == 'adapt', response
    changes = response['revisions'][0]['edits']
    assert changes[0]['after'] == checks[0][0].replace('NoError(', 'Error(')
    assert changes[1]['after'] == 'require.Equal(t, "", contents)'
    assert response['oracle_validity'] == 'unconfirmed'
    assert original['offered']['C0']['candidate']['edits'] == []


@pytest.mark.parametrize('value', ['NotNil', 'Error(t, reset())', '"Error"', 'true'])
def test_predicate_slot_is_a_listed_method_not_an_arbitrary_expression(value):
    prepared, _, corpus, _ = adapted('go', [('require.NoError(t, err)', 'err')])
    result = adapt_response(prepared['request'], {'decisions': [
        {'id': 'A0', 'status': 'adapt', 'expected': value}]}, corpus)
    assert result['status'] == 'unknown' and not result['revisions']


def test_unsupported_or_wrong_observer_has_no_editable_predicate_slot():
    assert expected_slot('require.NoError(t, err)', 'other', 'go') is None
    assert expected_slot('custom.NoError(t, err)', 'err', 'go') is None
    assert expected_slot('require.ErrorIs(t, err, want)', 'err', 'go') is None


def test_frontend_separates_unary_diagnostics_from_expectation():
    source = Source('sample_test.go', '''package sample
func TestOperation(t *testing.T) {
    err := operation("old")
    require.NoError(t, err, "旧输入: %v", err)
}
''', 'go')
    frontend = extract_frontend([source])
    corpus = to_emitter_corpus(frontend)
    observation = next(row for row in frontend['observations'] if row.get('predicate') == 'NoError')
    assert observation.get('expected') is None
    at = source.data.index(b'"old"')
    candidate = dict(id='changed_argument', base_test_id=observation['test_id'],
        edits=[dict(span=dict(path=source.path, start_byte=at, end_byte=at+5),
                    before='"old"', after='"new"', role='input')], imports=[])
    result = select(corpus, frontend, [candidate], budget=1)
    assert result['selected'] == [candidate]
    evidence = result['ranking'][0]['evidence']
    assert evidence['obligations']
    assert all(row['expected_dependency_basis'] == 'assertion_predicate_has_no_expected_input_reads'
               for row in evidence['obligations'])
