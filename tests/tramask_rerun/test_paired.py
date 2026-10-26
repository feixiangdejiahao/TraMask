"""Synthetic file staging and fake runtimes only; no Docker/provider calls."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tramask_rerun import paired


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@pytest.fixture
def data():
    case = {"id": "synthetic", "checkpoint": {"image_id": "sha256:" + "a" * 64, "head": "b" * 40},
            "test_timeout_seconds": 120, "build_timeout_seconds": 300, "working_directory": "/tmp/fixture",
            "resources": {"cpus": 1, "memory": "1g"}}
    files = {"app/code.py": "def value():\n    return 1\n",
             "tmp/test.py": "setup = 0\nresult = value()\nassert result == 1\n"}
    h = {"status": "proposed", "reason": "synthetic", "original_command": "python /tmp/test.py | tail -8",
         "target": {"source_path": "app/code.py", "behavior": "value", "anchor": "return", "logical_effect": "value", "public_observation": "result"},
         "alternative": {"kind": "targeted_mutation", "rationale": "synthetic", "action_ids": [],
                         "edits": [{"path": "app/code.py", "old": "return 1", "new": "return 2"}]},
         "instrumentation": {"command": "python /tmp/test.py", "noninterference": "pending semantic validation", "shared_anchors": [
             {"id": "effect", "channel": "effect", "p_location": "return", "q_location": "return", "meaning": "same"},
             {"id": "observation", "channel": "observation", "p_location": "assert", "q_location": "assert", "meaning": "same"}],
             "common_edits": [{"path": "tmp/test.py", "old": "assert result == 1\n", "new": "print('PROBE', result)\nassert result == 1\n"}],
             "p_edits": [{"path": "app/code.py", "old": "    return 1\n", "new": "    print('EFFECT', 1)\n    return 1\n"}],
             "q_edits": [{"path": "app/code.py", "old": "    return 2\n", "new": "    print('EFFECT', 2)\n    return 2\n"}],
             "helper_files": [{"path": "tmp/helper.py", "content": "# measurement helper\n"}]}}
    return case, files, h


def review(data, **kwargs):
    case, files, h = data
    return {"approved_for_execution": True, "reviewer_id": "technical-reviewer",
            "rationale": "Exact edits, reviewed instrumentation command and equal clean build plans.",
            "binding": paired.execution_binding(case, files, h, test_paths=["tmp/test.py"], **kwargs)}


def event(channel, value, anchor=None):
    return "TRAMASK_EVENT " + json.dumps({"channel": channel, "anchor": anchor or channel,
        "test": "test_value", "input": {"stimulus": 3}, "call": 1, "target_reached": True, "value": value}) + "\n"


class FakeRuntime:
    def __init__(self):
        self.calls = []
        self.bad_line = None
        self.raise_on_call = None
        self.interrupt_on_call = None
        self.build_fail_variant = None
        self.timeout_variant = None

    def __call__(self, checkpoint, out, command, timeout, **kwargs):
        out = Path(out)
        self.calls.append({"checkpoint": checkpoint, "out": out, "command": command, "timeout": timeout, **kwargs})
        out.mkdir(parents=True, exist_ok=False)
        if self.interrupt_on_call == len(self.calls):
            (out / "partial.log").write_text("preserve interrupted invocation")
            raise KeyboardInterrupt()
        if self.raise_on_call == len(self.calls):
            raise RuntimeError("synthetic infrastructure failure")
        name = out.name
        builds = []
        for i, build in enumerate(kwargs["build_commands"]):
            directory = out / f"build_{i:02d}"
            directory.mkdir()
            (directory / "stdout.bin").write_bytes(b"build output\n")
            (directory / "stderr.bin").write_bytes(b"")
            builds.append({"command": build, "status": "completed", "returncode": 1 if name == self.build_fail_variant else 0,
                           "elapsed_seconds": 0.5, "timed_out": False})
        if name == self.build_fail_variant and builds:
            result = {"status": "build_failed", "execution": None, "builds": builds, "observations": []}
        else:
            text = "--- PASS: test_value (0.00s)\n"
            if name.endswith("_instrumented"):
                text += event("effect", 2 if name.startswith("q_") else 1) + event("observation", [])
                if self.bad_line:
                    text += self.bad_line
            stdout, stderr = out / "stdout.bin", out / "stderr.bin"
            stdout.write_bytes(text.encode())
            stderr.write_bytes(b"diagnostic\xff\n")
            timed_out = name == self.timeout_variant
            execution = {"status": "timeout" if timed_out else "completed", "returncode": -9 if timed_out else 0,
                "timed_out": timed_out, "elapsed_seconds": 0.25, "raw_stdout": str(stdout), "raw_stderr": str(stderr),
                "stdout_sha256": sha(stdout.read_bytes()), "stdout_bytes": stdout.stat().st_size,
                "stderr_sha256": sha(stderr.read_bytes()), "stderr_bytes": stderr.stat().st_size}
            observations = []
            for index, path in enumerate(kwargs["observation_paths"]):
                raw_path = out / ("observation_" + str(index) + ".bin")
                raw_path.write_text(event("observation", {"side": 1}, anchor="captured-file"))
                observations.append({"path": path, "status": "present", "raw_path": str(raw_path),
                                     "sha256": sha(raw_path.read_bytes()), "bytes": raw_path.stat().st_size})
            result = {"status": execution["status"], "execution": execution, "builds": builds, "observations": observations}
        save(out / "result.json", result)
        return result


@pytest.fixture
def runtime(monkeypatch):
    fake = FakeRuntime()
    monkeypatch.setattr(paired, "execute_variant", fake)
    return fake


def execute(data, out, **kwargs):
    case, files, h = data
    return paired.execute_qualified_pair(case, files, h, out, test_paths=["tmp/test.py"],
                                         review=review(data, **kwargs), **kwargs)


def test_twelve_fresh_variants_bind_checkpoint_commands_files_and_raw_events(data, runtime, tmp_path):
    result = execute(data, tmp_path / "pair", observation_paths=["/tmp/measurement.log"])
    assert result["status"] == "completed_pending_evidence_qualification" and result["scientific_label"] is None
    assert len(runtime.calls) == 12 and len({row["out"] for row in runtime.calls}) == 12
    assert result["cost"]["subject_test_command_runs"] == 12
    assert result["cost"]["variant_invocations"] == 12 and result["cost"]["elapsed_subject_test_seconds"] == 3
    for row in runtime.calls:
        assert row["checkpoint"] == data[0]["checkpoint"] and row["workdir"] == "/tmp/fixture"
        assert row["command"] == (data[2]["instrumentation"]["command"] if row["out"].name.endswith("_instrumented") else data[2]["original_command"])
        if row["out"].name == "p_original":
            assert row["files"] == {}
        if row["out"].name.startswith("q_"):
            assert row["files"]["/app/code.py"]["before_sha256"] == sha(data[1]["app/code.py"])
    first = result["repeats"][0]
    diagnosis = first["variants"]["p_instrumented"]["diagnosis"]
    assert len(diagnosis["effects"]) == 1 and len(diagnosis["observations"]) == 2
    assert diagnosis["runner_collection_facts"]["identities"][0]["id"] == "test_value"
    comparison = first["diagnostics"]["instrumented_PQ"]["comparison"]
    assert comparison["effect_difference"] is True and comparison["observation_equality"] is True
    assert first["diagnostics"]["noninterference_checks"]["p"]["approved_noninterference"] is None
    assert len(result["between_repeat_diagnostics"]) == 2
    assert any(row["path"].endswith("stderr.bin") for row in result["artifacts"])


@pytest.mark.parametrize("mutation", ["approval", "hypothesis", "source", "command", "build", "checkpoint"])
def test_review_mismatch_prevents_all_execution_and_output(data, runtime, tmp_path, mutation):
    approval = review(data)
    case, files, h = copy.deepcopy(data)
    if mutation == "approval": approval["approved_for_execution"] = False
    if mutation == "hypothesis": h["reason"] = "different JSON"
    if mutation == "source": files["app/code.py"] += "# changed\n"
    if mutation == "command": h["instrumentation"]["command"] += " --extra"
    if mutation == "build": approval["binding"]["build_plan"]["commands"] = ["changed build"]
    if mutation == "checkpoint": case["checkpoint"]["head"] = "c" * 40
    with pytest.raises(ValueError):
        paired.execute_qualified_pair(case, files, h, tmp_path / "out", test_paths=["tmp/test.py"], review=approval)
    assert not runtime.calls and not (tmp_path / "out").exists()


def test_reuse_verifies_receipts_without_repeat_and_rejects_tampered_capture(data, runtime, tmp_path):
    out = tmp_path / "pair"
    first = execute(data, out)
    second = execute(data, out)
    assert second["reused_verified_output"] and len(runtime.calls) == 12
    assert second["cost"] == first["cost"]
    (out / "repeat_01/p_original/stdout.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="receipt_mismatch"):
        execute(data, out)
    assert len(runtime.calls) == 12


def test_reuse_rejects_added_symlink_directory(data, runtime, tmp_path):
    out = tmp_path / "pair"
    execute(data, out)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (out / "added-directory").symlink_to(unrelated, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink_in_paired_artifacts"):
        execute(data, out)
    assert len(runtime.calls) == 12


def test_invalid_checkpoint_digest_is_rejected_before_dispatch(data, runtime, tmp_path):
    data[0]["checkpoint"]["image_id"] = "sha256:" + "z" * 64
    with pytest.raises(ValueError, match="immutable_checkpoint_image_required"):
        execute(data, tmp_path / "invalid-image")
    assert not runtime.calls and not (tmp_path / "invalid-image").exists()


def test_interruption_preserves_completed_and_partial_runs_without_implicit_retry(data, runtime, tmp_path):
    runtime.interrupt_on_call = 3
    out = tmp_path / "partial"
    with pytest.raises(KeyboardInterrupt):
        execute(data, out)
    assert (out / "repeat_01/p_original/result.json").exists()
    assert (out / "repeat_01/q_original/result.json").exists()
    assert (out / "repeat_01/p_instrumented/partial.log").exists()
    with pytest.raises(FileExistsError, match="no_implicit_retry"):
        execute(data, out)
    assert len(runtime.calls) == 3


def test_generated_runtime_requires_reviewed_build_for_every_variant(data, runtime, tmp_path):
    with pytest.raises(ValueError, match="requires_explicit_build_plan"):
        execute(data, tmp_path / "bad", generated_runtime=True)
    assert not runtime.calls
    result = execute(data, tmp_path / "built", generated_runtime=True, build_commands=("python build.py",))
    assert result["cost"]["build_command_runs"] == 12
    assert result["cost"]["elapsed_build_seconds"] == 6
    assert all(row["build_commands"] == ["python build.py"] for row in runtime.calls)
    assert result["binding"]["build_plan"]["effective_timeout_seconds"] == data[0]["test_timeout_seconds"]


def test_build_failure_and_timeout_are_retained_without_success_inference(data, runtime, tmp_path):
    runtime.build_fail_variant = "q_original"
    runtime.timeout_variant = "q_instrumented"
    result = execute(data, tmp_path / "failed", generated_runtime=True, build_commands=("build",))
    assert result["status"] == "completed_with_execution_or_event_errors"
    assert result["cost"]["subject_test_command_runs"] == 9 and result["cost"]["build_command_runs"] == 12
    assert result["repeats"][0]["variants"]["q_instrumented"]["diagnosis"]["timed_out"]
    assert result["scientific_label"] is None


@pytest.mark.parametrize("bad", [
    'TRAMASK_EVENT {"channel":"effect","channel":"observation"}\n',
    'TRAMASK_EVENT {"channel":"effect","anchor":"x","target_reached":true,"value":NaN}\n',
    'TRAMASK_EVENT {"channel":"effect"}\n',
    'TRAMASK_EVENT {"channel":"effect","anchor":"x","target_reached":true,"value":1} extra\n',
    'prefix TRAMASK_EVENT {}\n'])
def test_strict_event_errors_preserve_valid_events_and_disable_comparison(data, runtime, tmp_path, bad):
    runtime.bad_line = bad
    result = execute(data, tmp_path / "events")
    row = result["repeats"][0]
    assert row["variants"]["p_instrumented"]["diagnosis"]["event_status"] == "event_error"
    assert len(row["variants"]["p_instrumented"]["diagnosis"]["events"]) == 2
    assert row["diagnostics"]["instrumented_PQ"]["comparison"] is None
    assert result["status"] == "completed_with_execution_or_event_errors" and result["scientific_label"] is None


def test_capsule_specs_are_explicit_new_files_in_all_four_variants(data, runtime, tmp_path):
    origins = {"tmp/test.py": {"kind": "historical_test_capsule", "new_file": True, "sha256": sha(data[1]["tmp/test.py"])}}
    execute(data, tmp_path / "capsule", source_origins=origins)
    assert all(row["files"]["/tmp/test.py"]["new_file"] for row in runtime.calls)
    assert all("before_sha256" not in row["files"]["/tmp/test.py"] for row in runtime.calls)


@pytest.mark.parametrize("empty", [True, False])
def test_empty_or_noop_q_is_staging_failure_not_a_success(data, runtime, tmp_path, empty):
    data[2]["alternative"]["edits"] = [] if empty else [{"path": "app/code.py", "old": "return 1", "new": "return 1"}]
    result = execute(data, tmp_path / "invalid")
    assert result["status"] == "staging_failed" and result["scientific_label"] is None
    assert result["cost"]["subject_test_command_runs"] == 0 and not runtime.calls
    assert execute(data, tmp_path / "invalid")["reused_verified_output"]


def test_unexpected_runtime_exception_is_retained_and_other_runs_continue(data, runtime, tmp_path):
    runtime.raise_on_call = 2
    result = execute(data, tmp_path / "exception")
    assert len(runtime.calls) == 12 and result["cost"]["subject_test_command_runs"] == 11
    assert result["cost"]["invocations_with_unknown_physical_counts"] == 1
    assert result["status"] == "completed_with_execution_or_event_errors"
    assert (tmp_path / "exception/repeat_01/q_original/invocation_failure.json").exists()


def test_candidate_pair_binds_candidate_and_preserves_fixed_Q(data, runtime, tmp_path):
    candidate = {"rank": 1, "status": "proposed", "edits": [{"path": "tmp/test.py", "old": "setup = 0", "new": "setup = 1"}]}
    approval = review(data, candidate=candidate, repeats=1)
    result = paired.execute_candidate_pair(*data, candidate, tmp_path / "candidate", test_paths=["tmp/test.py"], review=approval, repeats=1)
    assert result["binding"]["candidate_sha256"] and len(runtime.calls) == 4
    assert all("setup = 1" in row["files"]["/tmp/test.py"]["content"] for row in runtime.calls)
    assert "return 2" in runtime.calls[1]["files"]["/app/code.py"]["content"]
