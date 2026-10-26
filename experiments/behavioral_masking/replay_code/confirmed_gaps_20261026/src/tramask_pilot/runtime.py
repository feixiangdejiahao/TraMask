"""Pinned, disposable Docker execution for the TraMask replay pilot.

No subject command runs on the host and no host directory or credentials are
mounted in a subject container.  This module does not choose historical actions,
infer test outcomes, read reference solutions, or declare a masking witness.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
import uuid


MAX_COMMAND_TIMEOUT = 180
# Calibration showed that whole-suite tests can exceed 256 processes. CPU and
# memory bounds remain unchanged; timed-out descendants are explicitly reaped.
DEFAULT_PIDS_LIMIT = 1024
TRANSPORT_FAILURE = re.compile(
    r"OCI runtime exec failed|unable to start container process|procReady not received|"
    r"No such container|Cannot connect to the Docker daemon|Error response from daemon|"
    r"[Cc]ontainer\s+\S+\s+is (?:not running|restarting)")
NORMALIZATION_RULES = [
    "CRLF to LF; remove ANSI terminal control sequences",
    "explicit caller-supplied path aliases; /app becomes <REPO>",
    "pytest temporary-directory sequence numbers become <N>",
    "hexadecimal object addresses following 'at ' become <ADDRESS>",
    "test-runner elapsed durations following 'in ' or 'Time: ' become <TIME>",
]


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_output(text: str, *, path_aliases: dict[str, str] | None = None) -> str:
    """A display/comparison aid, never proof of equal public observations.

    Raw output is always retained by ``exec``. In particular this function does
    not erase arbitrary numbers, absolute paths, assertions, or exception text.
    """
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text.replace("\r\n", "\n"))
    aliases = {"/app": "<REPO>", **(path_aliases or {})}
    for original, replacement in sorted(aliases.items(), key=lambda item: -len(item[0])):
        if not original:
            raise ValueError("Empty output path alias")
        text = re.sub(re.escape(original) + r"(?=/|\s|:|$)", lambda _: replacement, text)
    text = re.sub(r"(pytest-(?:of-[^/\s]+/pytest-)?)[0-9]+", r"\1<N>", text)
    text = re.sub(r"\bat 0x[0-9a-fA-F]+\b", "at <ADDRESS>", text)
    text = re.sub(r"\b(in |Time: )[0-9]+(?:\.[0-9]+)?\s*(?:ms|milliseconds|s|seconds)\b",
                  r"\1<TIME>", text)
    return text


def _label(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value) or value in {".", ".."}:
        raise ValueError("Expected a simple, unique execution label")
    return value


def _container_path(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or str(path) == "/":
        raise ValueError("Expected a non-root absolute container path without '..'")
    return str(path)


# Standard-library-only code runs inside the subject image. Baseline untracked
# image files are deliberately excluded: they can be dependency caches or
# evaluator files, rather than files written by the agent.
_SNAPSHOT = r'''
import hashlib,json,os,stat,subprocess,sys,tarfile
request=json.load(sys.stdin)
base=request['base_commit']; root=request.get('root','/app'); destination=request['destination']
os.makedirs(destination,exist_ok=False)
def git(*args):
    return subprocess.check_output(['git','-c','safe.directory=/app','-C',root,*args])
tracked=set(git('ls-files','--cached','-z').split(b'\0'))-{b''}
untracked=set(git('ls-files','--others','--exclude-standard','-z').split(b'\0'))-{b''}
baseline={os.fsencode(p) for p in request['baseline_untracked']}
names=tracked | (untracked-baseline)
paths=[os.path.join(root,os.fsdecode(p)) for p in sorted(names)]
paths.extend(request['extra_paths'])
blocked={'.git','.aws','.codex','.agents','.venv','venv','node_modules','__pycache__','.pytest_cache','.mypy_cache','.cache'}
def allowed(path):
    parts=path.split('/')
    return not any(p in blocked or p=='.env' or p.startswith('.env.') for p in parts)
records=[]; excluded=[]; seen=set()
with tarfile.open(destination+'/sources.tar.gz','w:gz') as archive:
    for path in paths:
        path=os.path.normpath(path)
        if path in seen: continue
        seen.add(path)
        if not allowed(path):
            excluded.append({'path':path,'reason':'dependency_cache_or_private_path'});continue
        if not os.path.lexists(path):
            records.append({'path':path,'kind':'missing'});continue
        info=os.lstat(path)
        if stat.S_ISDIR(info.st_mode):
            excluded.append({'path':path,'reason':'explicit_files_required_for_directories'});continue
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            excluded.append({'path':path,'reason':'not_regular_file_or_symlink'});continue
        row={'path':path,'archive_path':path.lstrip('/'),'mode':stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):
            row.update(kind='symlink',target=os.readlink(path))
        else:
            with open(path,'rb') as f: data=f.read()
            row.update(kind='file',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        archive.add(path,arcname=row['archive_path'],recursive=False)
        records.append(row)
diff=git('diff','--binary',base,'--')
with open(destination+'/implementation.patch','wb') as f:f.write(diff)
manifest={'base_commit':base,'head':git('rev-parse','HEAD').decode().strip(),
          'files':records,'excluded':excluded,
          'selection':'tracked files plus nonignored new untracked files and explicit extra files; baseline untracked image files excluded',
          'diff_scope':'tracked changes relative to base, including committed and staged changes; untracked content is in archive',
          'status':git('status','--porcelain=v1','-z').decode(errors='replace')}
with open(destination+'/manifest.json','w') as f:json.dump(manifest,f,indent=2)
print(json.dumps({'files':len(records),'excluded':len(excluded)}))
'''


class Container:
    """Persistent chronological replay, or one fresh member of a P/Q pair.

    Construction resolves an image to its immutable ID and verifies ``HEAD``.
    Call ``snapshot`` immediately before the chosen historical ``exec``; source
    edits embedded in that same command remain part of the archived command.
    ``reset`` recreates the entire container from that same image, preserving
    installed dependencies while discarding all run-created state.
    """

    def __init__(self, image: str, output: str | Path, base_commit: str, *,
                 cpus: float = 2, memory: str = "8g", pids_limit: int = DEFAULT_PIDS_LIMIT,
                 path_aliases: dict[str, str] | None = None):
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", base_commit):
            raise ValueError("base_commit must be a full Git object ID")
        if cpus <= 0 or pids_limit <= 0 or not re.fullmatch(r"[1-9][0-9]*(?:[kmgtKMGT])?", memory):
            raise ValueError("Invalid container resource bound")
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        if (self.output / "container.json").exists():
            raise FileExistsError("Container evidence directory already used")
        self.image, self.base_commit = image, base_commit.lower()
        self.cpus, self.memory, self.pids_limit = cpus, memory, pids_limit
        self.path_aliases = dict(path_aliases or {})
        self.records: list[dict] = []
        self.lifecycle: list[dict] = []
        self.checkpoints: list[dict] = []
        self.name: str | None = None
        self.closed = True
        inspected = self._docker(["image", "inspect", "--format", "{{.Id}}", image], timeout=30)
        self.image_id = inspected.stdout.decode().strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_id):
            raise ValueError("Docker did not return an immutable image ID")
        self._start()

    @staticmethod
    def _docker(arguments: list[str], *, timeout: float = 30,
                input_bytes: bytes | None = None, check: bool = True):
        return subprocess.run(["docker", *arguments], input=input_bytes,
                              capture_output=True, timeout=timeout, check=check)

    def _persist(self):
        _write_json(self.output / "container.json", {
            "image": self.image, "image_id": self.image_id, "base_commit": self.base_commit,
            "isolation": {"network": "none", "capabilities": "ALL dropped", "host_mounts": [],
                          "host_environment_forwarded": False, "cpus": self.cpus,
                          "memory": self.memory, "pids_limit": self.pids_limit},
            "normalization_rules": NORMALIZATION_RULES, "path_aliases": self.path_aliases,
            "lifecycle": self.lifecycle, "closed": self.closed,
            "checkpoints": self.checkpoints,
        })
        _write_json(self.output / "records.json", self.records)

    def _start(self):
        self.name = "tramask-" + uuid.uuid4().hex[:20]
        self.scratch = "/tmp/" + self.name
        command = ["run", "--detach", "--init", "--name", self.name, "--network", "none",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                   "--cpus", str(self.cpus), "--memory", self.memory,
                   "--pids-limit", str(self.pids_limit), "--entrypoint", "sleep",
                   self.image_id, "infinity"]
        self.closed = False
        self.lifecycle.append({"event": "start", "name": self.name, "docker_argv": command})
        try:
            self._docker(command, timeout=60)
            head = self._control(["git", "-c", "safe.directory=/app", "-C", "/app",
                                  "rev-parse", "HEAD"]).stdout.decode().strip()
            if head.lower() != self.base_commit:
                raise ValueError(f"Base mismatch: expected {self.base_commit}, found {head}")
            # Validate the timer before executing any historical action.
            self._control(["timeout", "--version"])
            initial = self._control(["git", "-c", "safe.directory=/app", "-C", "/app",
                                     "ls-files", "--others", "--exclude-standard", "-z"])
            self.baseline_untracked = [v.decode(errors="surrogateescape")
                                       for v in initial.stdout.split(b"\0") if v]
            self._control(["mkdir", "-p", self.scratch])
            self.lifecycle[-1]["verified_base"] = head
            self._persist()
        except BaseException:
            self.close()
            raise

    def _control(self, argv: list[str], *, timeout: float = 30,
                 input_bytes: bytes | None = None, check: bool = True, workdir: str = "/app"):
        if self.closed:
            raise RuntimeError("Container is closed")
        if workdir != "/app":
            workdir = _container_path(workdir)
        command = ["exec", "--interactive", "--workdir", workdir, self.name, *argv]
        try:
            result = self._docker(command, timeout=timeout, input_bytes=input_bytes, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            if not check:
                raise
            directory = self.output / "control_errors" / uuid.uuid4().hex[:12]
            directory.mkdir(parents=True)
            _write_json(directory / "request.json", {"docker_argv": ["docker", *command],
                        "timeout_seconds": timeout, "error_type": type(error).__name__})
            for name in ("stdout", "stderr"):
                data = getattr(error, name, None) or b""
                (directory / (name + ".bin")).write_bytes(data if isinstance(data, bytes) else str(data).encode())
            raise RuntimeError(f"Container control transport failed ({type(error).__name__}); diagnostics: {directory}") from None
        if check and result.returncode:
            directory = self.output / "control_errors" / uuid.uuid4().hex[:12]
            directory.mkdir(parents=True)
            _write_json(directory / "request.json", {"docker_argv": ["docker", *command],
                        "timeout_seconds": timeout, "returncode": result.returncode})
            (directory / "stdout.bin").write_bytes(result.stdout)
            (directory / "stderr.bin").write_bytes(result.stderr)
            raise RuntimeError(f"Container control command failed (exit {result.returncode}, executable {argv[0]}); diagnostics: {directory}")
        return result

    def _restart_after_timeout(self, directory: Path) -> dict:
        """Reap the whole PID namespace while keeping this container's files."""
        event = {"event": "restart_after_timeout", "name": self.name,
                 "filesystem_preserved": True, "process_state_reset": True,
                 "restoration_deviation": True, "success": False,
                 "docker_argv": ["docker", "restart", "--time", "5", self.name]}
        try:
            restarted = self._docker(event["docker_argv"][1:], timeout=30, check=False)
            (directory / "restart.stdout.bin").write_bytes(restarted.stdout)
            (directory / "restart.stderr.bin").write_bytes(restarted.stderr)
            event["returncode"] = restarted.returncode
            if restarted.returncode:
                event["error"] = "container_restart_failed"
            else:
                checked = self._control(["git", "-c", "safe.directory=/app", "-C", "/app",
                                         "rev-parse", "HEAD"], timeout=30, check=False)
                (directory / "restart_check.stdout.bin").write_bytes(checked.stdout)
                (directory / "restart_check.stderr.bin").write_bytes(checked.stderr)
                head = checked.stdout.decode(errors="replace").strip()
                event.update(success=checked.returncode == 0 and bool(re.fullmatch(r"[0-9a-fA-F]{40,64}", head)),
                             head_after_restart=head, check_returncode=checked.returncode)
                if not event["success"]:
                    event["error"] = "container_exec_unavailable_after_restart"
        except (OSError, subprocess.SubprocessError) as error:
            event["error"] = type(error).__name__
        self.lifecycle.append(event)
        _write_json(directory / "restart.json", event)
        if not event["success"]:
            self.close()
        self._persist()
        return event

    def exec(self, command: str, label: str, timeout: int = MAX_COMMAND_TIMEOUT, *,
             expected=None, workdir: str = "/app") -> dict:
        """Execute exact shell text; retain raw bytes, archived output, and status.

        Docker transport failures terminate the container to avoid lingering
        commands. Exit 124/137 is recorded as a timeout signal, never as a test
        failure. A timer exit restarts the SAME container to reap descendants,
        retaining filesystem state but recording a process-state restoration
        deviation. The caller must still determine test collection/outcome.
        """
        if self.closed:
            raise RuntimeError("Container is closed")
        if not isinstance(command, str) or not command or "\0" in command:
            raise ValueError("command must be nonempty shell text without NUL")
        if type(timeout) is not int or not 0 < timeout <= MAX_COMMAND_TIMEOUT:
            raise ValueError(f"timeout must be between 1 and {MAX_COMMAND_TIMEOUT} seconds")
        label = _label(label)
        directory = self.output / "calls" / label
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "command.sh").write_text(command)
        if expected is not None:
            _write_json(directory / "archived_expected.json", expected)
        started = time.monotonic()
        record = {"label": label, "command": command, "working_directory": workdir, "timeout_seconds": timeout,
                  "container": self.name, "image_id": self.image_id,
                  "command_sha256": _digest(directory / "command.sh"),
                  "returncode": None, "timed_out": False, "transport_error": False,
                  "prior_restoration_deviations": [dict(event) for event in self.lifecycle
                                                    if event.get("restoration_deviation")],
                  "raw_stdout": str(directory / "stdout.bin"),
                  "raw_stderr": str(directory / "stderr.bin")}
        try:
            process = self._control(["timeout", "--signal=TERM", "--kill-after=5s",
                                     str(timeout) + "s", "bash", "-lc", command],
                                    timeout=timeout + 30, check=False, **({"workdir": workdir} if workdir != "/app" else {}))
            stdout, stderr = process.stdout, process.stderr
            record.update(returncode=process.returncode, timed_out=process.returncode in {124, 137})
            transport_text = (stdout + stderr).decode(errors="replace")
            if process.returncode and TRANSPORT_FAILURE.search(transport_text):
                record.update(transport_error=True, error="docker_exec_runtime_failure")
                self.close()
            elif record["timed_out"]:
                restarted = self._restart_after_timeout(directory)
                record.update(restart_after_timeout=restarted,
                              restoration_deviation="container_process_state_reset_after_timeout")
                if not restarted["success"]:
                    record.update(transport_error=True, error="timeout_cleanup_restart_failed")
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            record.update(timed_out=True, transport_error=True, error="docker_transport_timeout")
            self.close()
        except OSError as error:
            stdout, stderr = b"", str(error).encode()
            record.update(transport_error=True, error=type(error).__name__)
            self.close()
        record["elapsed_seconds"] = time.monotonic() - started
        for stream, data in (("stdout", stdout), ("stderr", stderr)):
            if isinstance(data, str):
                data = data.encode()
            (directory / (stream + ".bin")).write_bytes(data)
            text = data.decode(errors="replace")
            (directory / (stream + ".txt")).write_text(text)
            normalized = normalize_output(text, path_aliases=self.path_aliases)
            (directory / (stream + ".normalized.txt")).write_text(normalized)
            record[stream] = text
            record[stream + "_sha256"] = hashlib.sha256(data).hexdigest()
            record[stream + "_normalized_sha256"] = hashlib.sha256(normalized.encode()).hexdigest()
        record["normalization_is_not_semantic_equivalence"] = True
        _write_json(directory / "result.json", record)
        self.records.append(record)
        self._persist()
        return record

    def copy_to(self, source: str | Path, destination: str) -> None:
        if self.closed:
            raise RuntimeError("Container is closed")
        source = Path(source).resolve(strict=True)
        destination = _container_path(destination)
        self._control(["mkdir", "-p", str(PurePosixPath(destination).parent)])
        self._docker(["cp", str(source), self.name + ":" + destination], timeout=60)

    def copy_from(self, source: str, destination: str | Path) -> Path:
        if self.closed:
            raise RuntimeError("Container is closed")
        source = _container_path(source)
        destination = Path(destination).resolve()
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._docker(["cp", self.name + ":" + source, str(destination)], timeout=60)
        return destination

    def apply_patch(self, path: str | Path, label: str = "implementation") -> dict:
        """Apply one binary-compatible patch relative to the current version."""
        label = _label(label)
        directory = self.output / "patches" / label
        directory.mkdir(parents=True, exist_ok=False)
        frozen = directory / "implementation.patch"
        frozen.write_bytes(Path(path).read_bytes())
        target = self.scratch + "/" + label + ".patch"
        self.copy_to(frozen, target)
        process = self._control(["git", "-c", "safe.directory=/app", "-C", "/app", "apply",
                                 "--whitespace=nowarn", target], check=False)
        (directory / "stdout.bin").write_bytes(process.stdout)
        (directory / "stderr.bin").write_bytes(process.stderr)
        result = {"label": label, "sha256": _digest(frozen), "returncode": process.returncode}
        _write_json(directory / "result.json", result)
        if process.returncode:
            raise RuntimeError("Implementation patch could not be applied; see frozen patch logs")
        return result

    def snapshot(self, label: str, *, extra_paths: tuple[str, ...] | list[str] = ()) -> dict:
        """Freeze source/test bytes and the tracked diff at the current moment.

        Explicit extra paths must name files under /app or /tmp. An inline test
        stays in command.sh; callers must explicitly include ignored or /tmp
        test/fixture files. No archive is automatically extracted on the host.
        """
        label = _label(label)
        directory = self.output / "snapshots" / label
        if directory.exists():
            raise FileExistsError(directory)
        extra = [_container_path(value) for value in extra_paths]
        if any(not (p.startswith("/app/") or p.startswith("/tmp/")) for p in extra):
            raise ValueError("Snapshot extras must be files under /app or /tmp")
        remote = self.scratch + "/snapshot-" + label
        request = {"base_commit": self.base_commit, "destination": remote,
                   "baseline_untracked": self.baseline_untracked, "extra_paths": extra}
        self._control(["python3", "-c", _SNAPSHOT], input_bytes=json.dumps(request).encode(), timeout=120)
        self.copy_from(remote, directory)
        result = {"label": label, "image_id": self.image_id, "base_commit": self.base_commit,
                  "container": self.name, "after_execution_records": len(self.records),
                  "archive": str(directory / "sources.tar.gz"),
                  "patch": str(directory / "implementation.patch"),
                  "manifest": str(directory / "manifest.json")}
        for name, file in (("archive", "sources.tar.gz"), ("patch", "implementation.patch"),
                           ("manifest", "manifest.json")):
            result[name + "_sha256"] = _digest(directory / file)
        _write_json(directory / "receipt.json", result)
        return result

    def export_sources(self, destination: str | Path, *,
                       include_paths: tuple[str, ...] | list[str] = ()) -> dict:
        """Export an unextracted snapshot bundle into an unused host directory."""
        destination = Path(destination).resolve()
        if destination.exists():
            raise FileExistsError(destination)
        result = self.snapshot("export-" + uuid.uuid4().hex[:12], extra_paths=include_paths)
        import shutil
        shutil.copytree(Path(result["archive"]).parent, destination)
        return {**result, "export_directory": str(destination)}

    def checkpoint(self, label: str) -> dict:
        """Preserve this pre-command filesystem as an immutable Docker image.

        The image remains until ``cleanup_checkpoint(image_id)`` is explicitly
        called. A fresh ``Container(record['image_id'], output, record['head'])``
        starts with these filesystem bytes, including dependencies and fixtures.
        Docker commits do not capture live processes, sockets, or mounted volume
        contents; mounted volumes are rejected rather than silently omitted.
        """
        if self.closed:
            raise RuntimeError("Container is closed")
        label = _label(label)
        directory = self.output / "checkpoints" / label
        directory.mkdir(parents=True, exist_ok=False)
        mounts = self._docker(["inspect", "--format", "{{json .Mounts}}", self.name])
        (directory / "mounts.json").write_bytes(mounts.stdout)
        if json.loads(mounts.stdout):
            raise ValueError("Checkpoint requires a container without mounted volumes")
        head = self._control(["git", "-c", "safe.directory=/app", "-C", "/app",
                              "rev-parse", "HEAD"]).stdout.decode().strip()
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", head):
            raise ValueError("Checkpoint repository HEAD is not a full Git object ID")
        command = ["commit", "--pause=true", "--message", "TraMask pilot checkpoint " + label,
                   self.name]
        started = time.monotonic()
        record = {"label": label, "container": self.name, "head": head.lower(),
                  "source_image_id": self.image_id, "source_image": self.image,
                  "source_base_commit": self.base_commit, "docker_argv": ["docker", *command],
                  "started_at": datetime.now(timezone.utc).isoformat(),
                  "after_execution_records": len(self.records),
                  "pause": True, "filesystem_only": True, "process_state_preserved": False,
                  "mounts": [], "cleanup_status": "not_requested"}
        _write_json(directory / "request.json", record)
        try:
            committed = self._docker(command, timeout=180, check=False)
            (directory / "stdout.bin").write_bytes(committed.stdout)
            (directory / "stderr.bin").write_bytes(committed.stderr)
            record["returncode"] = committed.returncode
            stdout_text = committed.stdout.decode(errors="replace")
            image_ids = re.findall(r"^sha256:[0-9a-f]{64}$", stdout_text, flags=re.MULTILINE)
            record["image_id"] = image_ids[0] if len(image_ids) == 1 else None
            record["stdout_non_image_lines"] = [line for line in stdout_text.splitlines()
                                                 if line != record["image_id"]]
            if committed.returncode or len(image_ids) != 1:
                raise RuntimeError("Docker checkpoint commit failed; see checkpoint transport logs")
        except (OSError, subprocess.SubprocessError, RuntimeError) as error:
            record["error"] = type(error).__name__ + ": " + str(error)
            raise
        finally:
            record["elapsed_seconds"] = time.monotonic() - started
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(directory / "result.json", record)
        self.checkpoints.append(record)
        self._persist()
        return dict(record)

    def cleanup_checkpoint(self, image_id: str) -> dict:
        """Remove only an image created by this instance; keep all evidence logs.

        This can be called after ``close()``. No force flag is used: an image in
        use by a remaining paired-run container is retained and the refusal is
        recorded so the caller can retry after closing those containers.
        """
        matches = [record for record in self.checkpoints if record.get("image_id") == image_id]
        if not matches or image_id == self.image_id:
            raise ValueError("Refusing to remove an image not created as this container's checkpoint")
        if all(record["cleanup_status"] == "removed" for record in matches):
            return {"image_id": image_id, "status": "already_removed"}
        command = ["image", "rm", image_id]
        result = {"image_id": image_id, "docker_argv": ["docker", *command],
                  "requested_at": datetime.now(timezone.utc).isoformat()}
        try:
            removed = self._docker(command, timeout=60, check=False)
            result.update(returncode=removed.returncode, stdout=removed.stdout.decode(errors="replace"),
                          stderr=removed.stderr.decode(errors="replace"),
                          status="removed" if removed.returncode == 0 else "retained")
        except (OSError, subprocess.SubprocessError) as error:
            result.update(returncode=None, status="retained", error=type(error).__name__ + ": " + str(error))
        for record in matches:
            record["cleanup_status"] = result["status"]
            record.setdefault("cleanup_attempts", []).append(result)
            _write_json(self.output / "checkpoints" / record["label"] / "result.json", record)
        self._persist()
        return result

    def reset(self) -> None:
        """Restore the pinned image exactly, including external /tmp state."""
        self.close()
        self._start()

    def close(self) -> None:
        if not self.closed and self.name:
            error = None
            try:
                result = self._docker(["rm", "--force", self.name], timeout=30, check=False)
                if result.returncode:
                    error = result.stderr.decode(errors="replace")
            except (OSError, subprocess.SubprocessError) as exc:
                error = type(exc).__name__ + ": " + str(exc)
            finally:
                self.closed = True
                self.lifecycle.append({"event": "close", "name": self.name,
                                       "cleanup_error": error})
                self._persist()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

