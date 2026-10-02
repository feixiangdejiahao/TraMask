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
