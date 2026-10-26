"""Runtime isolation/fidelity checks; no Docker subjects or providers are run."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from tramask_pilot.runtime import Container, _SNAPSHOT, normalize_output


BASE = "a" * 40
IMAGE = "sha256:" + "b" * 64
CHECKPOINT = "sha256:" + "d" * 64


class FakeDocker:
    def __init__(self, *, head=BASE, execution=None, mounts=None, remove_code=0, commit_warning=False,
                 restart_code=0, control_failure=None):
        self.calls = []
        self.head = head
        self.execution = execution
        self.mounts = mounts or []
        self.remove_code = remove_code
        self.commit_warning = commit_warning
        self.restart_code = restart_code
        self.control_failure = control_failure

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        assert argv[0] == "docker", "Historical shell text must never execute on the host"
        if argv[1:3] == ["image", "inspect"]:
            image = CHECKPOINT if argv[-1] == CHECKPOINT else IMAGE
            return subprocess.CompletedProcess(argv, 0, (image + "\n").encode(), b"")
        if argv[1] == "inspect":
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.mounts).encode(), b"")
        if argv[1] == "commit":
            warning = b"WARNING: legacy builder is deprecated\n" if self.commit_warning else b""
            return subprocess.CompletedProcess(argv, 0, warning + CHECKPOINT.encode() + b"\n", b"")
        if argv[1] == "restart":
            return subprocess.CompletedProcess(argv, self.restart_code, b"restarted", b"failed" if self.restart_code else b"")
        if argv[1:3] == ["image", "rm"]:
            return subprocess.CompletedProcess(argv, self.remove_code, b"", b"in use" if self.remove_code else b"")
        if argv[1] == "exec":
            if self.control_failure and argv[-2:] == ["-c", self.control_failure]:
                return subprocess.CompletedProcess(argv, 128, b"OCI runtime exec failed: procReady not received", b"")
            if argv[-2:] == ["rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(argv, 0, self.head.encode() + b"\n", b"")
            if argv[-4:] == ["ls-files", "--others", "--exclude-standard", "-z"]:
                return subprocess.CompletedProcess(argv, 0, b"preinstalled-cache\0", b"")
            if "bash" in argv and self.execution is not None:
                if isinstance(self.execution, BaseException):
                    raise self.execution
                code, out, err = self.execution
                return subprocess.CompletedProcess(argv, code, out, err)
        return subprocess.CompletedProcess(argv, 0, b"", b"")


def test_exact_command_and_raw_output_survive_pinned_isolated_execution(tmp_path, monkeypatch):
    raw = b"\x1b[31m/app/test.py\x1b[0m: observed=17\r\n1 passed in 0.42s\n"
    docker = FakeDocker(execution=(0, raw, b"diagnostic\xff"))
    monkeypatch.setattr(subprocess, "run", docker)
    command = "printf '%s\\n' '$HOME `uname`'\npython test.py"
    expected = {"returncode": 0, "output": "archived output"}
    with Container("mutable-tag", tmp_path / "run", BASE) as container:
        record = container.exec(command, "step-12-call-0", expected=expected)
        with pytest.raises(FileExistsError):
            container.exec(command, "step-12-call-0")
    start = next(argv for argv, _ in docker.calls if argv[1] == "run")
    assert start[-2:] == [IMAGE, "infinity"]
    assert start[start.index("--network") + 1] == "none"
    assert start[start.index("--cap-drop") + 1] == "ALL"
    assert start[start.index("--pids-limit") + 1] == "1024"
    assert "no-new-privileges:true" in start
    assert not ({"--mount", "--volume", "-v", "--env", "-e", "--privileged"} & set(start))
    invocation, options = next((argv, kw) for argv, kw in docker.calls if "bash" in argv)
    assert invocation[-3:] == ["bash", "-lc", command]
    assert options["timeout"] == 210
    assert invocation[invocation.index("timeout") + 1:invocation.index("bash")] == [
        "--signal=TERM", "--kill-after=5s", "180s"]
    call = tmp_path / "run/calls/step-12-call-0"
    assert (call / "command.sh").read_text() == command
    assert (call / "stdout.bin").read_bytes() == raw
    assert (call / "stderr.bin").read_bytes() == b"diagnostic\xff"
    assert json.loads((call / "archived_expected.json").read_text()) == expected
    assert record["stdout_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "observed=17" in (call / "stdout.normalized.txt").read_text()
    assert record["normalization_is_not_semantic_equivalence"]
    assert json.loads((tmp_path / "run/container.json").read_text())["closed"]


def test_base_mismatch_closes_before_historical_execution(tmp_path, monkeypatch):
    docker = FakeDocker(head="c" * 40)
    monkeypatch.setattr(subprocess, "run", docker)
    with pytest.raises(ValueError, match="Base mismatch"):
        Container("tag", tmp_path / "run", BASE)
    assert any(argv[1:3] == ["rm", "--force"] for argv, _ in docker.calls)
    assert not any("bash" in argv for argv, _ in docker.calls)


@pytest.mark.parametrize("timeout", [0, -1, 181, 1.5, True])
def test_out_of_budget_timeout_rejected_before_execution(tmp_path, monkeypatch, timeout):
    docker = FakeDocker()
    monkeypatch.setattr(subprocess, "run", docker)
    with Container("tag", tmp_path / "run", BASE) as container:
        with pytest.raises(ValueError, match="timeout must be"):
            container.exec("some historical command", "bad", timeout=timeout)
    assert not any("bash" in argv for argv, _ in docker.calls)


def test_transport_timeout_retains_partial_output_and_discards_container(tmp_path, monkeypatch):
    docker = FakeDocker(execution=subprocess.TimeoutExpired("docker", 31, output=b"partial", stderr=b"err"))
    monkeypatch.setattr(subprocess, "run", docker)
    container = Container("tag", tmp_path / "run", BASE)
    record = container.exec("sleep 9999", "timeout", timeout=1)
    assert record["timed_out"] and record["transport_error"]
    assert record["returncode"] is None
    assert container.closed and record["stdout"] == "partial"
    assert (tmp_path / "run/calls/timeout/stdout.bin").read_bytes() == b"partial"
    with pytest.raises(RuntimeError, match="closed"):
        container.exec("echo unsafe continuation", "later")


def test_reset_recreates_the_same_pinned_image_without_deleting_image_dependencies(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(subprocess, "run", docker)
    with Container("moving-tag", tmp_path / "run", BASE) as container:
        previous_name = container.name
        container.reset()
        assert container.name != previous_name
    starts = [argv for argv, _ in docker.calls if argv[1] == "run"]
    assert len(starts) == 2 and all(argv[-2] == IMAGE for argv in starts)
    assert not any("clean" in argv for argv, _ in docker.calls)
    assert len([argv for argv, _ in docker.calls if argv[1:3] == ["image", "inspect"]]) == 1


def test_normalizer_keeps_semantic_values_and_documents_limited_changes():
    raw = "assert result == 0x55\n/app/value = 1.2s\n<object at 0xabc123>\n2 passed in 0.42s\n"
    normalized = normalize_output(raw)
    assert "result == 0x55" in normalized and "value = 1.2s" in normalized
    assert "at <ADDRESS>" in normalized and "passed in <TIME>" in normalized
    assert "<REPO>/value" in normalized
    assert normalize_output("/application/thing") == "/application/thing"
    assert normalize_output("/work/repo/a", path_aliases={"/work/repo": "<ROOT>"}) == "<ROOT>/a"


def test_snapshot_keeps_actual_versions_untracked_tests_and_deletions(tmp_path):
    """Synthetic Git fixtures only: no code under test is imported or executed."""
    repo = tmp_path / "repository"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL)
    git("init")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    (repo / "module.py").write_text("original bytes\n")
    (repo / "deleted.py").write_text("deleted later\n")
    (repo / ".gitignore").write_text("ignored_test.py\n")
    git("add", ".")
    git("commit", "-m", "synthetic base")
    base = git("rev-parse", "HEAD").decode().strip()
    (repo / "module.py").write_text("historical edited bytes\n")
    git("add", "module.py")  # Staged changes must still enter the base-relative diff.
    (repo / "deleted.py").unlink()
    (repo / "temporary_test.py").write_text("agent-created test bytes\n")
    (repo / "ignored_test.py").write_text("explicit ignored test bytes\n")
    (repo / "preinstalled-cache").write_text("must not enter agent snapshot\n")
    (repo / ".env").write_text("private fixture bytes\n")
    (repo / "link.py").symlink_to("module.py")
    destination = tmp_path / "snapshot"
    request = {"base_commit": base, "root": str(repo), "destination": str(destination),
               "baseline_untracked": ["preinstalled-cache"],
               "extra_paths": [str(repo / "ignored_test.py")]}
    subprocess.run([sys.executable, "-c", _SNAPSHOT], input=json.dumps(request).encode(),
                   capture_output=True, check=True)
    manifest = json.loads((destination / "manifest.json").read_text())
    rows = {Path(row["path"]).name: row for row in manifest["files"]}
    assert rows["deleted.py"]["kind"] == "missing"
    assert rows["link.py"]["kind"] == "symlink"
    assert "temporary_test.py" in rows and "ignored_test.py" in rows
    assert "preinstalled-cache" not in rows and ".env" not in rows
    patch = (destination / "implementation.patch").read_text()
    assert "+historical edited bytes" in patch and "deleted file mode" in patch
    with tarfile.open(destination / "sources.tar.gz") as archive:
        member = str(repo / "module.py").lstrip("/")
        assert archive.extractfile(member).read() == b"historical edited bytes\n"
        assert archive.getmember(str(repo / "link.py").lstrip("/")).issym()


def test_copy_path_validation_and_empty_patch_failure_are_not_execution_passes(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(subprocess, "run", docker)
    source = tmp_path / "test.py"
    source.write_text("bytes")
    with Container("tag", tmp_path / "run", BASE) as container:
        with pytest.raises(ValueError):
            container.copy_to(source, "/app/../escape")
        container.copy_to(source, "/app/nested/test.py")
        with pytest.raises(ValueError, match="under /app or /tmp"):
            container.snapshot("bad-extra", extra_paths=["/etc/passwd"])
    copies = [argv for argv, _ in docker.calls if argv[1] == "cp"]
    assert len(copies) == 1 and copies[0][-1].endswith(":/app/nested/test.py")


def test_checkpoint_can_start_fresh_twins_and_is_retained_until_explicit_cleanup(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(subprocess, "run", docker)
    source = Container("original-tag", tmp_path / "source", BASE)
    docker.head = "e" * 40  # Historical actions may have made a Git commit.
    checkpoint = source.checkpoint("before-test")
    assert checkpoint["image_id"] == CHECKPOINT
    assert checkpoint["head"] == docker.head
    assert checkpoint["source_base_commit"] == BASE
    assert checkpoint["source_image_id"] == IMAGE
    assert checkpoint["pause"] and not checkpoint["process_state_preserved"]
    assert checkpoint["elapsed_seconds"] >= 0
    assert "--pause=true" in checkpoint["docker_argv"]
    with Container(checkpoint["image_id"], tmp_path / "historical", checkpoint["head"]):
        pass
    with Container(checkpoint["image_id"], tmp_path / "final", checkpoint["head"]):
        pass
    source.close()
    assert not any(argv[1:3] == ["image", "rm"] for argv, _ in docker.calls)
    with pytest.raises(ValueError, match="not created"):
        source.cleanup_checkpoint(IMAGE)
    with pytest.raises(ValueError, match="not created"):
        source.cleanup_checkpoint("sha256:" + "f" * 64)
    cleaned = source.cleanup_checkpoint(CHECKPOINT)
    assert cleaned["status"] == "removed"
    assert source.cleanup_checkpoint(CHECKPOINT)["status"] == "already_removed"
    removals = [argv for argv, _ in docker.calls if argv[1:3] == ["image", "rm"]]
    assert removals == [["docker", "image", "rm", CHECKPOINT]]
    record = json.loads((tmp_path / "source/checkpoints/before-test/result.json").read_text())
    assert record["cleanup_status"] == "removed"
    assert (tmp_path / "source/checkpoints/before-test/stdout.bin").read_bytes() == (CHECKPOINT + "\n").encode()
    assert all("--mount" not in argv and "--volume" not in argv for argv, _ in docker.calls)


def test_checkpoint_rejects_mounts_omitted_by_docker_commit(tmp_path, monkeypatch):
    docker = FakeDocker(mounts=[{"Type": "volume", "Destination": "/app"}])
    monkeypatch.setattr(subprocess, "run", docker)
    with Container("tag", tmp_path / "source", BASE) as source:
        with pytest.raises(ValueError, match="without mounted volumes"):
            source.checkpoint("invalid-volume")
    assert not any(argv[1] == "commit" for argv, _ in docker.calls)


def test_checkpoint_in_use_is_retained_and_cleanup_can_be_retried(tmp_path, monkeypatch):
    docker = FakeDocker(remove_code=1)
    monkeypatch.setattr(subprocess, "run", docker)
    with Container("tag", tmp_path / "source", BASE) as source:
        checkpoint = source.checkpoint("kept")
    assert source.cleanup_checkpoint(checkpoint["image_id"])["status"] == "retained"
    docker.remove_code = 0
    assert source.cleanup_checkpoint(checkpoint["image_id"])["status"] == "removed"
    record = json.loads((tmp_path / "source/checkpoints/kept/result.json").read_text())
    assert [attempt["status"] for attempt in record["cleanup_attempts"]] == ["retained", "removed"]


def test_checkpoint_accepts_unique_image_id_after_docker_deprecation_warning(tmp_path, monkeypatch):
    docker = FakeDocker(commit_warning=True)
    monkeypatch.setattr(subprocess, "run", docker)
    with Container("tag", tmp_path / "source", BASE) as source:
        record = source.checkpoint("docker29")
    assert record["image_id"] == CHECKPOINT
    assert record["stdout_non_image_lines"] == ["WARNING: legacy builder is deprecated"]
    raw = (tmp_path / "source/checkpoints/docker29/stdout.bin").read_bytes()
    assert raw == b"WARNING: legacy builder is deprecated\n" + CHECKPOINT.encode() + b"\n"


def test_timer_exit_restarts_same_container_and_qualifies_process_state_deviation(tmp_path, monkeypatch):
    docker = FakeDocker(execution=(124, b"partial test output", b""))
    monkeypatch.setattr(subprocess, "run", docker)
    with Container("tag", tmp_path / "run", BASE) as source:
        name, scratch = source.name, source.scratch
        result = source.exec("pytest test_workers.py", "timeout", timeout=1)
        assert result["timed_out"] and not result["transport_error"]
        assert result["returncode"] == 124 and result["stdout"] == "partial test output"
        assert result["restoration_deviation"] == "container_process_state_reset_after_timeout"
        assert result["restart_after_timeout"]["success"]
        assert result["restart_after_timeout"]["filesystem_preserved"]
        assert source.name == name and source.scratch == scratch and not source.closed
        docker.execution = (0, b"later action", b"")
        later = source.exec("echo later", "later")
        assert later["stdout"] == "later action"
        assert later["prior_restoration_deviations"][0]["process_state_reset"]
    restarts = [argv for argv, _ in docker.calls if argv[1] == "restart"]
    assert restarts == [["docker", "restart", "--time", "5", name]]
    assert len([argv for argv, _ in docker.calls if argv[1] == "run"]) == 1
    lifecycle = json.loads((tmp_path / "run/container.json").read_text())["lifecycle"]
    assert any(row.get("process_state_reset") and row.get("restoration_deviation") for row in lifecycle)


def test_failed_timeout_restart_stops_further_replay(tmp_path, monkeypatch):
    docker = FakeDocker(execution=(124, b"partial", b""), restart_code=1)
    monkeypatch.setattr(subprocess, "run", docker)
    source = Container("tag", tmp_path / "run", BASE)
    result = source.exec("pytest test_workers.py", "timeout", timeout=1)
    assert result["transport_error"] and source.closed
    assert result["error"] == "timeout_cleanup_restart_failed"
    with pytest.raises(RuntimeError, match="closed"):
        source.exec("echo should not run", "later")


@pytest.mark.parametrize("output", [
    b"OCI runtime exec failed: exec failed: unable to start container process: procReady not received",
    b"Error response from daemon: Container abcdef is not running",
])
def test_docker_exec_error_is_transport_failure_not_subject_exit(tmp_path, monkeypatch, output):
    docker = FakeDocker(execution=(128, output, b""))
    monkeypatch.setattr(subprocess, "run", docker)
    source = Container("tag", tmp_path / "run", BASE)
    result = source.exec("pytest test_target.py", "oci")
    assert result["transport_error"] and not result["timed_out"] and source.closed
    assert result["error"] == "docker_exec_runtime_failure"
    assert (tmp_path / "run/calls/oci/stdout.bin").read_bytes() == output


def test_control_failure_archives_large_command_without_huge_exception_text(tmp_path, monkeypatch):
    script = "print('very large snapshot script')\n" * 1000
    docker = FakeDocker(control_failure=script)
    monkeypatch.setattr(subprocess, "run", docker)
    with Container("tag", tmp_path / "run", BASE) as source:
        with pytest.raises(RuntimeError, match="diagnostics:") as error:
            source._control(["python3", "-c", script])
        assert len(str(error.value)) < 350 and script not in str(error.value)
    diagnostic, = (tmp_path / "run/control_errors").iterdir()
    assert json.loads((diagnostic / "request.json").read_text())["docker_argv"][-1] == script
    assert b"OCI runtime" in (diagnostic / "stdout.bin").read_bytes()
