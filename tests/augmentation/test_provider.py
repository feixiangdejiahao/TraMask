import json
from pathlib import Path

import httpx

from augmentation import provider


def test_explicit_model_is_sent_and_actual_model_is_recorded(tmp_path, monkeypatch):
    received = []
    def handle(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "deepseek-flash", "choices": [{"finish_reason": "stop", "message": {"content": '{"decision":"unknown"}'}}]})
    client = httpx.Client
    monkeypatch.setattr(provider, "connection", lambda root: ("https://provider.invalid/v1/chat/completions", "test-key"))
    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    result = provider.dispatch({"id": "test", "system": "system", "prompt": "evidence"}, tmp_path / "call", root=Path.cwd())
    assert received[0]["model"] == "deepseek-v4-flash"
    assert result["response_model"] == "deepseek-flash"
    assert result["status"] == "complete"
    assert "test-key" not in (tmp_path / "call/manifest.json").read_text()
