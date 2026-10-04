import copy
import json

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import sql_predicate_clamp as relation
from relation_search import sql_predicate_clamp_review as review


CODE = '''import pytest
def test_rule(store):
    store.register("score < 10")
    with pytest.raises(ValueError):
        store.insert({"score": 100})
    assert store.count() == 0
'''


def prepared(**kwargs):
    frontend = extract_frontend([Source('test_rule.py', CODE, 'python', 'repository')])
    corpus = to_emitter_corpus(frontend)
    candidate = relation.generate(corpus, frontend, 'Public requirement')['candidates'][0]
    return review.prepare(corpus, frontend, candidate, 'Use SQLite expressions to validate every row.', **kwargs)


def test_complete_program_and_explicit_domain_premises_reach_fresh_review():
    result = prepared()
    request = result['request']; payload = json.loads(request['prompt'])
    assert payload['original_test'].endswith('assert store.count() == 0')
    assert payload['modified_test'].endswith('assert store.count() == 0')
    assert 'min(score, 10) < 10' in payload['modified_test']
    assert payload['sql_predicate_reference'] == review.REFERENCE_FACTS
    assert set(review.EXTRA_CHECKS) <= set(request['check_ids'])
    assert request['no_execution_outcomes'] and request['no_evaluation_labels']
    assert request['id'] == review.whole_test._identity(request)
    assert 'TEXT/BLOB' in payload['checks']['SQL_VALUES']['question']
    answer = dict(basis='All complete-test and domain obligations require support.',
                  judgments={key: 'supported' for key in request['check_ids']})
    assert review.decide(request, answer)['status'] == 'semantic_supported'
    answer['judgments']['SQL_VALUES'] = 'unknown'
    decision = review.decide(request, answer)
    assert decision['status'] == 'unknown' and not decision['alarm_eligible']
    answer['judgments']['SQL_VALUES'] = 'unsupported'
    assert review.decide(request, answer)['status'] == 'semantic_rejected'


def test_missing_check_reference_changes_or_codec_bypass_cannot_admit():
    request = prepared()['request']
    supported = dict(basis='Hypothesis', judgments={key: 'supported' for key in request['check_ids']})
    missing = copy.deepcopy(supported); del missing['judgments']['SQL_DIALECT']
    assert review.decide(request, missing)['status'] == 'unknown'
    for which in ('reference', 'premise', 'codec', 'check_ids'):
        changed = copy.deepcopy(request); payload = json.loads(changed['prompt'])
        if which == 'reference':
            payload['sql_predicate_reference']['limits'] = 'Assume every SQL dialect is equivalent.'
        elif which == 'premise':
            payload['checks']['SQL_VALUES']['question'] = 'Assume numeric.'
        elif which == 'codec':
            changed['codec_guard']['allow_prior_gate'] = False
        else:
            changed['check_ids'].remove('SQL_CONSUMER')
        changed['prompt'] = json.dumps(payload)
        assert review.decide(changed, supported)['status'] == 'unknown'


def test_reference_is_whole_and_budget_failure_does_not_truncate_the_test():
    result = prepared(max_prompt_bytes=1)
    assert result['request'] is None and result['status'] == 'unknown_prompt_budget'
    assert result['truncated'] is False and result['required_bytes'] > 1

