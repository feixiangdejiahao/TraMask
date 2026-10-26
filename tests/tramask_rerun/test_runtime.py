"""Synthetic local helpers and fake containers; no Docker or provider calls."""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from tramask_rerun import runtime


CHECKPOINT = {"image_id": "sha256:" + "d" * 64, "head": "a" * 40}


def digest(value):
    return hashlib.sha256(value).hexdigest()


class FakeContainer:
    instances = []

    def __init__(self, image, output, head, **resources):
        self.image_id, self.head = image, head
        self.output = Path(output)
        self.output.mkdir(parents=True)
        self.scratch = str(self.output / "scratch")
        Path(self.scratch).mkdir()
        self.name = "synthetic-" + str(len(self.instances))
        self.records, self.calls = [], []
        self.closed = False
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def _control(self, argv, **kwargs):
        assert argv[:3] == ["python3", "-I", "-c"]
        assert argv[3] in {runtime._FILES, runtime._EXECUTE}
        request = json.loads(kwargs["input_bytes"])
        self.calls.append((argv[3], request, kwargs["timeout"]))
        # These are fixed helper programs acting on pytest temporary files and
        # explicitly synthetic commands, never repository subject commands.
        return subprocess.run([sys.executable, "-I", "-c", argv[3]], input=kwargs["input_bytes"],
                              capture_output=True, timeout=kwargs["timeout"], check=False)

    def copy_from(self, source, destination):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    def _persist(self):
        pass

    def exec(self, *args, **kwargs):
        raise AssertionError("Must not use historical runtime.exec or its 180-second cap")

    def _restart_after_timeout(self, *args, **kwargs):
        raise AssertionError("Submission experiments must never restart a timed-out container")


@pytest.fixture
def fake_container(monkeypatch):
    FakeContainer.instances = []
    monkeypatch.setattr(runtime, "Container", FakeContainer)
    return FakeContainer


def python_command(source):
    return shlex.quote(sys.executable) + " -c " + shlex.quote(source)


def test_task_timeout_exact_bytes_and_no_old_exec(tmp_path, fake_container):
    command = python_command("import os;os.write(1,b'out\\xff\\r\\n');os.write(2,b'err\\xfe');raise SystemExit(7)")
    result = runtime.execute_variant(CHECKPOINT, tmp_path / "run", command, 1800, workdir="/tmp")
    record = result["execution"]
    assert result["status"] == "completed" and record["returncode"] == 7
    assert record["exit_status_is_not_test_verdict"]
    assert record["shell"] == "/bin/sh" and record["timeout_seconds"] == 1800
    assert Path(record["raw_stdout"]).read_bytes() == b"out\xff\r\n"
    assert Path(record["raw_stderr"]).read_bytes() == b"err\xfe"
    assert record["stdout_sha256"] == digest(b"out\xff\r\n")
    assert record["stderr_sha256"] == digest(b"err\xfe")
    container = fake_container.instances[0]
    assert container.image_id == CHECKPOINT["image_id"] and container.head == CHECKPOINT["head"]
    assert container.closed
    execute = [row for row in container.calls if row[0] == runtime._EXECUTE]
    assert len(execute) == 1 and execute[0][2] == 1830


def test_timeout_kills_group_preserves_partial_streams_and_closes(tmp_path, fake_container):
    command = python_command("import os,time;os.write(1,b'started');os.write(2,b'diagnostic');time.sleep(20)")
    result = runtime.execute_variant(CHECKPOINT, tmp_path / "run", command, 0.2, workdir="/tmp")
    record = result["execution"]
    assert result["status"] == "timeout" and record["timed_out"]
    assert Path(record["raw_stdout"]).read_bytes() == b"started"
    assert Path(record["raw_stderr"]).read_bytes() == b"diagnostic"
    assert "no container restart" in record["timeout_cleanup"]
    assert fake_container.instances[0].closed


def test_exact_replacements_and_explicit_new_files_record_both_hashes(tmp_path, fake_container):
    existing = tmp_path / "subject.py"
    existing.write_bytes(b"old\r\n")
    existing.chmod(0o755)
    new = tmp_path / "nested" / "probe.py"
    specs = {str(existing): {"content": "new\r\n", "before_sha256": digest(b"old\r\n")},
             str(new): {"content": "probe\n", "new_file": True}}
    result = runtime.execute_variant(CHECKPOINT, tmp_path / "run", "true", 300,
                                     files=specs, observation_paths=[str(existing)], workdir="/tmp")
    assert result["status"] == "completed"
    assert existing.read_bytes() == b"new\r\n" and existing.stat().st_mode & 0o777 == 0o755
    assert new.read_bytes() == b"probe\n"
    receipts = {row["path"]: row for row in result["file_receipts"]["files"]}
    assert receipts[str(existing)]["before_sha256"] == digest(b"old\r\n")
    assert receipts[str(existing)]["after_sha256"] == digest(b"new\r\n")
    assert receipts[str(new)]["before_sha256"] is None and receipts[str(new)]["new_file"]
    assert result["observations"][0]["content"] == "new\r\n"


def test_hash_failure_preflights_entire_batch_before_any_write_or_test(tmp_path, fake_container):
    first, second = tmp_path / "a", tmp_path / "b"
    first.write_text("first")
    second.write_text("second")
    result = runtime.execute_variant(CHECKPOINT, tmp_path / "run", "true", 300, workdir="/tmp", files={
        str(first): {"content": "changed", "before_sha256": digest(b"first")},
        str(second): {"content": "changed", "before_sha256": digest(b"wrong")}})
    assert result["status"] == "file_precondition_failed"
    assert result["file_receipts"]["error"] == "predecessor_hash_mismatch"
    assert first.read_text() == "first" and second.read_text() == "second"
    assert result["execution"] is None
    assert not any(call[0] == runtime._EXECUTE for call in fake_container.instances[0].calls)


