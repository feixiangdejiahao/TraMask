"""Enforce small semantic-query budgets on the actual wire, without networking."""
import json

import httpx
import pytest

from relational_gap import provider


@pytest.mark.parametrize('limit', [1, 512, 2048, 16384])
def test_explicit_budget_controls_wire_and_manifest(tmp_path, monkeypatch, limit):
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs/execution_policy.json').write_text('{"allow_model_code_upload":true}')
    monkeypatch.setattr(provider, 'dotenv_values', lambda _: {
        'BASE_URL': 'https://budget.invalid/v1', 'API_KEY': 'test-only'})
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            'choices': [{'message': {'content': '{"status":"unknown"}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 7, 'completion_tokens': 3}})

    client = httpx.Client
    monkeypatch.setattr(provider.httpx, 'Client', lambda **kwargs:
        client(transport=httpx.MockTransport(respond), **kwargs))
    record = provider.dispatch(dict(id='budget', system='S', prompt='P', max_tokens=limit),
                               tmp_path / 'output', root=tmp_path)
    assert len(seen) == 1
    assert seen[0]['max_tokens'] == limit
    assert record['max_output_tokens'] == limit
    assert record['usage'] == {'prompt_tokens': 7, 'completion_tokens': 3}


@pytest.mark.parametrize('limit', [True, 0, -1, 16385, 512.0, '512', None])
def test_invalid_budget_never_reads_credentials_or_contacts_provider(tmp_path, monkeypatch, limit):
    monkeypatch.setattr(provider, 'dotenv_values', lambda _: pytest.fail('read credentials'))
    monkeypatch.setattr(provider.httpx, 'Client', lambda **_: pytest.fail('contacted provider'))
    with pytest.raises(ValueError, match='output token budget'):
        provider.dispatch(dict(id='budget', system='S', prompt='P', max_tokens=limit),
                          tmp_path / 'output', root=tmp_path)
