"""Finite-ID admission and freeze boundaries; all network traffic is mocked."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from generic_composition import gate


CANDIDATES = [
    {'id': 'candidate-b', 'edits': [{'before': 'f(2)', 'after': 'wrap(f(2))'}]},
    {'id': 'candidate-a', 'edits': [{'before': 'f(3)', 'after': 'wrap(f(3))'}]},
]


@pytest.mark.parametrize('content', [
    '{"accepted": ["unknown"]}',
    '{"accepted": ["candidate-a", "candidate-a"]}',
    '{"accepted": [true]}',
    '{"accepted": "candidate-a"}',
    '{"accepted": [], "code": "assert True"}',
    '["candidate-a"]',
    '```json\n{"accepted": []}\n```',
])
def test_only_unique_known_ids_are_allowed(content):
    with pytest.raises(ValueError):
        gate.parse_selection(content, CANDIDATES)


def test_selection_is_sorted_and_empty_selection_is_valid():
    assert gate.parse_selection('{"accepted": []}', CANDIDATES) == []
    assert gate.parse_selection('{"accepted": ["candidate-b", "candidate-a"]}', CANDIDATES) == [
        'candidate-a', 'candidate-b']


def fake_provider(monkeypatch, tmp_path, response=None, *, error=None):
    (tmp_path / 'configs').mkdir(exist_ok=True)
    (tmp_path / 'configs/execution_policy.json').write_text('{"allow_model_code_upload": true}')
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    monkeypatch.setattr(gate, 'dotenv_values', lambda _: {
        'BASE_URL': 'https://unit.invalid/v1', 'API_KEY': 'unit-test-only-placeholder'})
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            if error is not None:
                raise error
            return response

    class Client:
        def __init__(self, **kwargs):
            self.options = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def post(self, url, **kwargs):
            calls.append({'url': url, 'options': self.options, **kwargs})
            return Response()

    monkeypatch.setattr(gate.httpx, 'Client', Client)
    return calls


def provider_response(content='{"accepted": ["candidate-a"]}'):
    return {'id': 'unit-response', 'model': 'unit-model', 'usage': {'total_tokens': 7},
            'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}


def cached_admission(monkeypatch, tmp_path):
    calls = fake_provider(monkeypatch, tmp_path, provider_response())
    output = tmp_path / 'cache'
    result = gate.request_admission({'issue': 'unit requirement'}, CANDIDATES, output)
    assert result['valid'] and len(calls) == 1
    return output, calls


def test_one_request_contains_fixed_proposals_and_no_credentials_in_artifacts(monkeypatch, tmp_path):
    output, calls = cached_admission(monkeypatch, tmp_path)
    payload = calls[0]['json']
    sent = json.loads(payload['messages'][1]['content'])
    assert sent == {'evidence': {'issue': 'unit requirement'}, 'candidates': CANDIDATES}
    assert 'tools' not in payload
    assert calls[0]['options']['follow_redirects'] is False
    assert gate.load_admission(output, CANDIDATES)['accepted'] == ['candidate-a']
    assert all('unit-test-only-placeholder' not in p.read_text() for p in output.iterdir())
    with pytest.raises(FileExistsError):
        gate.request_admission({}, CANDIDATES, output)
    assert len(calls) == 1


@pytest.mark.parametrize('filename', ['request.json', 'response.json', 'candidates.json'])
def test_cached_request_response_and_candidate_byte_changes_are_rejected(monkeypatch, tmp_path, filename):
    output, _ = cached_admission(monkeypatch, tmp_path)
    path = output / filename
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError):
        gate.load_admission(output, CANDIDATES)


def test_changed_candidate_code_cannot_reuse_admission(monkeypatch, tmp_path):
    output, _ = cached_admission(monkeypatch, tmp_path)
    changed = json.loads(json.dumps(CANDIDATES))
    changed[0]['edits'][0]['after'] = 'other(f(2))'
    with pytest.raises(ValueError, match='candidate'):
        gate.load_admission(output, changed)


def test_cached_accepted_ids_cannot_be_changed_in_manifest(monkeypatch, tmp_path):
    output, _ = cached_admission(monkeypatch, tmp_path)
    path = output / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['accepted'] = ['candidate-b']
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='IDs differ'):
        gate.load_admission(output, CANDIDATES)


def test_response_cannot_supply_or_execute_replacement_code(monkeypatch, tmp_path):
    marker = tmp_path / 'model_code_executed'
    content = json.dumps({'accepted': ['candidate-a'],
                          'code': f'open({str(marker)!r}, "w").write("executed")'})
    calls = fake_provider(monkeypatch, tmp_path, provider_response(content))
    result = gate.request_admission({}, CANDIDATES, tmp_path / 'cache')
    assert not result['valid'] and len(calls) == 1
    assert not marker.exists()
    assert {p.name for p in (tmp_path / 'cache').iterdir()} == {
        'request.json', 'candidates.json', 'response.json', 'manifest.json'}


@pytest.mark.parametrize('response,error', [
    (None, ValueError('unit malformed JSON')),
    (None, None),
    ([], None),
    ({'choices': []}, None),
    ({'id': 'unit-missing-choices'}, None),
    ({'choices': [{'message': None}]}, None),
])
def test_dispatched_malformed_responses_still_record_one_call(monkeypatch, tmp_path, response, error):
    calls = fake_provider(monkeypatch, tmp_path, response, error=error)
    output = tmp_path / 'cache'
    result = gate.request_admission({}, CANDIDATES, output)
    saved = json.loads((output / 'manifest.json').read_text())
    assert not result['valid'] and not saved['valid']
    assert result['external_model_calls'] == saved['external_model_calls'] == len(calls) == 1


def experiment_module():
    path = Path(__file__).resolve().parents[1] / 'scripts/run_generic_experiment.py'
    spec = importlib.util.spec_from_file_location('unit_generic_experiment', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def staged_inputs(monkeypatch, tmp_path, candidates=CANDIDATES):
    module = experiment_module()
    output = tmp_path / 'stage'
    output.mkdir()
    artifacts = {'case.json': {'id': 'unit'}, 'evidence.json': {'issue': 'unit requirement'},
                 'candidates.json': candidates}
    for name, value in artifacts.items():
        module.write_json(output / name, value)
    hashes = {'unit.py': 'synthetic-code-hash'}
    monkeypatch.setattr(module, 'algorithm_hashes', lambda: hashes)
    module.write_json(output / 'prepare.json', {
        'case_id': 'unit', 'status': 'complete', 'algorithm_sha256': hashes,
        'declared_admission_rounds': ['r1', 'r2'], 'expected_model': 'gpt-6-astra',
        'budget': {'model_calls_per_round': 1, 'max_output_tokens_per_round': 10000},
        'files_sha256': {name: module.digest(output / name) for name in artifacts}})
    args = SimpleNamespace(output=output, case='unit', cache_output=None, rerun_id='r1',
                           max_tokens=10000, model='gpt-6-astra')
    return module, args


def test_rounds_reuse_frozen_inputs_without_generation_or_execution_feedback(monkeypatch, tmp_path):
    module, args = staged_inputs(monkeypatch, tmp_path)
    import generic_composition.corpus
    import generic_composition.engine

    def prohibited(*a, **kw):
        raise AssertionError('admission must not regenerate')
    monkeypatch.setattr(generic_composition.corpus, 'build_corpus', prohibited)
    monkeypatch.setattr(generic_composition.engine, 'generate', prohibited)
    calls = []

    def admit(evidence, candidates, output, **kwargs):
        calls.append((evidence, candidates, kwargs))
        return {'valid': True, 'accepted': [], 'external_model_calls': 1}
    monkeypatch.setattr(gate, 'request_admission', admit)
    module.admit(args)
    with pytest.raises(FileExistsError):
        module.admit(args)
    (args.output / 'execution').mkdir()
    (args.output / 'execution' / 'evaluation.json').write_text('{"forbidden_feedback": true}')
    args.rerun_id = 'r2'
    module.admit(args)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert 'forbidden_feedback' not in json.dumps(calls)


def test_failed_round_is_not_automatically_retried(monkeypatch, tmp_path):
    module, args = staged_inputs(monkeypatch, tmp_path)
    calls = []

    def fail(*a, **kw):
        calls.append(True)
        raise RuntimeError('unit transport failure')
    monkeypatch.setattr(gate, 'request_admission', fail)
    with pytest.raises(RuntimeError):
        module.admit(args)
    with pytest.raises(FileExistsError):
        module.admit(args)
    assert len(calls) == 1
    marker = json.loads((args.output / 'admission/r1.json').read_text())
    assert marker['status'] == 'failed'


@pytest.mark.parametrize('name,value', [
    ('rerun_id', 'r3'), ('model', 'different-model'), ('max_tokens', 5000),
])
def test_declared_round_model_and_budget_cannot_drift(monkeypatch, tmp_path, name, value):
    module, args = staged_inputs(monkeypatch, tmp_path)
    setattr(args, name, value)

    def fail(*a, **kw):
        raise AssertionError('Invalid round must fail before provider dispatch')
    monkeypatch.setattr(gate, 'request_admission', fail)
    with pytest.raises(ValueError):
        module.admit(args)


def test_empty_candidate_set_needs_no_model_call(monkeypatch, tmp_path):
    module, args = staged_inputs(monkeypatch, tmp_path, [])

    def fail(*a, **kw):
        raise AssertionError('Empty candidates must not contact a provider')
    monkeypatch.setattr(gate, 'request_admission', fail)
    result = module.admit(args)
    assert result['status'] == 'no_candidates'
    marker = json.loads((args.output / 'admission/r1.json').read_text())
    assert marker['external_model_calls'] == 0
