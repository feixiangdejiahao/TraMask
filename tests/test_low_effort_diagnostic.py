import json
from pathlib import Path

import pytest

from scripts import diagnose_low_effort_oracle_cache as diagnostic


@pytest.fixture
def baseline(tmp_path):
    base = tmp_path / 'baseline'
    requests, authorized = [], []
    for index in range(32):
        prepared = tmp_path / f'prepared_{index}'
        diagnostic.write(prepared / 'corpus.json', {'language': 'python'})
        diagnostic.write(prepared / 'case.json', {'id': 'toy'})
        thinking = 'enabled' if index < 21 else 'disabled'
        request = {'id': str(index), 'system': 'system', 'prompt': f'prompt {index}',
                   'source_prepared': str(prepared), 'thinking': thinking}
        original = base / 'original_requests' / f'request_{index:03d}.json'
        diagnostic.write(original, request)
        historical = tmp_path / 'historical' / f'request_{index:03d}'
        diagnostic.write(historical / 'request.json',
                         diagnostic.wire_payload(request, thinking=thinking))
        requests.append(dict(index=index, original_copy=str(original),
            original_copy_sha256=diagnostic.digest(original),
            prompt_system_sha256=diagnostic.prompt_identity(request),
            source_corpus=str(prepared / 'corpus.json'),
            source_corpus_sha256=diagnostic.digest(prepared / 'corpus.json'),
            historical_completion=str(historical),
            old_payload_sha256=diagnostic.digest(historical / 'request.json'),
            old_payload_thinking=thinking))
        authorized.append(dict(request_index=index, case='toy', trial='toy-trial',
            matches_authorized_registry={'trial': True}, case_path=str(prepared / 'case.json'),
            case_sha256=diagnostic.digest(prepared / 'case.json')))
    diagnostic.write(base / 'authorization_scope.json', dict(
        all_requests_within_existing_17_trials=True, requests=authorized,
        user_authorization_quote='test authorization',
        earlier_provider_authorization_quote='test provider'))
    diagnostic.write(base / 'protocol.json', dict(requests=requests,
        selected_without_outcomes=True, authorization_scope=dict(
            proof_sha256=diagnostic.digest(base / 'authorization_scope.json'))))
    diagnostic.write(base / 'protocol.seal.json', dict(sha256=diagnostic.digest(base / 'protocol.json')))
    return base


def test_prepare_preserves_entire_inventory_and_only_changes_parameters(baseline, tmp_path):
    output = tmp_path / 'low'
    result = diagnostic.prepare(baseline, output)
    assert result['requests'] == 32
    assert result['external_model_calls'] == 0
    assert result['strata'] == {'original_enabled': 21, 'original_disabled': 11}
    protocol = diagnostic.read(output / 'protocol.json')
    for index, row in enumerate(protocol['requests']):
        old = diagnostic.read(row['original_copy'])
        new = diagnostic.read(row['request'])
        assert row['index'] == index
        assert new == {**old, 'thinking': 'enabled', 'reasoning_effort': 'low'}
        assert diagnostic.prompt_identity(new) == row['prompt_system_sha256']
    assert protocol['concurrency'] == 1
    assert protocol['launch_window_seconds'] == 360
    assert protocol['retries'] == 0
    assert not (output / 'launch.json').exists()


def test_prepare_rejects_changed_corpus(baseline, tmp_path):
    original = diagnostic.read(baseline / 'protocol.json')['requests'][0]
    Path(original['source_corpus']).write_text('{"changed": true}')
    with pytest.raises(ValueError, match='source corpus changed'):
        diagnostic.prepare(baseline, tmp_path / 'low')


def test_run_records_strata_and_no_silent_retry(baseline, tmp_path, monkeypatch):
    from scripts import relation_search_semantics
    output = tmp_path / 'low'
    diagnostic.prepare(baseline, output)
    calls = []

    def complete(args):
        request = diagnostic.read(args.input)
        calls.append(request['id'])
        diagnostic.write(args.output / 'request.json', diagnostic.wire_payload(
            request, thinking='enabled', effort='low'))
        diagnostic.write(args.output / 'manifest.json', dict(status='complete',
            finish_reason='stop', usage={'completion_tokens': 4,
            'completion_tokens_details': {'reasoning_tokens': 2}}, seconds=0.1))
        (args.output / 'completion.txt').write_text('{"revisions": []}')
        diagnostic.write(args.output / 'validation.json', dict(revisions=[]))

    monkeypatch.setattr(relation_search_semantics, 'complete', complete)
    result = diagnostic.run(output)
    assert calls == [str(index) for index in range(32)]
    assert result['finished']
    assert result['counts']['json_valid'] == 32
    assert result['strata']['original_enabled']['counts']['launched'] == 21
    assert result['strata']['original_disabled']['counts']['launched'] == 11
    assert result['tokens']['completion_tokens_details.reasoning_tokens'] == 64
    assert all(row['expected_wire_payload_matches'] for row in result['records'])
    with pytest.raises(ValueError, match='not silently restarted'):
        diagnostic.run(output)
    assert len(calls) == 32


def test_run_detects_payload_drift_after_single_request(baseline, tmp_path, monkeypatch):
    from scripts import relation_search_semantics
    output = tmp_path / 'low'
    diagnostic.prepare(baseline, output)
    calls = []

    def complete(args):
        calls.append(str(args.input))
        diagnostic.write(args.output / 'request.json', {'wrong': True})

    monkeypatch.setattr(relation_search_semantics, 'complete', complete)
    with pytest.raises(ValueError, match='Wire payload differed'):
        diagnostic.run(output)
    assert len(calls) == 1
    assert not diagnostic.read(output / 'diagnostic.json')['finished']
