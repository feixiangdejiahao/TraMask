"""Provider wire compatibility and explicitly requested effort, with no network."""
import json

import httpx
import pytest

from relational_gap import provider


@pytest.fixture
def recorded_provider(tmp_path, monkeypatch):
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs/execution_policy.json').write_text(
        '{"allow_model_code_upload": true}')
    monkeypatch.setattr(provider, 'dotenv_values', lambda _: {
        'BASE_URL': 'https://example.invalid/v1', 'API_KEY': 'mock-secret'})
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={
            'model': 'deepseek-v4-flash',
            'choices': [{'message': {'content': '{"revisions": []}'},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 12, 'completion_tokens': 5}})

    real_client = httpx.Client
    monkeypatch.setattr(provider.httpx, 'Client', lambda **kwargs:
        real_client(transport=httpx.MockTransport(respond), **kwargs))
    return tmp_path, captured


@pytest.mark.parametrize('thinking', [None, 'enabled', 'disabled'])
def test_unspecified_effort_keeps_existing_payload(recorded_provider, thinking):
    root, requests = recorded_provider
    request = {'id': 'fixed-id', 'system': 'System', 'prompt': 'Prompt'}
    if thinking is not None:
        request['thinking'] = thinking
    record = provider.dispatch(request, root / 'output', root=root)
    expected = {
        'model': 'deepseek-v4-flash', 'temperature': 0, 'max_tokens': 16384,
        'messages': [{'role': 'system', 'content': 'System'},
                     {'role': 'user', 'content': 'Prompt'}],
        'response_format': {'type': 'json_object'}, 'stream': False,
        'thinking': {'type': thinking or 'disabled'}}
    assert requests[0].content == provider.encoded(expected)
    assert (root / 'output/request.json').read_bytes() == requests[0].content
    assert 'reasoning_effort' not in record
    assert record['status'] == 'complete'


@pytest.mark.parametrize('effort', ['low', 'high', 'max'])
def test_explicit_effort_reaches_wire_and_manifest(recorded_provider, effort):
    root, requests = recorded_provider
    request = {'id': 'fixed-id', 'system': 'System', 'prompt': 'Prompt',
               'thinking': 'enabled', 'reasoning_effort': effort}
    record = provider.dispatch(request, root / 'output', root=root)
    payload = json.loads(requests[0].content)
    assert payload['reasoning_effort'] == effort
    assert payload['thinking'] == {'type': 'enabled'}
    assert payload['model'] == 'deepseek-v4-flash'
    assert record['reasoning_effort'] == effort
    assert json.loads((root / 'output/manifest.json').read_text()) == record
    assert 'mock-secret' not in (root / 'output/manifest.json').read_text()
    assert 'example.invalid' not in (root / 'output/manifest.json').read_text()


@pytest.mark.parametrize('effort', [None, '', 'medium', 'none'])
def test_invalid_effort_rejected_before_network(recorded_provider, effort):
    root, requests = recorded_provider
    with pytest.raises(ValueError, match='Unsupported reasoning effort'):
        provider.dispatch({'id': 'x', 'system': 'S', 'prompt': 'P',
                           'reasoning_effort': effort}, root / 'output', root=root)
    assert requests == []
