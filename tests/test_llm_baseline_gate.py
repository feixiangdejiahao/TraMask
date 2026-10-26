"""Postgeneration gate uses invented frozen inputs and mocked transport only."""
import json
from types import SimpleNamespace

import pytest

from prototypes import llm_baseline
from generic_composition import gate
from generic_composition.corpus import build_corpus
from scripts import run_llm_baseline_gate as postgate


def frozen_round(tmp_path, *, empty=False):
    repository = tmp_path / "invented_subject"
    repository.mkdir()
    (repository / "test_toy.py").write_text("def test_parent():\n    assert run(1) == 1\n")
    corpus = build_corpus(repository, "python")
    identifier = next(iter(corpus["tests"]))
    corpus["tests"][identifier]["retrieval_rank"] = 1
    evidence = llm_baseline.retrieval_evidence(corpus, {"issue": "Combine source behaviors", "production_context": {}})
    shown = llm_baseline.presentation(corpus, evidence)
    content = json.dumps({"tests": [] if empty else [{"source_test_id": identifier, "body": "assert run(2) == 2"}]})
    generated = llm_baseline.materialize(content, corpus, shown)
    source = tmp_path / "original_r1"
    source.mkdir()
    data = {"case.json": {"id": "toy", "language": "python", "repository": str(repository),
                          "harness": {"command": "true", "report_format": "jsonl", "report_path": "stdout.txt"}},
            "retrieval.json": {"selected_tests": []}, "corpus.json": corpus, "evidence.json": evidence,
            "generated.json": generated, "candidates.json": generated["candidates"]}
    for name, value in data.items():
        postgate.driver.write_json(source / name, value)
    original = {"case_id": "toy", "status": "complete", "generator": "independent_llm_baseline",
                "generation_round": "r1", "corpus_coverage": corpus["coverage"],
                "baseline_algorithm_sha256": {"old_snapshot.py": "original-algorithm-hash"},
                "files_sha256": {name: postgate.driver.digest(source / name) for name in data}}
    postgate.driver.write_json(source / "prepare.json", original)
    artifact = source / "frozen/direct/manifest.json"
    postgate.driver.write_json(artifact, {"report": {"format": "jsonl", "path": "stdout.txt"}, "files": [],
                                        "metadata": {"generation_round": "r1",
                                                     "prepare_sha256": postgate.driver.digest(source / "prepare.json")}})
    postgate.driver.write_json(source / "freezes/direct.json", {"artifact_sha256": postgate.driver.digest(artifact)})
    # These files must never be read or uploaded by the postgate adapter.
    postgate.driver.write_json(source / "audit.json", {"secret_audit_label": "MUST_NOT_APPEAR"})
    postgate.driver.write_json(source / "execution/result.json", {"outcome": "MUST_NOT_APPEAR"})
    return SimpleNamespace(case="toy", source_round=source, output=tmp_path / "postgate", timeout=15)


def provider(monkeypatch, tmp_path, content='{"accepted":["c0"]}'):
    root = tmp_path / "fake_provider_root"
    (root / "configs").mkdir(parents=True)
    (root / "configs/execution_policy.json").write_text('{"allow_model_code_upload":true}')
    monkeypatch.setattr(gate, "ROOT", root)
    monkeypatch.setattr(gate, "dotenv_values", lambda _: {"BASE_URL": "https://unit.invalid/v1", "API_KEY": "fake-key"})
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"model": postgate.MODEL, "usage": {"total_tokens": 7},
                    "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            calls.append(kwargs["json"])
            return Response()

    monkeypatch.setattr(gate.httpx, "Client", Client)
    return calls


def test_static_inputs_preserve_bodies_and_replace_only_origin_paragraph(monkeypatch, tmp_path):
    args = frozen_round(tmp_path)
    calls = provider(monkeypatch, tmp_path)
    original = gate.SYSTEM
    result = postgate.prepare(args)
    assert result["source_generation_round"] == "r1" and calls == []
    for name in set(postgate.SOURCE_FILES) - {"evidence.json"}:
        assert (args.output / name).read_bytes() == (args.source_round / name).read_bytes()
    prepared = json.loads((args.output / "prepare.json").read_bytes())
    assert prepared["declared_admission_rounds"] == ["gate"]
    assert prepared["algorithm_sha256"] == postgate.driver.algorithm_hashes()
    assert prepared["postgate_adapter_sha256"] == postgate.adapter_hashes()
    result = postgate.admit(args)
    assert result["accepted"] == 1 and len(calls) == 1 and gate.SYSTEM == original
    prompt = calls[0]["messages"][0]["content"]
    assert "A model proposed complete replacement bodies" in prompt
    assert prompt.split("\n\n", 1)[1] == original.split("\n\n", 1)[1]
    assert "MUST_NOT_APPEAR" not in json.dumps(calls[0])
    assert calls[0]["model"] == "deepseek-v4-flash" and calls[0]["max_tokens"] == 10000
    assert calls[0] == json.loads((args.output / "gate_request_template.json").read_bytes())
    frozen = postgate.freeze(args)
    assert frozen["variant"] == "gate" and frozen["generated"] == frozen["controls"] == 1
    with pytest.raises(FileExistsError):
        postgate.admit(args)
    assert len(calls) == 1 and gate.SYSTEM == original


