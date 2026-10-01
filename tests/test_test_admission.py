"""End-to-end source applicability queries with no real provider or repository."""
import copy
import json

from anchor_retrieval.syntax import Source
from relation_search import admission
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def toy():
    code = '''def sum_pair(a, b):
    return a + b

def test_pair():
    result = sum_pair(2, 3)
    assert result == 5
    assert result > 0
'''
    source = Source('test_pair.py', code, 'python')
    frontend = extract_frontend([source])
    corpus = to_emitter_corpus(frontend)
    test_id = next(iter(corpus['tests']))
    at = code.index('2, 3')
    candidate = dict(id='input', base_test_id=test_id, language='python',
        edits=[dict(span=dict(path=source.path, start_byte=at, end_byte=at+1),
                    before='2', after='7', role='input')], imports=[], source_test_ids=[])
    return corpus, frontend, candidate


def request():
    corpus, frontend, candidate = toy()
    result = admission.prepare(corpus, frontend, candidate, 'Return the sum of a and b.',
                               checks=dict(status='review', components={}))
    assert result['status'] == 'prepared'
    return corpus, candidate, result['request']


def test_query_covers_changed_test_and_every_later_observation_without_outcomes():
    _, _, req = request()
    wire = json.loads(req['prompt'])
    assert 'sum_pair(7, 3)' in wire['modified_test']
    assert 'sum_pair(2, 3)' in wire['original_test']
    assert 'assert result > 0' in wire['modified_test']
    assert len(req['check_ids']) == 3
    assert req['thinking'] == 'disabled' and req['max_tokens'] == 2048
    assert req['no_execution_outcomes'] and req['no_evaluation_labels']
    assert set(wire['checks']) == set(req['check_ids'])
    assert not any(key in wire for key in ['failure', 'ground_truth', 'target_test', 'verdict'])


def test_candidate_failure_does_not_certify_a_stale_expected_value():
    corpus, candidate, req = request()
    # The candidate's normal result is 10, so its source expectation 5 is stale.
    code = admission.preview(corpus, candidate)
    namespace = {'sum_pair': lambda a, b: a+b}
    exec(code, namespace)
    try:
        namespace['test_pair']()
    except AssertionError:
        pass
    else:
        raise AssertionError('stale oracle should actually fail the correct sum')
    rejected = admission.decide(req, {'P': 'unsupported', 'Q0': 'unsupported', 'Q1': 'supported'})
    assert not admission.alarm(rejected, generated_test_failed=True, all_source_controls_passed=True)


def test_partial_judgment_cannot_hide_wrong_later_assertions():
    _, _, req = request()
    for response in [{'P': 'supported', 'Q0': 'supported'},
                     {'P': 'supported', 'Q0': 'supported', 'Q1': 'unknown'}]:
        result = admission.decide(req, response)
        assert result['status'] == 'unknown' and not result['alarm_eligible']


def test_supported_hypothesis_still_needs_real_controlled_failure():
    _, _, req = request()
    result = admission.decide(req, {key: 'supported' for key in req['check_ids']})
    assert result['semantic_validity'] == 'model_hypothesis_requires_independent_evaluation'
    assert not admission.alarm(result, generated_test_failed=False, all_source_controls_passed=True)
    assert not admission.alarm(result, generated_test_failed=True, all_source_controls_passed=False)
    assert admission.alarm(result, generated_test_failed=True, all_source_controls_passed=True)


def test_truncated_response_and_budget_refusal_never_become_alarms():
    corpus, frontend, candidate = toy()
    result = admission.prepare(corpus, frontend, candidate, 'Return the sum.',
        checks=dict(status='review', components={}), max_prompt_bytes=10)
    assert result['request'] is None and result['status'] == 'unknown_prompt_budget'
    assert result['truncated'] is False
    _, _, req = request()
    decision = admission.decide(req, {key: 'supported' for key in req['check_ids']}, finish_reason='length')
    assert decision['status'] == 'unknown' and not decision['alarm_eligible']


def test_request_is_bound_to_complete_source_and_program_edits():
    corpus, candidate, req = request()
    assert admission.verify_snapshot(req, corpus, candidate)
    changed = copy.deepcopy(candidate)
    changed['edits'][0]['after'] = '9'
    assert not admission.verify_snapshot(req, corpus, changed)
    corpus['sources']['test_pair.py']['code'] += '\n# changed context\n'
    assert not admission.verify_snapshot(req, corpus, candidate)


def test_static_contradiction_prevents_any_semantic_query():
    corpus, frontend, candidate = toy()
    result = admission.prepare(corpus, frontend, candidate, 'Return sum.',
        checks=dict(status='invalid', components={'roles': {'findings': ['type contradiction']}}))
    assert result['request'] is None and result['status'] == 'static_invalid'
