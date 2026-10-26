"""Mock full chronological replays; never read reserved data or invoke Docker."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tramask_pilot.submission_replay import EXECUTE, INVENTORY, SENTINEL
from tramask_rerun import replay


BASE = "a" * 40
HEAD = "b" * 40
BASE_IMAGE = "sha256:" + "c" * 64
CHECKPOINT_IMAGE = "sha256:" + "d" * 64


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "explicit-inputs"
    source.mkdir()
    commands = ["echo first", "cat README.md", "printf final", SENTINEL]
    trajectory = {"steps": [{"step_id": index, "tool_calls": [{"function_name": "bash", "arguments": {"command": command}}],
        "observation": {"results": [{"content": json.dumps({"returncode": 0, "output": "archived"})}]}}
        for index, command in enumerate(commands)]}
    dump(source / "trajectory.json", trajectory)
    (source / "model.patch").write_bytes(b"synthetic submitted patch\n")
    (source / "instruction.md").write_text("Synthetic issue, no real corpus data.")
    (source / "task.toml").write_text(f'''[metadata]
base_commit_hash = "{BASE}"
[environment]
docker_image = "synthetic:image"
cpus = 2
memory_mb = 8192
''')
    case = {"id": "synthetic-case", "image": "synthetic:image", "base_commit": BASE,
            "source": "/must-not-read-implicit-source", "task_directory": "/must-not-read-implicit-task"}
    return source, case, commands


class FakeContainer:
    instances = []
    events = []
    commands = []
    fail_command = None
    background = False
    action_timeout = False

    def __init__(self, image, output, head, **resources):
        self.output = Path(output)
        self.output.mkdir(parents=True)
        self.image = image
        self.image_id = CHECKPOINT_IMAGE if image == CHECKPOINT_IMAGE else BASE_IMAGE
        self.base_commit = head
        self.name = "fake-" + str(len(self.instances))
        self.scratch = "/tmp/" + self.name
        self.records, self.remote = [], {}
        self.process_reads = 0
        self.closed = False
        self.instances.append(self)
        self.events.append(("start", self.image_id, head))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        self._persist()
        self.events.append(("close", self.image_id))

    def _persist(self):
        dump(self.output / "records.json", self.records)
        dump(self.output / "container.json", {"image_id": self.image_id, "closed": self.closed})

    def _control(self, argv, **kwargs):
        script = argv[-1]
        if script == replay._PROCESSES:
            self.process_reads += 1
            self.events.append(("process_inventory", self.process_reads))
            rows = [{"pid": 1, "ppid": 0, "pgid": 1, "session": 1, "state": "S", "start_ticks": 10,
                     "argv": ["sleep", "infinity"]}]
            if self.process_reads == 2 and self.background:
                rows.append({"pid": 23, "ppid": 1, "pgid": 23, "session": 23, "state": "S", "start_ticks": 30,
                             "argv": ["python3", "/tmp/server.py"]})
            return subprocess.CompletedProcess(argv, 0, json.dumps({"processes": rows, "errors": []}).encode(), b"")
        if script == EXECUTE:
            assert argv == ["python3", "-c", EXECUTE] and kwargs["timeout"] == 60
            request = json.loads(kwargs["input_bytes"])
            assert request["env"] == replay.ENV
            command = request["command"]
            self.commands.append(command)
            self.events.append(("action", command))
            if command == self.fail_command:
                raise RuntimeError("synthetic transport interruption after possible side effect")
            output = ("executed " + command).encode()
            self.remote[request["output"]] = output
            result = {"returncode": -1 if self.action_timeout else 0, "timed_out": self.action_timeout,
                      "output_bytes": len(output), "output_sha256": hashlib.sha256(output).hexdigest(),
                      "elapsed_seconds": 0.01, "exception_info": ""}
            return subprocess.CompletedProcess(argv, 0, json.dumps(result).encode(), b"")
        if script == INVENTORY:
            assert self.image_id == CHECKPOINT_IMAGE and self.instances[0].closed
            assert (self.output.parent / "checkpoint.json").exists()
            self.events.append(("filesystem_inventory", self.image_id))
            request = json.loads(kwargs["input_bytes"])
            self.remote[request["destination"]] = json.dumps({"roots": ["/app", "/tmp"], "errors": [],
                "files": [{"path": "/tmp/test.py", "sha256": "a" * 64},
                          {"path": "/app/node_modules/dependency.js", "sha256": "b" * 64}]}).encode()
            return subprocess.CompletedProcess(argv, 0, b'{"files":2,"errors":0}', b"")
        raise AssertionError("Unexpected subject operation")

    def copy_from(self, source, destination):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(self.remote[source])

    def checkpoint(self, label):
        assert label == "before_submission"
        self.events.append(("checkpoint", label))
        result = {"image_id": CHECKPOINT_IMAGE, "head": HEAD, "filesystem_only": True,
                  "process_state_preserved": False, "after_execution_records": len(self.records)}
        dump(self.output / "checkpoints" / label / "result.json", result)
        return result

    @staticmethod
    def _docker(argv, **kwargs):
        if argv[0] == "diff":
            return subprocess.CompletedProcess(argv, 0, b"C /app/source.py\n", b"")
        raise AssertionError("Unexpected Docker operation")

    def apply_patch(self, *args, **kwargs):
        raise AssertionError("Replay must never repair source with a patch")


@pytest.fixture
def fake(monkeypatch):
    FakeContainer.instances, FakeContainer.events, FakeContainer.commands = [], [], []
    FakeContainer.fail_command, FakeContainer.background, FakeContainer.action_timeout = None, False, False
    monkeypatch.setattr(replay, "Container", FakeContainer)
    def validate(runtime, patch, out, *, base_commit):
        assert runtime.image_id == CHECKPOINT_IMAGE and runtime.base_commit == HEAD
        assert FakeContainer.instances[0].closed and base_commit == BASE
        assert Path(patch) == runtime.output.parent / "inputs/model.patch"
        assert Path(patch).read_bytes() == b"synthetic submitted patch\n"
        assert (runtime.output.parent / "checkpoint.json").exists()
        FakeContainer.events.append(("validate", runtime.image_id))
        report = {"submission_state_status": "matched", "submitted_commit_tree_matches": True,
            "working_tree_matches_submitted_commit": True, "index_tree_matches_submitted_commit": True,
            "subject_files_or_real_index_patched": False, "image_id": runtime.image_id,
            "submitted_patch_sha256": hashlib.sha256(Path(patch).read_bytes()).hexdigest()}
        dump(Path(out) / "observation.json", {"synthetic": "raw tracked-tree comparison"})
        dump(Path(out) / "report.json", report)
        return report
    monkeypatch.setattr(replay, "validate_submission_state", validate)
    return FakeContainer


def test_full_exact_actions_then_freeze_then_fresh_validation_and_input_integrity(tmp_path, inputs, fake):
    source, case, commands = inputs
    original = {name: (source / name).read_bytes() for name in replay.INPUT_NAMES}
    out = tmp_path / "attempt"
    result = replay.replay_case(case, source, out)
    assert result["status"] == "replayed" and result["state_validation_passed"]
    assert fake.commands == commands[:-1]  # Includes the read-only cat action.
    assert result["actions_executed"] == 3 and result["terminal_marker"] == "s3_c0"
    assert result["action_ids"] == ["s0_c0", "s1_c0", "s2_c0"]
    for name in replay.INPUT_NAMES:
        assert (source / name).read_bytes() == original[name]
        assert (out / "inputs" / name).read_bytes() == original[name]
    for index, command in enumerate(commands[:-1]):
        directory = out / "runtime/calls" / f"s{index}_c0"
        assert (directory / "command.sh").read_text() == command
        row = json.loads((directory / "result.json").read_text())
        assert row["shell"] == "/bin/sh" and row["timeout_seconds"] == 30
    phases = [row[0] for row in fake.events]
    assert phases.index("checkpoint") < phases.index("filesystem_inventory") < phases.index("validate")
    assert len(fake.instances) == 2 and all(instance.closed for instance in fake.instances)
    assert result["study_checkpoint"]["image_id"] == CHECKPOINT_IMAGE
    assert result["study_checkpoint"]["head"] == HEAD
    assert Path(result["study_checkpoint"]["summary"]["path"]) == out / "summary.json"
    assert not result["output_equality_used"] and not result["repair_actions_performed"]


def test_completed_attempt_reuse_checks_receipts_and_does_not_reexecute(tmp_path, inputs, fake):
    source, case, _ = inputs
    out = tmp_path / "attempt"
    replay.replay_case(case, source, out)
    before = {path: path.read_bytes() for path in out.rglob("*") if path.is_file()}
    result = replay.replay_case(case, source, out)
    assert result["resumed"] and len(fake.instances) == 2
    assert all(path.read_bytes() == content for path, content in before.items())
    (out / "validation/observation.json").write_text("tampered")
    with pytest.raises(ValueError, match="artifact_receipt_changed"):
        replay.replay_case(case, source, out)
    assert len(fake.instances) == 2


def test_partial_attempt_reports_unsafe_resume_and_preserves_every_file(tmp_path, inputs, fake):
    source, case, commands = inputs
    fake.fail_command = commands[1]
    out = tmp_path / "attempt"
    failed = replay.replay_case(case, source, out)
    assert failed["status"] == "interrupted_attempt" and failed["completed_actions"] == 1
    assert failed["resumability"]["can_resume_commands"] is False
    before = {path: path.read_bytes() for path in out.rglob("*") if path.is_file()}
    repeated = replay.replay_case(case, source, out)
    assert repeated["status"] == "requires_new_attempt" and len(fake.instances) == 1
    assert all(path.read_bytes() == content for path, content in before.items())
    assert fake.commands == commands[:2]


def test_background_process_is_recorded_for_manual_qualification_not_fixed(tmp_path, inputs, fake):
    source, case, commands = inputs
    fake.background = True
    result = replay.replay_case(case, source, tmp_path / "attempt")
    assert result["status"] == "replayed_pending_manual_qualification"
    assert result["requires_manual_qualification"] and result["state_validation_passed"]
    assert result["process_qualification"]["active_background_processes"][0]["pid"] == 23
    assert not result["process_qualification"]["known_processes_quiescent"]
    assert fake.commands == commands[:-1] and not result["repair_actions_performed"]


def test_state_or_index_mismatch_does_not_trigger_afterpatch_repair(tmp_path, inputs, fake, monkeypatch):
    source, case, commands = inputs
    original = replay.validate_submission_state
    def mismatch(*args, **kwargs):
        report = original(*args, **kwargs)
        report["index_tree_matches_submitted_commit"] = False
        dump(Path(args[2]) / "report.json", report)
        return report
    monkeypatch.setattr(replay, "validate_submission_state", mismatch)
    result = replay.replay_case(case, source, tmp_path / "attempt")
    assert not result["state_validation_passed"] and result["requires_manual_qualification"]
    assert "submitted_head_worktree_or_index_not_verified" in result["risks"]
    assert fake.commands == commands[:-1]


def test_historical_timeout_remains_recorded_while_all_actions_are_attempted(tmp_path, inputs, fake):
    source, case, commands = inputs
    fake.action_timeout = True
    result = replay.replay_case(case, source, tmp_path / "attempt")
    assert result["timeouts"] == ["s0_c0", "s1_c0", "s2_c0"]
    assert result["returncode_differences"] == result["timeouts"]
    assert result["requires_manual_qualification"] and fake.commands == commands[:-1]


def test_case_configuration_and_existing_attempt_identity_are_bound(tmp_path, inputs, fake):
    source, case, _ = inputs
    with pytest.raises(ValueError, match="explicit_task_configuration"):
        replay.replay_case({**case, "image": "other:image"}, source, tmp_path / "wrong")
    assert not fake.instances
    replay.replay_case(case, source, tmp_path / "attempt")
    with pytest.raises(ValueError, match="existing_attempt_input_or_case_mismatch"):
        replay.replay_case({**case, "id": "different"}, source, tmp_path / "attempt")


def test_image_preflight_is_read_only(monkeypatch):
    calls = []
    def docker(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, (BASE_IMAGE + "\n").encode(), b"")
    monkeypatch.setattr(replay.Container, "_docker", docker)
    result = replay.inspect_image_availability("synthetic:image")
    assert result["available"] and result["image_id"] == BASE_IMAGE and not result["pull_attempted"]
    assert calls == [["image", "inspect", "--format", "{{.Id}}", "synthetic:image"]]


def test_failure_after_checkpoint_reports_validation_only_opportunity(tmp_path, inputs, fake, monkeypatch):
    source, case, _ = inputs
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic validator failure")
    monkeypatch.setattr(replay, "validate_submission_state", fail)
    result = replay.replay_case(case, source, tmp_path / "attempt")
    assert result["status"] == "interrupted_attempt"
    assert result["resumability"]["can_validate_saved_checkpoint_in_new_attempt"]
    assert result["checkpoint"]["image_id"] == CHECKPOINT_IMAGE
    assert result["resumability"]["can_resume_commands"] is False


def test_interrupted_progress_write_is_preserved_and_never_restarted(tmp_path, inputs, fake):
    source, case, _ = inputs
    out = tmp_path / "attempt"
    (out / "progress").mkdir(parents=True)
    partial = out / "progress/000000.json"
    partial.write_bytes(b'{"phase":')
    result = replay.replay_case(case, source, out)
    assert result["status"] == "requires_new_attempt" and not fake.instances
    assert result["resumability"]["interrupted_artifacts"][0]["error_type"] == "JSONDecodeError"
    assert partial.read_bytes() == b'{"phase":'
