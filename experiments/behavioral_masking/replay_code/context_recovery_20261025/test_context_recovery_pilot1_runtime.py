"""Local contracts and control-flow tests; never start Docker or call a provider."""
import copy
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace

import pytest

import context_recovery_pilot1_runtime as runtime


CHECKPOINT = {"image_id": "sha256:" + "d" * 64, "head": "a" * 40}
BASE = "b" * 40


@pytest.fixture
def plan(tmp_path):
    inputs, task = tmp_path / "raw", tmp_path / "official"
    inputs.mkdir()
    (task / "tests").mkdir(parents=True)
    (task / "solution").mkdir()
    (inputs / "instruction.md").write_text("Synthetic fixture\n")
    (inputs / "trajectory.json").write_text('{"steps": []}\n')
    (inputs / "model.patch").write_text("")
    (inputs / "task.toml").write_text('[metadata]\nbase_commit_hash = "' + BASE + '"\n')
    (task / "solution/solution.patch").write_text("")
    (task / "tests/test.patch").write_text(
        'diff --git a/tests/check.py b/tests/check.py\n--- a/tests/check.py\n+++ b/tests/check.py\n'
        '@@ -1 +1 @@\n-old\n+new\n')
    (task / "tests/config.json").write_text(json.dumps({"base_commit": BASE}))
    pointer = tmp_path / "checkpoint.json"
    pointer.write_text(json.dumps(CHECKPOINT))
    observation = tmp_path / "observation.json"
    observation.write_text("{}\n")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"submission_state_status": "matched", "submitted_commit_tree_matches": True,
        "working_tree_matches_submitted_commit": True, "index_tree_matches_submitted_commit": True,
        "subject_files_or_real_index_patched": False, "image_id": CHECKPOINT["image_id"],
        "runtime_initial_head": CHECKPOINT["head"], "base_commit": BASE,
        "submitted_patch_sha256": runtime._receipt(inputs / "model.patch")["sha256"],
        "observation_sha256": runtime._receipt(observation)["sha256"]}))
    qualification = tmp_path / "qualification.json"
    qualification.write_text(json.dumps({"passed": True, "checkpoint": CHECKPOINT, "base_commit": BASE,
        "model_patch": runtime._receipt(inputs / "model.patch"), "validation_report": runtime._receipt(report),
        "validation_observation": runtime._receipt(observation), "checkpoint_reference": runtime._receipt(pointer)}))
    return {"checkpoint": dict(CHECKPOINT), "base_commit": BASE, "implementation": "delivered",
            "task_directory": str(task), "input_directory": str(inputs), "mode": "agent",
            "checkpoint_validation": str(qualification), "command": "python3 check.py", "timeout": 60,
            "build_commands": [], "files": [], "env": {}}


def test_plan_requires_explicit_rebuild_and_exact_file_destinations(plan, tmp_path):
    source = tmp_path / "test.py"
    source.write_text("print('fixture')\n")
    invalid = copy.deepcopy(plan)
    invalid.update(requires_build=True)
    with pytest.raises(ValueError, match="requires_build"):
        runtime.validate_plan(invalid)
    for destination in ("/etc/passwd", "/app/../tmp/test.py", "/app/.git/config"):
        invalid = copy.deepcopy(plan)
        invalid["files"] = [{"source": str(source), "destination": destination}]
        with pytest.raises(ValueError):
            runtime.validate_plan(invalid)
    valid = copy.deepcopy(plan)
    valid.update(requires_build=True, build_commands=["python3 -m compileall package"])
    assert runtime.validate_plan(valid)["requires_build"] is True


def test_verifier_rejects_agent_file_overwrite_and_base_mismatch(plan, tmp_path):
    source = tmp_path / "agent.py"
    source.write_text("pass\n")
    plan.update(mode="verifier", files=[{"source": str(source), "destination": "/app/tests/check.py"}])
    with pytest.raises(ValueError, match="override_official"):
        runtime.validate_plan(plan)
    plan["files"] = []
    (Path(plan["task_directory"]) / "tests/config.json").write_text(json.dumps({"base_commit": "c" * 40}))
    with pytest.raises(ValueError, match="verifier_base"):
        runtime.validate_plan(plan)


