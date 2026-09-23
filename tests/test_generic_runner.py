import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from combination_testing import runner as old
from generic_composition.runner import freeze_artifact, infer_harness, run_artifact, run_pair


def test_freeze_records_overwritten_source_and_required_controls(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    original = repo / "test_sample.py"
    original.write_text("def test_seed():\n    assert True\n")
    artifact = tmp_path / "artifact"
    manifest = freeze_artifact(artifact, "unseen", {"test_sample.py": original.read_text() + "\ndef test_new():\n    assert True\n"},
                               "true", "jsonl", "stdout.txt", repository=repo,
                               obligations=[{"id": "test_new", "control_ids": ["test_seed"]}])
    assert manifest["metadata"]["source_files"] == [{"path": "test_sample.py", "sha256": old.sha256(original)}]
    assert manifest["metadata"]["obligations"][0]["controls"] == ["test_seed"]
    assert original.read_text() == "def test_seed():\n    assert True\n"
    with pytest.raises(ValueError, match="source controls"):
        freeze_artifact(tmp_path / "bad", "unseen", {}, "true", "jsonl", "stdout.txt",
                        repository=repo, obligations=[{"id": "test_new"}])


@pytest.mark.parametrize("source_control_passes", [True, False])
def test_local_pair_uses_identical_artifact_and_gates_source_controls(tmp_path, source_control_passes):
    candidate, reference = tmp_path / "candidate", tmp_path / "reference"
    candidate.mkdir()
    reference.mkdir()
    (candidate / "library.py").write_text("value = 2\n")
    (reference / "library.py").write_text("value = 1\n")
    original = f"def test_seed():\n    assert {source_control_passes}\n"
    for repo in (candidate, reference):
        (repo / "test_sample.py").write_text(original)
    content = original + "\ndef test_combined():\n    from library import value\n    assert value == 1\n"
    harness = infer_harness(candidate, "python", ["test_sample.py"], python=sys.executable)
    artifact, output = tmp_path / "artifact", tmp_path / "execution"
    freeze_artifact(artifact, "unseen", {"test_sample.py": content}, harness["command"],
                    harness["report_format"], harness["report_path"], repository=candidate,
                    obligations=[{"id": "test_combined", "controls": ["test_seed"]}])
    result = run_pair(artifact, output, registry=[{"id": "unseen", "repository": str(candidate)}],
                      reference_repository=reference)
    assert bool(result["candidate_alarm"]) == source_control_passes
    assert bool(result["detected"]) == source_control_passes
    if not source_control_passes:
        assert result["counts"]["blocked_by_control"] == 1
    c = json.loads((output / "candidate/result.json").read_text())
    r = json.loads((output / "reference/result.json").read_text())
    assert c["artifact_sha256"] == r["artifact_sha256"] == old.sha256(artifact / "manifest.json")
    assert c["implementation_sha256"] != r["implementation_sha256"]
    assert (candidate / "test_sample.py").read_text() == original
    assert (reference / "test_sample.py").read_text() == original


def test_local_reference_requires_explicit_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    artifact = tmp_path / "artifact"
    freeze_artifact(artifact, "x", {}, "true", "jsonl", "stdout.txt", repository=repo, obligations=[])
    with pytest.raises(ValueError, match="explicit reference_repository"):
        run_artifact(artifact, "reference", tmp_path / "out", registry=[{"id": "x", "repository": str(repo)}])


def test_custom_docker_registry_and_candidate_patch_root(tmp_path, monkeypatch):
    artifact, output, data = tmp_path / "artifact", tmp_path / "output", tmp_path / "data"
    data.mkdir()
    patch = data / "chosen.patch"
    patch.write_text("candidate patch bytes\n")
    old.freeze_artifact(artifact, "unseen", {}, "true", "jsonl", "stdout.txt")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"cases": [{"id": "unseen", "image": "unit/image:one",
                    "base_commit_hash": "base-123", "candidate_patch": "chosen.patch"}]}))
    seen = []

    def fake_run(command, **kwargs):
        seen.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(stdout="sha256:image\n", stderr="", returncode=0)
        if command[:2] == ["docker", "run"]:
            request = json.loads(kwargs["input"])
            assert request["base_commit"] == "base-123"
            assert "none" == command[command.index("--network") + 1]
            (output / "process.json").write_text(json.dumps({"stage": "finished", "returncode": 0}))
            (output / "stdout.txt").write_text('CC_RESULT {"id":"seed","status":"pass"}\n')
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(old.subprocess, "run", fake_run)
    result = old.run_artifact(artifact, "candidate", output, registry=registry, case_root=data)
    assert result["patch_sha256"] == old.sha256(patch)
    assert result["base_commit"] == "base-123"
    assert result["status"] == "pass"
    assert any("unit/image:one" in x for x in seen)


