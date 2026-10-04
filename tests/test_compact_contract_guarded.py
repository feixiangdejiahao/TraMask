"""Check complete-payload preservation, codec abstention, and final budgets."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import compact_admission, compact_contract_guarded as admission
from scripts import run_test_admission as runner


def example(code, *, before=None, after=None, api=None):
    path = 'tests/test_value.py'
    sources = [Source(path, code, 'python')]
    if api is not None:
        sources.append(Source('api.py', api, 'python'))
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    candidate = dict(id='generic', base_test_id=next(iter(corpus['tests'])),
                     edits=[], imports=[], source_test_ids=[])
    if before is not None:
        start = code.encode().index(before.encode())
        candidate['edits'] = [dict(span=dict(path=path, start_byte=start,
            end_byte=start + len(before.encode())), before=before, after=after, role='input')]
    return corpus, frontend, candidate


def documented_example():
    return example('from api import double\ndef test_value():\n    assert double(3) == 6\n',
        api='def double(value):\n    """Return twice the input value: 两倍."""\n'
            '    return candidate_private_body(value)\n')


def test_api_context_preserves_complete_compact_obligations_and_source_identity():
    args = documented_example()
    args[2]['evaluation_label'] = 'PRIVATE EVALUATION LABEL'
    args[2]['native_evidence'] = 'PRIVATE EXECUTION OUTCOME'
    originals = copy.deepcopy(args)
    baseline = compact_admission.prepare(*args, 'Return twice the input.')['request']
    result = admission.prepare(*args, 'Return twice the input.')
    request = result['request']
    payload = json.loads(request['prompt'])
    evidence = payload.pop('api_contract_context')
    assert payload == json.loads(baseline['prompt'])
    assert request['check_ids'] == baseline['check_ids']
    assert request['source_sha256'] == baseline['source_sha256']
    assert request['candidate_sha256'] == baseline['candidate_sha256']
    assert request['id'] == runner._request_identity(request) != baseline['id']
    assert '两倍' in str(evidence['records'])
    assert 'candidate_private_body' not in request['prompt']
    assert 'PRIVATE' not in request['prompt']
    assert args == originals
    assert runner._method(runner.METHODS['compact_contract_guarded']) is admission


@pytest.mark.parametrize('encoded', [False, True])
def test_multiline_input_edit_uses_actual_complete_modified_test_for_guard(encoded):
    before = 'result = consume(value)'
    argument = '__import__("shlex").quote(value)' if encoded else 'value'
    # This fragment cannot parse alone. Its later lines retain test indentation.
    after = 'ready = False\n    with expected_error():\n        result = consume('+argument+')'
    args = example('def test_value():\n    '+before+'\n    assert finished()\n',
                   before=before, after=after)
    result = admission.prepare(*args, 'Consume this value and check completion.')
    if encoded:
        assert result['status'] == 'unknown_codec_or_input_boundary'
        assert result['request'] is None and not result['alarm_eligible']
        assert result['withheld_not_invalid'] is True
        assert result['semantic_validity'] == 'unconfirmed'
        assert result['codec_guard']['additions'][0]['identities'] == ['shlex.quote']
    else:
        assert result['status'] == 'prepared'
        payload = json.loads(result['request']['prompt'])
        assert after in payload['modified_test']
        assert payload['modified_test'].endswith('assert finished()')
        assert not result['codec_guard']['unknown']


def test_import_alias_in_complete_source_cannot_hide_added_codec():
    args = example('from json import dumps as encode\ndef test_value():\n'
                   '    assert consume(value)\n',
                   before='consume(value)', after='consume(encode(value))')
    result = admission.prepare(*args, 'The consumer accepts its documented input.')
    assert result['request'] is None
    assert result['reason'] == 'new_codec_adapter_unproved'
    assert result['codec_guard']['additions'][0]['identities'] == ['json.dumps']


def test_final_utf8_budget_counts_added_api_context_and_never_truncates():
    args = documented_example()
    complete = admission.prepare(*args, 'Return twice the input.')
    request = complete['request']
    required = len(request['system'].encode()) + len(request['prompt'].encode())
    baseline = compact_admission.prepare(*args, 'Return twice the input.')
    assert baseline['prompt_bytes'] < required
    rejected = admission.prepare(*args, 'Return twice the input.', max_prompt_bytes=required - 1)
    assert rejected['status'] == 'unknown_prompt_budget'
    assert rejected['request'] is None and rejected['truncated'] is False
    assert rejected['required_bytes'] == required
    exact = admission.prepare(*args, 'Return twice the input.', max_prompt_bytes=required)
    assert exact['request'] == request


def test_model_support_cannot_override_missing_or_withheld_local_guard():
    request = admission.prepare(*documented_example(), 'Return twice the input.')['request']
    answer = dict(basis='The issue supports every check.',
                  judgments={key: 'supported' for key in request['check_ids']})
    assert admission.decide(request, answer)['alarm_eligible']
    for guard in ({}, {'allow_prior_gate': False}):
        altered = dict(request, codec_guard=guard)
        decision = admission.decide(altered, answer)
        assert decision['status'] == 'unknown'
        assert not decision['alarm_eligible']