def test_cache_is_a_fresh_validation_reference_and_checks_raw_identity(plan, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Cache inspection must not invoke replay or Docker")
    monkeypatch.setattr(runtime, "replay_case", forbidden)
    monkeypatch.setattr(runtime, "Container", forbidden)
    run = tmp_path / "run"
    run.mkdir()
    row = {"screen_id": "S001", "trial": "fixture__one", "base_commit": BASE, "image": "fixture:base",
           "task_directory": plan["task_directory"], "input_directory": plan["input_directory"]}
    (run / "screening_order.json").write_text(json.dumps({"trials": [row]}))
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"checkpoints": [{"trial": row["trial"], "base_commit": BASE, "image": row["image"],
        "raw_inputs": {name: runtime._receipt(Path(plan["input_directory"]) / name) for name in runtime.INPUT_NAMES},
        "checkpoint": CHECKPOINT}]}))
    result = runtime.replay_screen("S001", run=run, checkpoint_index=cache)
    assert result["fresh_validation_required"] and result["image_id"] == CHECKPOINT["image_id"]
    assert "state_validation_passed" not in result
    with pytest.raises(FileExistsError):
        runtime.replay_screen("S001", run=run, checkpoint_index=cache)
    (run / "cases/S001/checkpoint.json").unlink()
    (Path(plan["input_directory"]) / "model.patch").write_text("changed\n")
    with pytest.raises(ValueError, match="raw_input_mismatch"):
        runtime.replay_screen("S001", run=run, checkpoint_index=cache)
    assert not (run / "cases/S001/checkpoint.json").exists()


@pytest.fixture
def fake_execution(monkeypatch):
    calls = []
    class FakeContainer:
        def __init__(self, image, output, head, **resources):
            self.image_id, self.name, self.scratch = image, "synthetic", "/tmp/synthetic"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def _docker(self, argv, **kwargs):
            assert argv[0] == "cp"
            calls.append("docker cp " + argv[-1])
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    def run(container, command, timeout, out, env, workdir):
        calls.append(command)
        out.mkdir(parents=True)
        (out / "stdout.bin").write_bytes(b"raw\xff\n")
        (out / "stderr.bin").write_bytes(b"diagnostic\xfe")
        return {"command": command, "status": "completed", "returncode": 9 if command in {"build fails", "target nonzero"} else 0,
                "raw_stdout": str(out / "stdout.bin"), "raw_stderr": str(out / "stderr.bin")}
    monkeypatch.setattr(runtime, "Container", FakeContainer)
    monkeypatch.setattr(runtime, "_run", run)
    return calls


def test_build_failure_stops_target_and_records_final_diff(plan, tmp_path, fake_execution):
    plan.update(requires_build=True, build_commands=["build fails"], command="must not execute")
    result = runtime.execute_plan(plan, tmp_path / "execution")
    assert result["status"] == "preparation_failed" and not result["target_executed"]
    assert "must not execute" not in fake_execution
    assert any("diff --binary" in command for command in fake_execution)
    assert result["failed_step"] == "build_000"