def test_invalid_selection_is_not_repaired_or_retried(monkeypatch, tmp_path):
    args = frozen_round(tmp_path)
    calls = provider(monkeypatch, tmp_path, '{"accepted":["unknown"]}')
    postgate.prepare(args)
    result = postgate.admit(args)
    assert result["status"] == "invalid" and len(calls) == 1
    assert gate.SYSTEM == postgate.ORIGINAL_SYSTEM
    with pytest.raises(ValueError, match="valid semantic"):
        postgate.freeze(args)
    with pytest.raises(FileExistsError):
        postgate.admit(args)
    assert len(calls) == 1


def test_empty_baseline_uses_original_no_candidates_behavior(monkeypatch, tmp_path):
    args = frozen_round(tmp_path, empty=True)
    calls = provider(monkeypatch, tmp_path)
    postgate.prepare(args)
    assert postgate.admit(args)["status"] == "no_candidates"
    assert calls == []
    assert postgate.freeze(args)["generated"] == 0


def test_origin_prompt_restored_when_driver_raises(monkeypatch, tmp_path):
    args = frozen_round(tmp_path)
    postgate.prepare(args)

    def fail(_):
        assert gate.SYSTEM == postgate.SYSTEM
        raise RuntimeError("invented dispatch failure")

    monkeypatch.setattr(postgate.driver, "admit", fail)
    with pytest.raises(RuntimeError, match="invented"):
        postgate.admit(args)
    assert gate.SYSTEM == postgate.ORIGINAL_SYSTEM


@pytest.mark.parametrize("filename", ["corpus.json", "evidence.json", "candidates.json"])
def test_changed_original_inputs_cannot_be_prepared(tmp_path, filename):
    args = frozen_round(tmp_path)
    path = args.source_round / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact changed"):
        postgate.prepare(args)


def test_original_frozen_round_must_match(tmp_path):
    args = frozen_round(tmp_path)
    artifact = args.source_round / "frozen/direct/manifest.json"
    value = json.loads(artifact.read_bytes())
    value["metadata"]["generation_round"] = "r2"
    postgate.driver.write_json(artifact, value)
    postgate.driver.write_json(args.source_round / "freezes/direct.json", {"artifact_sha256": postgate.driver.digest(artifact)})
    with pytest.raises(ValueError, match="different bytes or round"):
        postgate.prepare(args)


def test_unexpected_evidence_fields_are_rejected_even_with_matching_hash(tmp_path):
    args = frozen_round(tmp_path)
    evidence_path = args.source_round / "evidence.json"
    evidence = json.loads(evidence_path.read_bytes())
    evidence["audit_labels"] = ["MUST_NOT_APPEAR"]
    postgate.driver.write_json(evidence_path, evidence)
    manifest_path = args.source_round / "prepare.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files_sha256"]["evidence.json"] = postgate.driver.digest(evidence_path)
    postgate.driver.write_json(manifest_path, manifest)
    artifact = args.source_round / "frozen/direct/manifest.json"
    postgate.driver.write_json(artifact, {"report": {"format": "jsonl", "path": "stdout.txt"}, "files": [],
                                        "metadata": {"generation_round": "r1", "prepare_sha256": postgate.driver.digest(manifest_path)}})
    postgate.driver.write_json(args.source_round / "freezes/direct.json", {"artifact_sha256": postgate.driver.digest(artifact)})
    with pytest.raises(ValueError, match="non-static"):
        postgate.prepare(args)


def test_cached_gate_cannot_silently_use_different_evidence(monkeypatch, tmp_path):
    args = frozen_round(tmp_path)
    provider(monkeypatch, tmp_path)
    postgate.prepare(args)
    postgate.admit(args)
    path = args.output / "admission/gate/request.json"
    request = json.loads(path.read_bytes())
    request["messages"][1]["content"] = '{"evidence":{"issue":"different"}}'
    postgate.driver.write_json(path, request)
    with pytest.raises(ValueError, match="frozen postgate evidence"):
        postgate.freeze(args)