def test_standard_harness_inference_has_no_case_names(tmp_path):
    (tmp_path / "package.json").write_text('{"devDependencies":{"vitest":"1"}}')
    (tmp_path / "pnpm-lock.yaml").write_text("")
    harness = infer_harness(tmp_path, "typescript", ["src/a.test.ts"])
    assert "pnpm exec vitest run src/a.test.ts" in harness["command"]
    assert harness["report_format"] == "vitest-json"
    harness = infer_harness(tmp_path, "go", ["nested/value_test.go", "root_test.go"])
    assert "./nested" in harness["command"]
    assert harness["report_format"] == "go-json"
    harness = infer_harness(tmp_path, "go", [".internal/value_test.go"], name_filter="^TestGC_")
    assert "./.internal" in harness["command"] and "-run '^TestGC_'" in harness["command"]


def test_explicit_clone_filters_preserve_default_behavior(tmp_path):
    assert " -k test_gc_" in infer_harness(tmp_path, "python", ["test_a.py"], name_filter="test_gc_")["command"]
    (tmp_path / "package.json").write_text('{"devDependencies":{"vitest":"1"}}')
    assert " -t gc_" in infer_harness(tmp_path, "typescript", ["a.test.ts"], name_filter="gc_")["command"]


def test_go_subtest_mapping_requires_all_control_leaves_pass():
    from generic_composition.runner import _normalize_go_subtests
    from combination_testing.evaluate import _controls_pass
    manifest = {"report": {"format": "go-json"}, "metadata": {
        "controls": ["TestGC_control_a"], "obligations": [{"id": "TestGC_new", "controls": ["TestGC_control_a"]}]}}
    result = {"tests": [{"id": "pkg::TestGC_control_a/one", "status": "pass"},
                         {"id": "pkg::TestGC_control_a/two", "status": "fail"}]}
    _normalize_go_subtests(result, manifest)
    assert result["tests"][0]["raw_id"] == "pkg::TestGC_control_a/one"
    assert result["tests"][0]["id"] == "pkg::TestGC_control_a[one]"
    assert not _controls_pass(["TestGC_control_a"], {row["id"]: row for row in result["tests"]})


def test_node_adapter_reports_named_tests(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"type":"module"}')
    source = '''import {test} from 'node:test';
import {strict as assert} from 'node:assert';
test('seed', () => assert.equal(1, 1));
test('generated', () => assert.equal(2, 2));
test.skip('disabled', () => assert.fail('not executed'));
'''
    (repo / "example.test.ts").write_text(source)
    harness = infer_harness(repo, "typescript", ["example.test.ts"])
    artifact = tmp_path / "artifact"
    freeze_artifact(artifact, "node", {"example.test.ts": source, **harness["files"]},
                    harness["command"], harness["report_format"], harness["report_path"],
                    repository=repo, obligations=[{"id": "generated", "controls": ["seed"]}])
    result = run_artifact(artifact, "candidate", tmp_path / "execution",
                          registry=[{"id": "node", "repository": str(repo)}])
    assert not result["errors"]
    assert {row["id"] for row in result["tests"]} == {"seed", "generated", "disabled"}
    assert result["counts"]["pass"] == 2
    assert result["counts"]["skip"] == 1