def test_production_snapshots_cover_untracked_files_and_deletion_after_failed_build(
        plan, tmp_path, fake_execution, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    tracked = repository / "deleted.rs"
    tracked.write_bytes(b"original tracked source\n")
    subprocess.run(["git", "-C", str(repository), "add", "deleted.rs"], check=True)
    subprocess.run(["git", "-C", str(repository), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
    untracked = repository / "new.rs"
    original = b"original untracked source\n"
    changed = b"changed during failed build\n"
    untracked.write_bytes(original)
    # This is the real blind spot: Git's ordinary diff does not include the file.
    assert subprocess.run(["git", "-C", str(repository), "diff", "--binary", "HEAD"],
                          capture_output=True, check=True).stdout == b""
    fake_run = runtime._run

    def local_snapshots(container, command, timeout, out, env, workdir):
        record = fake_run(container, command, timeout, out, env, workdir)
        args = shlex.split(command)
        if args[:4] == ["python3", "-I", "-c", runtime._PRODUCTION_SNAPSHOT]:
            assert args[4] == "/app"
            args[4] = str(repository)
            process = subprocess.run(args, capture_output=True, check=True)
            Path(record["raw_stdout"]).write_bytes(process.stdout)
            Path(record["raw_stderr"]).write_bytes(process.stderr)
        elif command == "build fails":
            untracked.write_bytes(changed)
            tracked.unlink()
        return record

    monkeypatch.setattr(runtime, "_run", local_snapshots)
    plan.update(production_paths=["new.rs", "deleted.rs", "absent.rs"],
                requires_build=True, build_commands=["build fails"])
    result = runtime.execute_plan(plan, tmp_path / "execution")
    assert result["status"] == "preparation_failed" and not result["target_executed"]
    snapshots = {
        stage: {row["path"]: row for row in json.loads(Path(record["raw_stdout"]).read_bytes())["paths"]}
        for stage, record in result["production_snapshots"].items()
    }
    for stage, content in (("before_build", original), ("final", changed)):
        row = snapshots[stage]["new.rs"]
        assert row["exists"] and row["kind"] == "file"
        assert row["bytes"] == len(content)
        assert row["sha256"] == hashlib.sha256(content).hexdigest()
        assert not snapshots[stage]["absent.rs"]["exists"]
    assert snapshots["before_build"]["deleted.rs"]["exists"]
    assert snapshots["final"]["deleted.rs"] == {
        "path": "deleted.rs", "exists": False, "kind": "absent", "bytes": None, "sha256": None}
    labels = [step["label"] for step in result["steps"]]
    assert labels.index("production_snapshot_before_build") < labels.index("build_000")
    assert labels.index("build_000") < labels.index("production_snapshot_final")
    assert "production_diff" in result


def test_target_nonzero_is_recorded_without_test_verdict_and_no_overwrite(plan, tmp_path, fake_execution):
    plan["command"] = "target nonzero"
    out = tmp_path / "execution"
    result = runtime.execute_plan(plan, out)
    assert result["status"] == "completed" and result["execution"]["returncode"] == 9
    assert result["exit_status_is_not_test_verdict"]
    assert Path(result["execution"]["raw_stdout"]).read_bytes() == b"raw\xff\n"
    assert not any("reset --hard" in command for command in fake_execution)
    with pytest.raises(FileExistsError):
        runtime.execute_plan(plan, out)


def test_reference_copies_exact_agent_bytes_after_reset_and_solution(plan, tmp_path, fake_execution):
    source = tmp_path / "agent_test.py"
    source.write_bytes(b"print('same agent test')\n")
    plan.update(implementation="reference", files=[{"source": str(source), "destination": "/app/agent_test.py"}])
    result = runtime.execute_plan(plan, tmp_path / "execution")
    assert result["status"] == "completed"
    reset = next(i for i, command in enumerate(fake_execution) if "reset --hard" in command)
    clean = next(i for i, command in enumerate(fake_execution) if "clean -fd" in command)
    apply = next(i for i, command in enumerate(fake_execution) if "apply --whitespace" in command)
    agent_copy = fake_execution.index("docker cp synthetic:/app/agent_test.py")
    target = fake_execution.index(plan["command"])
    assert reset < clean < apply < agent_copy < target
    assert (tmp_path / "execution/inputs/file_000").read_bytes() == source.read_bytes()


def test_reference_rejects_agent_whole_source_overwriting_solution(plan, tmp_path):
    source = tmp_path / "mixed_source_test.py"
    source.write_text("# production and inline tests\n")
    (Path(plan["task_directory"]) / "solution/solution.patch").write_text(
        'diff --git a/source.py b/source.py\n--- a/source.py\n+++ b/source.py\n@@ -1 +1 @@\n-old\n+new\n')
    plan.update(implementation="reference", files=[{"source": str(source), "destination": "/app/source.py"}])
    with pytest.raises(ValueError, match="override_reference_solution"):
        runtime.validate_plan(plan)


def test_execute_rejects_unpassed_or_tampered_checkpoint_validation(plan, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "Container", lambda *args, **kwargs: pytest.fail("Must reject before Docker"))
    path = Path(plan["checkpoint_validation"])
    qualification = json.loads(path.read_text())
    qualification["passed"] = False
    path.write_text(json.dumps(qualification))
    with pytest.raises(ValueError, match="validation_not_passed"):
        runtime.execute_plan(plan, tmp_path / "execution")
    assert not (tmp_path / "execution").exists()
    qualification["passed"] = True
    path.write_text(json.dumps(qualification))
    Path(qualification["validation_report"]["path"]).write_text("{}")
    with pytest.raises(ValueError, match="receipt_changed"):
        runtime.execute_plan(plan, tmp_path / "execution")


@pytest.mark.parametrize("matched", [True, False])
def test_validate_uses_fresh_clone_preserves_pointer_and_records_result(plan, tmp_path, monkeypatch, matched):
    run = tmp_path / "run"
    case_dir = run / "cases/S001"
    case_dir.mkdir(parents=True)
    row = {"screen_id": "S001", "trial": "fixture__one", "base_commit": BASE,
           "input_directory": plan["input_directory"]}
    (run / "screening_order.json").write_text(json.dumps({"trials": [row]}))
    pointer = case_dir / "checkpoint.json"
    pointer.write_text(json.dumps({**CHECKPOINT, "trial": row["trial"], "base_commit": BASE,
        "raw_inputs": {"model.patch": runtime._receipt(Path(plan["input_directory"]) / "model.patch")}}))
    before = pointer.read_bytes()
    calls = []
    class FakeContainer:
        def __init__(self, image, output, head):
            calls.append((image, Path(output), head))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    def validate(container, patch, out, *, base_commit):
        assert patch == Path(plan["input_directory"]) / "model.patch" and base_commit == BASE
        out.mkdir(parents=True)
        (out / "observation.json").write_text("{}\n")
        report = json.loads((tmp_path / "report.json").read_text())
        report["index_tree_matches_submitted_commit"] = matched
        (out / "report.json").write_text(json.dumps(report))
        return report
    monkeypatch.setattr(runtime, "Container", FakeContainer)
    monkeypatch.setattr(runtime, "validate_submission_state", validate)
    result = runtime.validate_screen("S001", run=run)
    assert result["passed"] is matched
    assert pointer.read_bytes() == before
    assert calls == [(CHECKPOINT["image_id"], case_dir / "checkpoint_validation/container", CHECKPOINT["head"])]
    assert (case_dir / "checkpoint_validation/qualification.json").is_file()
    with pytest.raises(FileExistsError):
        runtime.validate_screen("S001", run=run)


def test_explicit_new_replay_attempt_preserves_prior_failure(plan, tmp_path, monkeypatch):
    run = tmp_path / "run"
    first = run / "cases/S001/replay_attempt_001"
    first.mkdir(parents=True)
    prior = first / "failure.json"
    prior.write_bytes(b'{"completed_actions": 0}\n')
    before = prior.read_bytes()
    row = {"screen_id": "S001", "trial": "fixture__one", "base_commit": BASE, "image": "fixture:base",
           "task_directory": plan["task_directory"], "input_directory": plan["input_directory"]}
    (run / "screening_order.json").write_text(json.dumps({"trials": [row]}))
    cache = tmp_path / "empty_cache.json"
    cache.write_text('{"checkpoints": []}\n')
    called = []
    def replay(case, inputs, destination):
        called.append(destination)
        destination.mkdir(parents=True, exist_ok=False)
        checkpoint = {**CHECKPOINT, "state_validation_passed": True}
        (destination / "checkpoint_reference.json").write_text(json.dumps(checkpoint))
        return {"state_validation_passed": True, "study_checkpoint": checkpoint}
    monkeypatch.setattr(runtime, "replay_case", replay)
    with pytest.raises(FileExistsError):
        runtime.replay_screen("S001", run=run, checkpoint_index=cache)
    with pytest.raises(ValueError, match="attempt_requires"):
        runtime.replay_screen("S001", run=run, checkpoint_index=cache, attempt="../escape")
    assert not called
    second = run / "cases/S001/replay_attempt_002"
    result = runtime.replay_screen("S001", run=run, checkpoint_index=cache, attempt="replay_attempt_002")
    assert called == [second] and result["replay_attempt"] == str(second)
    assert prior.read_bytes() == before
