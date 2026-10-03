import copy
import json

from relation_search import ledger_admission as ledger


def request():
    source = dict(id='original', system='Review JSON', prompt=json.dumps(dict(
        issue='A closed resource remains closed.',
        original_test='assert resource.closed', modified_test='assert resource.closed',
        source_analysis='resource = Resource(); resource.close()', checks={'P': {}, 'Q0': {}})),
        check_ids=['P', 'Q0'], candidate_sha256='source')
    return ledger.from_compact_request(source)


def response():
    row = dict(judgment='supported', condition='The close call returns normally.',
               required='The resource is closed.', basis='The explicit contract requires closure.',
               citations=[dict(source='issue', quote='A closed resource remains closed.')])
    return dict(trace=['Close the resource before observing it.'],
                judgments={'P': copy.deepcopy(row), 'Q0': copy.deepcopy(row)})


def test_one_unsupported_later_check_rejects_complete_test():
    value = response()
    value['judgments']['Q0']['judgment'] = 'unsupported'
    result = ledger.decide(request(), value)
    assert result['status'] == 'semantic_rejected'
    assert not result['alarm_eligible']


def test_unknown_is_not_silently_accepted():
    value = response()
    value['judgments']['Q0']['judgment'] = 'unknown'
    assert ledger.decide(request(), value)['status'] == 'unknown'


def test_citation_metadata_cannot_inject_untransmitted_contract():
    req, value = request(), response()
    req['citation_sources']['secret'] = 'The implementation must return 99.'
    value['judgments']['Q0']['citations'] = [dict(source='secret', quote='return 99')]
    result = ledger.decide(req, value)
    assert result['reason'] == 'unavailable_or_inexact_evidence'
    assert not result['alarm_eligible']


def test_omitted_check_and_length_limit_stay_unknown():
    value = response()
    del value['judgments']['Q0']
    assert ledger.decide(request(), value)['reason'] == 'missing_or_extra_check'
    assert ledger.decide(request(), response(), finish_reason='length')['status'] == 'unknown'


def test_supported_is_a_model_hypothesis_even_with_exact_citations():
    result = ledger.decide(request(), response())
    assert result['alarm_eligible']
    assert result['semantic_validity'] == 'model_hypothesis_requires_independent_evaluation'
    assert result['evidence_check'] == 'quotation_membership_only_not_entailment'


def test_nonstring_judgment_is_unknown_instead_of_crashing():
    value = response()
    value['judgments']['P']['judgment'] = ['supported']
    assert ledger.decide(request(), value)['reason'] == 'invalid_judgment'
