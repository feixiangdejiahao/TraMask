"""The protocol wrapper changes two request fields and preserves one-shot checks."""
import json

import pytest

from experimental import llm_baseline as baseline
from scripts import run_llm_generation_baseline as original
from scripts import run_llm_thinking_baseline as thinking
from test_llm_generation_baseline import provider, response_content, staged_toy


def test_exactly_two_request_fields_change_and_defaults_restore():
    shown = {"source_tests": {}, "issue": "invented"}
    expected = baseline.request_payload(shown)
    hashes = original.baseline_hashes()
    with thinking.protocol_context():
        actual = baseline.request_payload(shown)
        assert {key for key in expected if expected[key] != actual[key]} == {"thinking", "reasoning_effort"}
        assert actual["thinking"] == {"type": "enabled"} and actual["reasoning_effort"] == "low"
        assert actual["model"] == "deepseek-v4-flash" and actual["max_tokens"] == 10000
        assert set(original.baseline_hashes()) == {*hashes, "scripts/run_llm_thinking_baseline.py"}
    assert baseline.request_payload(shown) == expected and original.baseline_hashes() == hashes


def test_protocol_is_snapshotted_and_round_trip_freezes(monkeypatch, tmp_path):
    _, shown, args = staged_toy(tmp_path)
    identifier = next(iter(shown["source_tests"]))
    calls, _ = provider(monkeypatch, tmp_path, response_content(identifier, "assert run(2) == 2"))
    thinking.prepare(args)
    manifest = json.loads((args.output / "baseline_prepare.json").read_bytes())
    assert manifest["request_protocol"] == thinking.PROTOCOL
    wrapper = "scripts/run_llm_thinking_baseline.py"
    assert manifest["baseline_algorithm_sha256"][wrapper] == original.driver.digest(thinking.ROOT / wrapper)
    assert (args.output / "algorithm_snapshot" / wrapper).read_bytes() == (thinking.ROOT / wrapper).read_bytes()
    with pytest.raises(ValueError, match="Algorithm changed"):
        original.generate(args)
    thinking.generate(args)
    assert len(calls) == 1
    request = json.loads(calls[0].content)
    assert request["thinking"] == {"type": "enabled"} and request["reasoning_effort"] == "low"
    assert thinking.freeze(args)["generated"] == 1
    round_output = args.output / "rounds/r1"
    assert json.loads((round_output / "prepare.json").read_bytes())["request_protocol"] == thinking.PROTOCOL
    assert (round_output / "algorithm_snapshot" / wrapper).exists()
    with pytest.raises(FileExistsError):
        thinking.generate(args)
    assert len(calls) == 1


def test_default_protocol_rejects_thinking_cache_replay(monkeypatch, tmp_path):
    corpus, shown, args = staged_toy(tmp_path)
    identifier = next(iter(shown["source_tests"]))
    provider(monkeypatch, tmp_path, response_content(identifier, "assert run(2) == 2"))
    thinking.prepare(args)
    thinking.generate(args)
    shown = json.loads((args.output / "input.json").read_bytes())
    cache = args.output / "rounds/r1/generation"
    with pytest.raises(ValueError, match="different frozen evidence or protocol"):
        baseline.load_generation(cache, shown, corpus)
    with thinking.protocol_context():
        assert baseline.load_generation(cache, shown, corpus)[0]["valid"] is True
