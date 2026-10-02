"""The model gate must retain complete-test and source-coverage distinctions."""
import json

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import compact_admission as admission


def example(code):
    frontend = extract_frontend([Source('tests/test_acceptance.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend, dict(id='generic', base_test_id=next(iter(corpus['tests'])),
                                 edits=[], imports=[], source_test_ids=[])


def test_complete_test_and_source_guards_are_supplied_without_outcomes():
    corpus, frontend, candidate = example('''import pytest
def test_contract():
    with pytest.raises(ValueError):
        decode('malformed')
        assert 9 == 0
    assert closed()
''')
    candidate['native_evidence'] = 'PRIVATE NATIVE OUTCOME'
    candidate['evaluation_label'] = 'PRIVATE EVALUATION LABEL'
    result = admission.prepare(corpus, frontend, candidate, 'Malformed input is rejected and the resource closed.')
    assert result['status'] == 'prepared'
    request = result['request']; wire = json.loads(request['prompt'])
    assert 'assert 9 == 0' in wire['modified_test']
    assert 'assert closed()' in wire['modified_test']
    assert any(row.get('kind') == 'expected_exception' for row in wire['checks'].values())
    assert any(row.get('guards') for row in wire['checks'].values())
    assert 'PRIVATE' not in request['prompt']
    assert 'not_represented_by_Q' in wire['checks']['P']['scope']


def test_json_protocol_does_not_depend_on_source_code_vocabulary():
    result = admission.prepare(*example('def test_value():\n    assert double(3) == 6\n'),
                               'Compute twice the input.')
    # The provider rejects json_object requests unless JSON is named in a
    # message. A codebase mentioning the module by chance must not be needed.
    assert 'json' in result['request']['system'].lower()


def test_source_partial_is_not_reported_as_proved_complete():
    request = dict(id='frozen', check_ids=['P', 'Q0'], coverage={'source_sites_complete': False})
    result = admission.decide(request, {'basis': 'Contract supports the supplied checks.',
                                       'judgments': {'P': 'supported', 'Q0': 'supported'}})
    assert result['alarm_eligible']
    assert not result['source_sites_complete']
    assert result['semantic_validity'] == 'model_hypothesis_requires_independent_evaluation'


def test_any_unsupported_or_unknown_check_prevents_admission():
    request = dict(id='frozen', check_ids=['P', 'Q0'])
    for value, status in [('unsupported', 'semantic_rejected'), ('unknown', 'unknown')]:
        result = admission.decide(request, {'basis': 'Scope evidence.',
                                          'judgments': {'P': 'supported', 'Q0': value}})
        assert result['status'] == status
        assert not result['alarm_eligible']


def test_missing_or_malformed_judgments_and_truncation_cannot_admit():
    request = dict(id='frozen', check_ids=['P', 'Q0'])
    for answer in [None, {}, {'basis': [], 'judgments': {'P': 'supported', 'Q0': 'supported'}},
                   {'basis': '', 'judgments': {'P': 'supported'}},
                   {'basis': '', 'judgments': {'P': 'supported', 'Q0': []}},
                   {'basis': '', 'judgments': {'P': 'supported', 'Q0': 'supported'}, 'extra': True}]:
        assert not admission.decide(request, answer)['alarm_eligible']
    answer = {'basis': '', 'judgments': {'P': 'supported', 'Q0': 'supported'}}
    assert not admission.decide(request, answer, finish_reason='length')['alarm_eligible']


def test_prompt_budget_never_truncates_test_into_a_different_program():
    args = example('def test_value():\n    assert compute(3) == 6\n')
    result = admission.prepare(*args, 'Compute twice the input.', max_prompt_bytes=1)
    assert result['status'] == 'unknown_prompt_budget'
    assert result['request'] is None
    assert result['truncated'] is False


def test_large_check_messages_are_indexed_without_repeating_full_statement():
    message = 'diagnostic_' * 150
    code = f'def test_value():\n    assert compute(3) == 6, {message!r}\n'
    result = admission.prepare(*example(code), 'Compute twice the input.')
    assert result['status'] == 'prepared'
    payload = json.loads(result['request']['prompt'])
    check = next(row for key, row in payload['checks'].items() if key != 'P')
    assert check['expression']['text'] == 'compute(3) == 6'
    assert check['expression']['omitted_chars'] == 0
    assert message in payload['modified_test']
    assert message in payload['source_analysis']


def test_exception_check_indexes_type_without_duplicating_region_body():
    code = '''import pytest
def test_reject():
    with pytest.raises(ValueError):
        load('bad')
        assert unreachable_state()
'''
    result = admission.prepare(*example(code), 'Reject malformed inputs with ValueError.')
    payload = json.loads(result['request']['prompt'])
    check = next(row for row in payload['checks'].values() if row.get('kind') == 'expected_exception')
    assert check['expression']['text'] == 'ValueError'
    assert check['requires'] == 'matching_exception_adapter_exit'
    assert check['region']
    assert "load('bad')" in payload['modified_test']


def test_conditional_false_fact_is_evidence_not_an_unconditional_test_rejection():
    code = '''import pytest
def test_expected_failure():
    with pytest.raises(AssertionError):
        assert len([1]) == []
'''
    result = admission.prepare(*example(code), 'This check deliberately verifies assertion failure.')
    assert result['status'] == 'prepared'
    payload = json.loads(result['request']['prompt'])
    facts = payload['conditional_predicate_facts']
    assert len(facts['facts']) == 1
    assert facts['facts'][0]['normal_completion_value'] is False
    assert facts['facts'][0]['implies_test_invalid'] is False
    assert 'normally' in facts['premise']
    assert any(check.get('kind') == 'expected_exception' for check in payload['checks'].values())


def test_old_tests_can_supply_context_without_being_selected_validation_roots():
    code = '''import pytest
@pytest.fixture
def reader():
    return Reader()
def test_existing(reader):
    assert reader.read('abc') == 'ok'
def test_new(reader):
    assert reader.read('abd') == 'ok'
'''
    corpus, frontend, candidate = example(code)
    new_id = next(key for key in corpus['tests'] if 'test_new' in key)
    corpus['tests'] = {new_id: corpus['tests'][new_id]}
    candidate['base_test_id'] = new_id
    start = code.index("'abd'")
    candidate['edits'] = [dict(span=dict(path='tests/test_acceptance.py', start_byte=start,
                                       end_byte=start + 5), before="'abd'", after="'abe'", role='input')]
    result = admission.prepare(corpus, frontend, candidate, 'Reader accepts the supplied input formats.')
    payload = json.loads(result['request']['prompt'])
    assert any(control['name'] == 'test_existing' for control in payload['recovered_source_controls'])
