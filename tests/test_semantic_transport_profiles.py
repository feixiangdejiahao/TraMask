"""Completion profiles change bounded request settings, never candidate content."""
import copy
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from prototypes.test_action_and_oracle_transfer import model
from scripts import run_semantic_transport as transport


def empty_inputs():
    pending = {'candidates': [], 'shown_ids': [], 'counts': {'candidates': 0, 'shown': 0}}
    corpus = {'language': 'python', 'sources': {}, 'tests': {}, 'coverage': {}}
    return corpus, pending, model.presentation(corpus, {}, pending)


def legacy_request(shown):
    return {'model': model.MODEL, 'max_tokens': 10000, 'temperature': 0,
            'thinking': {'type': 'disabled'}, 'reasoning_effort': 'none',
            'response_format': {'type': 'json_object'}, 'tool_choice': 'none',
            'messages': [{'role': 'system', 'content': model.SYSTEM},
                         {'role': 'user', 'content': json.dumps(shown, sort_keys=True,
                                                              ensure_ascii=True, allow_nan=False)}]}


def test_default_request_bytes_are_unchanged_and_profiles_keep_identical_messages():
    _, pending, shown = empty_inputs()
    original = copy.deepcopy(shown)
    standard = model.request_payload(shown)
    assert model.encoded(standard) == model.encoded(legacy_request(shown))
    assert model.request_payload(dict(shown, completion_profile='standard')) == standard
    reasoned = model.request_payload(dict(shown, completion_profile='reasoned_32k'))
    assert {key for key in reasoned if reasoned[key] != standard[key]} == {
        'max_tokens', 'thinking', 'reasoning_effort'}
    assert reasoned['max_tokens'] == 32000
    assert reasoned['thinking'] == {'type': 'enabled'}
    assert reasoned['reasoning_effort'] == 'low'
    assert reasoned['messages'] == standard['messages']
    assert shown == original
    assert json.loads(reasoned['messages'][1]['content'])['max_completions'] == 8
    model.validate_input(dict(shown, completion_profile='reasoned_32k'), pending)


@pytest.mark.parametrize('profile', ['unknown', None, [], {}, 32000])
def test_unknown_profile_cannot_become_arbitrary_request_settings(profile):
    _, pending, shown = empty_inputs()
    shown['completion_profile'] = profile
    with pytest.raises(ValueError, match='Unknown completion profile'):
        model.validate_input(shown, pending)
    with pytest.raises(ValueError, match='Unknown completion profile'):
        model.request_payload(shown)


@pytest.mark.parametrize('profile', ['standard', 'reasoned_32k'])
def test_profile_cache_replays_offline_and_rejects_cross_profile_reuse(tmp_path, profile):
    _, pending, shown = empty_inputs()
    if profile != 'standard':
        shown['completion_profile'] = profile
    with patch.object(model, 'dotenv_values') as credentials, patch.object(model.httpx, 'Client') as client:
        directory = tmp_path / 'completion'
        record = model.request_completion(shown, pending, directory)
        checked, validation = model.load_completion(directory, shown, pending)
        assert checked['valid'] and validation == {'accepted': [], 'rejected': []}
        assert record['external_model_calls'] == 0
        other = dict(shown, completion_profile='reasoned_32k' if profile == 'standard' else 'standard')
        with pytest.raises(ValueError, match='Cached completion input changed'):
            model.load_completion(directory, other, pending)
        credentials.assert_not_called()
        client.assert_not_called()


@pytest.mark.parametrize('profile', ['standard', 'reasoned_32k'])
def test_prepare_freezes_profile_and_uses_actual_request_budget(tmp_path, profile):
    corpus, pending, _ = empty_inputs()
    source = tmp_path / 'source'
    source.mkdir()
    values = {'case.json': {'id': 'synthetic'}, 'corpus.json': corpus,
              'retrieval.json': {}, 'evidence.json': {}}
    for name, value in values.items():
        model.write_json(source / name, value)
    model.write_json(source / 'prepare.json', {
        'case_id': 'synthetic', 'status': 'complete',
        'files_sha256': {name: model.digest((source / name).read_bytes()) for name in values}})
    args = SimpleNamespace(case='synthetic', source_prepared=source,
                           output=tmp_path / 'prepared', completion_profile=profile)
    with ExitStack() as stack:
        stack.enter_context(patch.object(transport.driver, 'algorithm_hashes', return_value={}))
        stack.enter_context(patch.object(transport, 'transport_hashes', return_value={}))
        generate = stack.enter_context(patch.object(transport.proposals, 'generate', return_value=pending))
        credentials = stack.enter_context(patch.object(model, 'dotenv_values'))
        client = stack.enter_context(patch.object(model.httpx, 'Client'))
        transport.prepare(args)
        manifest = transport.checked_inputs(args)
        request = json.loads((args.output / 'request_template.json').read_bytes())
        shown = json.loads((args.output / 'input.json').read_bytes())
        assert manifest['budget']['max_output_tokens_per_round'] == request['max_tokens']
        assert request['max_tokens'] == (32000 if profile == 'reasoned_32k' else 10000)
        assert manifest['budget']['model_calls_per_round'] == 1
        assert manifest['budget']['max_completions_per_round'] == 8
        assert ('completion_profile' in shown) == (profile != 'standard')
        assert ('completion_profile' in manifest) == (profile != 'standard')
        assert json.loads((args.output / 'pending.json').read_bytes()) == pending
        assert generate.call_args.kwargs == {'retrieval': {}}
        credentials.assert_not_called()
        client.assert_not_called()
        manifest['completion_profile'] = 'standard' if profile == 'reasoned_32k' else 'reasoned_32k'
        model.write_json(args.output / 'transport_prepare.json', manifest)
        with pytest.raises(ValueError, match='profile or token budget'):
            transport.checked_inputs(args)
