import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from tramask_pilot import provider


REQUEST = {"id": "test-1", "system": "Return JSON.", "prompt": "审查 evidence"}


def fake_transport(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(provider, "connection", lambda root: ("https://provider.invalid/v1/chat/completions", "private-test-key"))
    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def reply(usage=None, content='{"decision":"yes"}'):
    value = {"model": "deepseek-returned-model", "choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    if usage is not None:
        value["usage"] = usage
    return httpx.Response(200, json=value)


def test_exact_settings_usage_settlement_and_idempotent_resume(tmp_path, monkeypatch):
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return reply({"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150})
    fake_transport(monkeypatch, handler)
    result = provider.call(tmp_path, tmp_path, tmp_path / "call", REQUEST)
    assert result["status"] == "complete"
    assert result["parsed"] == {"decision": "yes"}
    assert result["response_model"] == "deepseek-returned-model"
    assert received[0]["model"] == "deepseek-v4-flash"
    assert received[0]["temperature"] == 0
    assert received[0]["thinking"] == {"type": "disabled"}
    assert received[0]["max_tokens"] == 8192
    assert received[0]["response_format"] == {"type": "json_object"}
    assert result["budget"]["input_token_upper_bound"] == len(provider._encoded(received[0])) + provider.WRAPPER_TOKENS
    assert result["budget"]["charged_tokens"] == 150
    assert provider.BudgetLedger(tmp_path).snapshot()["committed_tokens"] == 150
    resumed = provider.call(tmp_path, tmp_path, tmp_path / "call", REQUEST)
    assert resumed["parsed"] == result["parsed"] and resumed["resumed"]
    assert len(received) == 1
    with pytest.raises(ValueError, match="out_dir_request_mismatch"):
        provider.call(tmp_path, tmp_path, tmp_path / "call", {**REQUEST, "prompt": "different"})


def test_missing_usage_charges_full_reservation_and_stops_next_call(tmp_path, monkeypatch):
    received = []
    def handler(request):
        received.append(request)
        return reply()
    fake_transport(monkeypatch, handler)
    first = provider.call(tmp_path, tmp_path, tmp_path / "first", REQUEST)
    amount = first["budget"]["reserved_tokens"]
    assert first["budget"]["charged_tokens"] == amount
    assert first["budget"]["accounting"] == "full_reservation_missing_usage"
    ledger = provider.BudgetLedger(tmp_path)
    ledger.reserve("calibration", "calibration", provider.BUDGET_TOKENS - amount, 0)
    denied = provider.call(tmp_path, tmp_path, tmp_path / "second", {**REQUEST, "id": "second"})
    assert denied["status"] == "budget_exceeded"
    assert denied["external_model_calls"] == 0
    assert len(received) == 1
    assert ledger.snapshot()["committed_tokens"] == provider.BUDGET_TOKENS


def test_failed_http_body_is_retained_and_split_credentials_are_redacted(tmp_path, monkeypatch):
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"error":"private-'
            yield b'test-key", "usage":{"total_tokens":7}, "model":"error-model"}'
    fake_transport(monkeypatch, lambda request: httpx.Response(429, stream=Chunks()))
    result = provider.call(tmp_path, tmp_path, tmp_path / "call", REQUEST)
    assert result["status"] == "error"
    assert result["http_status"] == 429
    assert result["error_code"] == "http_status_error"
    assert result["budget"]["charged_tokens"] == 7
    assert result["response_model"] == "error-model"
    assert json.loads((tmp_path / "call/response.body").read_text())["error"] == "[REDACTED]"
    assert all(b"private-test-key" not in path.read_bytes() for path in (tmp_path / "call").iterdir())


def test_transport_failure_is_recorded_once_and_costs_reservation(tmp_path, monkeypatch):
    attempts = []
    def handler(request):
        attempts.append(request)
        raise httpx.ReadTimeout("secret https://provider.invalid/v1/chat/completions private-test-key")
    fake_transport(monkeypatch, handler)
    first = provider.call(tmp_path, tmp_path, tmp_path / "call", REQUEST)
    second = provider.call(tmp_path, tmp_path, tmp_path / "call", REQUEST)
    assert first["error_type"] == "ReadTimeout" and second["resumed"]
    assert first["budget"]["charged_tokens"] == first["budget"]["reserved_tokens"]
    assert len(attempts) == 1
    assert b"private-test-key" not in (tmp_path / "call/manifest.json").read_bytes()


def test_reserved_call_survives_restart_without_redispatch(tmp_path, monkeypatch):
    fake_transport(monkeypatch, lambda request: pytest.fail("Must not dispatch an existing reservation"))
    # Simulate a process dying after reservation but before writing its manifest.
    original = provider._atomic_write
    def crash_manifest(path, value):
        if path.name == "manifest.json":
            raise KeyboardInterrupt()
        return original(path, value)
    monkeypatch.setattr(provider, "_atomic_write", crash_manifest)
    with pytest.raises(KeyboardInterrupt):
        provider.call(tmp_path, tmp_path, tmp_path / "call", REQUEST)
    monkeypatch.setattr(provider, "_atomic_write", original)
    before = provider.BudgetLedger(tmp_path).snapshot()["committed_tokens"]
    resumed = provider.call(tmp_path, tmp_path, tmp_path / "call", REQUEST)
    assert resumed["status"] == "interrupted"
    assert resumed["budget"]["reserved_tokens"] == before > 0
    assert provider.BudgetLedger(tmp_path).snapshot()["committed_tokens"] == before


def test_concurrent_reservations_cannot_overspend_and_settlement_is_idempotent(tmp_path):
    def reserve(index):
        return provider.BudgetLedger(tmp_path).reserve(str(index), str(index), 2_000_000, 500_000)
    with ThreadPoolExecutor(max_workers=8) as pool:
        reservations = list(pool.map(reserve, range(8)))
    assert sum(fresh for _, fresh in reservations) == 4
    ledger = provider.BudgetLedger(tmp_path)
    assert ledger.snapshot()["committed_tokens"] == provider.BUDGET_TOKENS
    key = next(iter(ledger.snapshot()["calls"]))
    assert ledger.settle(key, {"total_tokens": 100})["charged_tokens"] == 100
    assert ledger.settle(key, None)["charged_tokens"] == 100
    assert ledger.snapshot()["committed_tokens"] == 7_500_100


@pytest.mark.parametrize("usage, expected", [(None, None), ({"prompt_tokens": 5}, None),
    ({"total_tokens": -1}, None), ({"total_tokens": True}, None),
    ({"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 8}, 10)])
def test_usage_is_complete_and_conservative(usage, expected):
    assert provider._usage_tokens(usage) == expected
