"""Invented fixtures only; network is blocked by tests/conftest.py."""
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from prototypes import llm_baseline as baseline
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from scripts import run_llm_generation_baseline as cli


def toy(tmp_path, code="def test_parent():\n    assert run(1) == 1\n", language="python", path="test_toy.py"):
    repository = tmp_path / "invented"
    repository.mkdir(parents=True, exist_ok=True)
    (repository / path).write_text(code)
    corpus = build_corpus(repository, language)
    for rank, parent in enumerate(corpus["tests"].values(), 1):
        parent["retrieval_rank"] = rank
    original_evidence = {"issue": "Combine the source behaviors", "source_tests": {},
                         "production_context": {"interpretation": "Possibly buggy", "files": []},
                         "rules": ["old construction rule must not be uploaded"]}
    evidence = baseline.retrieval_evidence(corpus, original_evidence)
    return corpus, baseline.presentation(corpus, evidence), repository


def response_content(identifier, body):
    return json.dumps({"tests": [{"source_test_id": identifier, "body": body}]})


def provider(monkeypatch, tmp_path, content, *, status=200, raw_bytes=None):
    root = tmp_path / "fake_provider_root"
    (root / "configs").mkdir(parents=True)
    (root / "configs/execution_policy.json").write_text('{"allow_model_code_upload":true}')
    (root / "results").mkdir()
    (root / "results/api_route.json").write_text('{"prefix":"gateway/"}')
    monkeypatch.setattr(baseline, "ROOT", root)
    monkeypatch.setattr(baseline, "dotenv_values", lambda path: {
        "BASE_URL": "https://unit.invalid/v1", "API_KEY": "mock-only-secret"})
    calls = []

    def handler(request):
        calls.append(request)
        if raw_bytes is not None:
            return httpx.Response(status, content=raw_bytes)
        return httpx.Response(status, json={"model": baseline.MODEL, "usage": {"total_tokens": 11},
                                            "choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

    original_client = httpx.Client
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(baseline.httpx, "Client", client)
    return calls, options


def test_retrieval_parents_do_not_depend_on_old_candidate_coverage(tmp_path):
    corpus, shown, _ = toy(tmp_path, "def test_a():\n    assert run(1) == 1\ndef test_b():\n    assert run(2) == 2\n")
    ids = list(corpus["tests"])
    corpus["tests"][ids[0]]["retrieval_rank"] = 11
    evidence = baseline.retrieval_evidence(corpus, {"source_tests": {}, "candidates": ["hidden"], "issue": "contract"})
    shown = baseline.presentation(corpus, evidence)
    assert set(shown["source_tests"]) == {ids[1]}
    assert "candidates" not in shown and "rules" not in shown
    with pytest.raises(ValueError, match="non-visible"):
        baseline.parse_tests(response_content(ids[0], "assert run(3) == 3"), shown)


def test_request_parent_order_survives_canonical_artifact_round_trip(tmp_path):
    corpus, shown, _ = toy(tmp_path, "def test_a():\n    assert run(1) == 1\ndef test_b():\n    assert run(2) == 2\n")
    ids = sorted(corpus["tests"], reverse=True)
    for rank, identifier in enumerate(ids, 1):
        corpus["tests"][identifier]["retrieval_rank"] = rank
    shown = baseline.presentation(corpus, baseline.retrieval_evidence(corpus, {}))
    payload = baseline.request_payload(json.loads(baseline.encoded(shown)))
    assert list(json.loads(payload["messages"][1]["content"])["source_tests"]) == ids


@pytest.mark.parametrize("prefix", ["# independent comment\n    ", "\n    ", "# first\n    # second\n    "])
def test_python_leading_suite_comments_are_preserved_without_body_escape(tmp_path, prefix):
    corpus, shown, _ = toy(tmp_path)
    identifier = next(iter(shown["source_tests"]))
    body = prefix + "assert run(2) == 2"
    generated = baseline.materialize(response_content(identifier, body), corpus, shown)
    assert generated["counts"]["candidates"] == 1
    assert generated["candidates"][0]["edits"][0]["after"] == body
    escaped = "# comment\n    assert run(2) == 2\nassert run(3) == 3"
    assert baseline.validate_body(corpus, identifier, escaped)["status"] == "unsupported"


@pytest.mark.parametrize("value", [
    [], {"tests": [], "oracle_rule": "invented"}, {"tests": "not a list"},
    {"tests": [{"source_test_id": "unknown", "body": "assert True"}]},
    {"tests": [{"source_test_id": True, "body": "assert True"}]},
    {"tests": [{"source_test_id": "parent", "body": ""}]},
    {"tests": [{"source_test_id": "parent", "body": 7}]},
    {"tests": [{"source_test_id": "parent", "body": "x", "reason": "extra"}]},
    {"tests": [{"source_test_id": "parent", "body": "x"}] * 2},
    {"tests": [{"source_test_id": "parent", "body": str(i)} for i in range(4)]},
])
def test_minimal_finite_output_schema(value):
    with pytest.raises(ValueError):
        baseline.parse_tests(json.dumps(value), {"source_tests": {"parent": {}}})


@pytest.mark.parametrize("text", ['```json\n{"tests":[]}\n```', '{"tests":[],"tests":[]}',
                                  '{"tests":[{"source_test_id":"parent","body":"a","body":"b"}]}'])
def test_no_json_fence_or_duplicate_key_repairs(text):
    with pytest.raises(ValueError):
        baseline.parse_tests(text, {"source_tests": {"parent": {}}})


def test_finite_utf8_body_and_request_bytes(monkeypatch):
    shown = {"source_tests": {"parent": {}}}
    monkeypatch.setattr(baseline, "MAX_BODY_BYTES", 5)
    with pytest.raises(ValueError, match="byte limit"):
        baseline.parse_tests(response_content("parent", "猫猫"), shown)
    monkeypatch.setattr(baseline, "MAX_REQUEST_BYTES", 1)
    with pytest.raises(ValueError, match="no truncation"):
        baseline.request_payload(shown)


@pytest.mark.parametrize("code,language,path,body", [
    ("class TestScope:\n    def test_parent(self):\n        assert run(1) == 1\n", "python", "test_toy.py",
     "value = run(2)\n        assert value == 2"),
    ('package toy\nimport "testing"\nfunc TestParent(t *testing.T) { if run(1) != 1 { t.Fatal("bad") } }\n',
     "go", "toy_test.go", '{ if run(2) != 2 { t.Fatal("different") } }'),
    ("describe('outer', () => { test('parent', () => { expect(run(1)).toBe(1); }); });\n",
     "typescript", "toy.test.ts", "{ const value = run(2); expect(value).toBe(2); }"),
    ("test('parent', () => expect(run(1)).toBe(1));\n", "typescript", "toy.test.ts", "expect(run(2)).toBe(2)"),
])
def test_exact_body_replacements_emit_with_original_parent_control(tmp_path, code, language, path, body):
    corpus, shown, source = toy(tmp_path, code, language, path)
    identifier = next(iter(shown["source_tests"]))
    generated = baseline.materialize(response_content(identifier, body), corpus, shown)
    assert generated["counts"] == {"proposed": 1, "candidates": 1, "unsupported": 0}
    candidate = generated["candidates"][0]
    assert candidate["edits"][0]["after"] == body
    assert candidate["source_test_ids"] == [identifier] and candidate["imports"] == []
    emitted = emit(corpus, generated["candidates"])
    assert len(emitted["obligations"]) == len(emitted["controls"]) == 1
    assert emitted["obligations"][0]["control_ids"] == [emitted["controls"][0]["id"]]
    assert (source / path).read_text() == code
    if language == "typescript" and "describe" in code:
        assert emitted["obligations"][0]["id"].startswith("outer gc_")


@pytest.mark.parametrize("body,reason", [
    ("assert True\nescaped = 5", "complete_parent_body"),
    ("assert True\n\ndef test_escape():\n    assert True", "complete_parent_body"),
    ("assert run(2) == 2\n", "complete_parent_body"),
    ("import invented\n    assert invented.run(2) == 2", "imports_or_scope"),
    ("global value\n    assert run(2) == 2", "imports_or_scope"),
    ("assert value == 2\n    value = run(2)", "lexical_or_local_arity"),
    ("assert run(", "parse_error"),
])
def test_unsupported_body_code_is_recorded_without_repair(tmp_path, body, reason):
    corpus, shown, _ = toy(tmp_path)
    identifier = next(iter(shown["source_tests"]))
    result = baseline.materialize(response_content(identifier, body), corpus, shown)
    assert result["candidates"] == []
    assert reason in result["unsupported"][0]["reason"]


def test_body_local_imports_must_remain_exact(tmp_path):
    corpus, shown, _ = toy(tmp_path, "def test_parent():\n    import math\n    assert math.floor(1.2) == 1\n")
    identifier = next(iter(shown["source_tests"]))
    retained = "import math\n    assert math.floor(2.7) == 2"
    assert baseline.validate_body(corpus, identifier, retained)["status"] == "supported"
    assert baseline.validate_body(corpus, identifier, "assert True")["status"] == "unsupported"


def test_unknown_external_bindings_are_explicit_not_oracle_proofs(tmp_path):
    corpus, shown, _ = toy(tmp_path)
    identifier = next(iter(shown["source_tests"]))
    result = baseline.materialize(response_content(identifier, "assert run(2) == 2"), corpus, shown)
    assert result["validation"][0]["lexical"]["status"] == "unknown"
    assert "independent audit" in result["semantic_status"]


def test_one_request_exact_model_endpoint_bytes_and_no_retry(monkeypatch, tmp_path):
    corpus, shown, _ = toy(tmp_path)
    identifier = next(iter(shown["source_tests"]))
    calls, options = provider(monkeypatch, tmp_path, response_content(identifier, "assert run(2) == 2"))
    output = tmp_path / "cache"
    manifest = baseline.request_generation(shown, corpus, output)
    assert manifest["valid"] and manifest["external_model_calls"] == len(calls) == 1
    assert str(calls[0].url) == "https://unit.invalid/v1/gateway/chat/completions"
    assert manifest["provider_endpoint_sha256"] == baseline.digest(str(calls[0].url).encode())
    assert calls[0].content == (output / "request.json").read_bytes()
    payload = json.loads(calls[0].content)
    assert payload["model"] == "deepseek-v4-flash" and payload["max_tokens"] == 10000
    assert payload["tool_choice"] == "none" and "tools" not in payload
    assert payload["thinking"] == {"type": "disabled"} and payload["reasoning_effort"] == "none"
    assert options[0]["follow_redirects"] is False
    assert baseline.load_generation(output, shown, corpus)[1]["counts"]["candidates"] == 1
    for path in output.iterdir():
        assert "mock-only-secret" not in path.read_text() and "https://unit.invalid" not in path.read_text()
    with pytest.raises(FileExistsError):
        baseline.request_generation(shown, corpus, output)
    assert len(calls) == 1


@pytest.mark.parametrize("filename", ["request.json", "input.json", "response.json", "generated.json"])
def test_changed_cached_bytes_cannot_load(monkeypatch, tmp_path, filename):
    corpus, shown, _ = toy(tmp_path)
    identifier = next(iter(shown["source_tests"]))
    provider(monkeypatch, tmp_path, response_content(identifier, "assert run(2) == 2"))
    output = tmp_path / "cache"
    baseline.request_generation(shown, corpus, output)
    path = output / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        baseline.load_generation(output, shown, corpus)


@pytest.mark.parametrize("content,status,raw,reason", [
    ("not JSON", 200, None, "invalid_generation_output"),
    (None, 200, None, "invalid_generation_output"),
    (None, 302, b"redirect", "http_status_error"),
    (None, 200, b"not envelope JSON", "invalid_response_envelope"),
])
def test_failed_one_shot_requests_persist_response_and_failure(monkeypatch, tmp_path, content, status, raw, reason):
    corpus, shown, _ = toy(tmp_path)
    calls, _ = provider(monkeypatch, tmp_path, content, status=status, raw_bytes=raw)
    output = tmp_path / "cache"
    manifest = baseline.request_generation(shown, corpus, output)
    assert manifest["valid"] is False and manifest["failure_kind"] == reason
    assert manifest["external_model_calls"] == len(calls) == 1
    assert (output / "response.json").exists() and (output / "manifest.json").exists()
    assert not (output / "generated.json").exists()


def test_response_bytes_are_bounded(monkeypatch, tmp_path):
    corpus, shown, _ = toy(tmp_path)
    provider(monkeypatch, tmp_path, None, raw_bytes=b"x" * 200)
    monkeypatch.setattr(baseline, "MAX_RESPONSE_BYTES", 100)
    output = tmp_path / "cache"
    manifest = baseline.request_generation(shown, corpus, output)
    assert manifest["failure_kind"] == "response_byte_limit"
    assert (output / "response.json").stat().st_size == 100


def staged_toy(tmp_path, code="def test_parent():\n    assert run(1) == 1\n"):
    corpus, shown, repository = toy(tmp_path, code)
    source = tmp_path / "source_prepared"
    source.mkdir()
    data = {"case.json": {"id": "invented", "language": "python", "repository": str(repository),
                          "harness": {"command": "true", "report_format": "jsonl", "report_path": "stdout.txt"}},
            "retrieval.json": {"selected_tests": []}, "corpus.json": corpus,
            "evidence.json": {"issue": "Combine source behaviors", "source_tests": {}, "production_context": {}}}
    for name, value in data.items():
        cli.write_json(source / name, value)
    cli.write_json(source / "prepare.json", {"case_id": "invented", "status": "complete",
                                            "files_sha256": {name: cli.driver.digest(source / name) for name in data}})
    args = SimpleNamespace(case="invented", source_prepared=source, output=tmp_path / "baseline", rerun_id="r1", timeout=15)
    return corpus, shown, args


def test_cli_rounds_freeze_original_controls_without_subject_execution(monkeypatch, tmp_path):
    corpus, shown, args = staged_toy(tmp_path)
    identifier = next(iter(shown["source_tests"]))
    calls, _ = provider(monkeypatch, tmp_path, response_content(identifier, "assert run(2) == 2"))
    cli.prepare(args)
    assert calls == []
    cli.generate(args)
    assert (args.output / "request_template.json").read_bytes() == calls[0].content
    frozen = cli.freeze(args)
    assert frozen["generated"] == frozen["controls"] == 1
    first = args.output / "rounds/r1"
    manifest = json.loads((first / "frozen/direct/manifest.json").read_bytes())
    assert manifest["metadata"]["algorithm"] == "independent_llm_generation_baseline"
    assert manifest["metadata"]["generation_round"] == "r1"
    with pytest.raises(FileExistsError):
        cli.generate(args)
    args.rerun_id = "r2"
    cli.generate(args)
    assert len(calls) == 2 and calls[0].content == calls[1].content
    second = args.output / "rounds/r2"
    first.rename(args.output / "rounds/temporary")
    second.rename(first)
    (args.output / "rounds/temporary").rename(second)
    with pytest.raises(ValueError, match="declared round"):
        cli.freeze(args)


def test_cli_freeze_preserves_resolved_call_signatures_after_json_round_trip(monkeypatch, tmp_path):
    code = "def run(value, scale=1):\n    return value * scale\n\ndef test_parent():\n    assert run(1) == 1\n"
    corpus, shown, args = staged_toy(tmp_path, code)
    identifier = next(iter(shown["source_tests"]))
    provider(monkeypatch, tmp_path, response_content(identifier, "assert run(2, scale=2) == 4"))
    cli.prepare(args)
    cli.generate(args)
    cached = json.loads((args.output / "rounds/r1/generated.json").read_bytes())
    assert cached["validation"][0]["lexical"]["calls"][0]["signature"]["parameters"]
    frozen = cli.freeze(args)
    assert frozen["generated"] == frozen["controls"] == 1


def test_cli_invalid_generation_remains_explicit_and_freezes_empty(monkeypatch, tmp_path):
    _, _, args = staged_toy(tmp_path)
    calls, _ = provider(monkeypatch, tmp_path, "malformed")
    cli.prepare(args)
    generated = cli.generate(args)
    assert generated["status"] == "invalid" and len(calls) == 1
    assert generated["counts"]["proposed"] is None
    frozen = cli.freeze(args)
    assert frozen["generated"] == frozen["controls"] == 0
    manifest = json.loads((args.output / "rounds/r1/frozen/direct/manifest.json").read_bytes())
    assert manifest["metadata"]["generation_valid"] is False
    assert manifest["metadata"]["no_executable_tests"] is True