@pytest.mark.parametrize("path", ["/etc/passwd", "/app/../etc/passwd", "/tmp//x", "relative.py", "/app/.git/config", "/tmp"])
def test_path_escape_refused_before_start(tmp_path, fake_container, path):
    with pytest.raises(ValueError):
        runtime.execute_variant(CHECKPOINT, tmp_path / "run", "true", 300,
                                files={path: {"content": "x", "new_file": True}})
    assert not fake_container.instances


def test_symlink_ancestor_and_leaf_rejected_without_following(tmp_path, fake_container):
    target = tmp_path / "real"
    target.mkdir()
    original = target / "file"
    original.write_text("do not change")
    link = tmp_path / "alias"
    link.symlink_to(target, target_is_directory=True)
    result = runtime.execute_variant(CHECKPOINT, tmp_path / "run", "true", 300,
        files={str(link / "file"): {"content": "changed", "before_sha256": digest(b"do not change")}})
    assert result["status"] == "file_precondition_failed"
    assert result["file_receipts"]["error"] == "symlink_in_subject_path"
    assert original.read_text() == "do not change"


def test_implicit_new_file_and_existing_new_file_rejected(tmp_path, fake_container):
    file = tmp_path / "test.py"
    with pytest.raises(ValueError, match="existing_file_requires_before_sha256"):
        runtime.execute_variant(CHECKPOINT, tmp_path / "run", "true", 300, files={str(file): {"content": "new"}})
    file.write_text("existing")
    result = runtime.execute_variant(CHECKPOINT, tmp_path / "run", "true", 300,
                                     files={str(file): {"content": "new", "new_file": True}})
    assert result["status"] == "file_precondition_failed" and file.read_text() == "existing"


def test_failed_build_prevents_stale_execution_and_successful_build_precedes_test(tmp_path, fake_container):
    file = tmp_path / "production.py"
    file.write_text("before")
    spec = {str(file): {"content": "after", "before_sha256": digest(b"before")}}
    with pytest.raises(ValueError, match="requires_build_command"):
        runtime.execute_variant(CHECKPOINT, tmp_path / "run", "true", 300, files=spec,
                                production_paths=[str(file)], generated_runtime=True)
    failed = runtime.execute_variant(CHECKPOINT, tmp_path / "failed", "true", 300,
        files=spec, production_paths=[str(file)], generated_runtime=True,
        build_commands=["exit 9"], workdir="/tmp")
    assert failed["status"] == "build_failed" and failed["execution"] is None
    assert failed["builds"][0]["returncode"] == 9
    passed = runtime.execute_variant(CHECKPOINT, tmp_path / "passed", "true", 300,
        build_commands=["printf 'compiled'"], workdir="/tmp")
    assert passed["status"] == "completed" and passed["builds"][0]["stdout"] == "compiled"
    executed = [r[1]["command"] for r in fake_container.instances[-1].calls if r[0] == runtime._EXECUTE]
    assert executed == ["printf 'compiled'", "true"]


def test_export_checkpoint_is_explicit_and_missing_is_not_restored(tmp_path, fake_container):
    present, missing = tmp_path / "test.py", tmp_path / "absent.py"
    present.write_text("original")
    result = runtime.export_checkpoint_files(CHECKPOINT, tmp_path / "export", [str(present), str(missing)])
    assert result["status"] == "complete"
    records = {row["path"]: row for row in result["files"]}
    assert records[str(present)]["content"] == "original"
    assert records[str(present)]["sha256"] == digest(b"original")
    assert records[str(missing)]["status"] == "missing" and not missing.exists()
    assert fake_container.instances[0].closed


def test_each_variant_uses_its_own_clean_checkpoint_container_and_durable_directory(tmp_path, fake_container):
    for variant in ("p_original", "q_original", "p_instrumented", "q_instrumented"):
        assert runtime.execute_variant(CHECKPOINT, tmp_path / variant, "true", 300,
                                       workdir="/tmp")["status"] == "completed"
    assert len(fake_container.instances) == 4
    assert len({container.name for container in fake_container.instances}) == 4
    assert all(container.image_id == CHECKPOINT["image_id"] and container.closed for container in fake_container.instances)
    with pytest.raises(FileExistsError):
        runtime.execute_variant(CHECKPOINT, tmp_path / "p_original", "true", 300, workdir="/tmp")
    assert len(fake_container.instances) == 4


def test_transport_failure_preserves_raw_diagnostics_and_stops(tmp_path, fake_container, monkeypatch):
    original = fake_container._control
    def control(self, argv, **kwargs):
        if argv[3] == runtime._EXECUTE:
            raise subprocess.TimeoutExpired("docker", 330, output=b"control partial", stderr=b"transport error")
        return original(self, argv, **kwargs)
    monkeypatch.setattr(fake_container, "_control", control)
    result = runtime.execute_variant(CHECKPOINT, tmp_path / "run", "true", 300, workdir="/tmp")
    assert result["status"] == "transport_error"
    assert (tmp_path / "run/test/control/transport.stdout.bin").read_bytes() == b"control partial"
    assert fake_container.instances[0].closed


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan")])
def test_invalid_timeouts_rejected_before_container(tmp_path, fake_container, timeout):
    with pytest.raises(ValueError, match="positive_finite"):
        runtime.execute_variant(CHECKPOINT, tmp_path / "run", "true", timeout)
    assert not fake_container.instances
