"""Execute one variant in a fresh clone of an explicit submission checkpoint.

This module does not select a checkpoint, restore historical tests, infer test
verdicts, or classify masking. Callers own variant construction and semantic
review. All subject execution and file access happens in the isolated container.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess

from tramask_pilot.runtime import Container


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _path(value: str) -> str:
    if not isinstance(value, str) or "\0" in value:
        raise ValueError("invalid_subject_path")
    path = PurePosixPath(value)
    if (str(path) != value or not path.is_absolute() or ".." in path.parts
            or len(path.parts) < 3 or path.parts[1] not in {"app", "tmp"}):
        raise ValueError("subject_path_requires_exact_absolute_app_or_tmp_file")
    if any(part in {".git", ".aws", ".codex", ".agents"} for part in path.parts):
        raise ValueError("private_subject_path")
    return value


def _checkpoint(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("checkpoint_requires_image_id_and_head")
    image, head = value.get("image_id"), value.get("head")
    if not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("checkpoint_image_must_be_immutable")
    if not isinstance(head, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", head):
        raise ValueError("checkpoint_head_must_be_full_object_id")
    return {"image_id": image, "head": head.lower()}


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("timeout_requires_positive_finite_task_seconds")
    return value


def _environment(value: dict | None) -> dict:
    value = {} if value is None else value
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
        or not isinstance(item, str) or "\0" in item for key, item in value.items()
    ):
        raise ValueError("invalid_environment_overlay")
    return dict(value)


def _file_specs(files: dict | None) -> list[dict]:
    """Bind complete replacement bytes to the exact checkpoint predecessor."""
    files = {} if files is None else files
    if not isinstance(files, dict):
        raise ValueError("files_must_map_absolute_paths_to_specs")
    result = []
    for path, spec in sorted(files.items()):
        _path(path)
        if not isinstance(spec, dict) or set(spec) - {"content", "before_sha256", "new_file"}:
            raise ValueError("file_requires_content_and_before_sha256_or_explicit_new_file")
        content = spec.get("content")
        if not isinstance(content, str):
            raise ValueError("replacement_content_must_be_complete_text")
        is_new = spec.get("new_file", False)
        if type(is_new) is not bool:
            raise ValueError("new_file_must_be_boolean")
        before = spec.get("before_sha256")
        if is_new:
            if before is not None:
                raise ValueError("new_file_must_not_have_predecessor_hash")
        elif not isinstance(before, str) or not re.fullmatch(r"[0-9a-f]{64}", before):
            raise ValueError("existing_file_requires_before_sha256")
        raw = content.encode("utf-8")
        result.append({"path": path, "new_file": is_new, "before_sha256": before,
                       "after_sha256": _sha(raw), "content_base64": base64.b64encode(raw).decode()})
    names = [row["path"] for row in result]
    if any(a != b and b.startswith(a + "/") for a in names for b in names):
        raise ValueError("file_directory_collision")
    return result


# Only standard-library operations on explicitly requested files. Every write
# is preflighted before the first file changes; symlink ancestors and leaves are
# refused, including /app and /tmp themselves. No archive extraction is used.
_FILES = r'''
import base64,hashlib,json,os,pathlib,stat,sys,tempfile
r=json.load(sys.stdin)
def digest(data):return hashlib.sha256(data).hexdigest()
def checked(name):
    p=pathlib.PurePosixPath(name)
    if (str(p)!=name or not p.is_absolute() or '..' in p.parts or len(p.parts)<3
            or p.parts[1] not in {'app','tmp'} or any(x in {'.git','.aws','.codex','.agents'} for x in p.parts)):
        raise ValueError('unsafe_subject_path')
    cursor='/'
    for index,part in enumerate(p.parts[1:]):
        cursor=os.path.join(cursor,part)
        try:info=os.lstat(cursor)
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode):raise ValueError('symlink_in_subject_path')
        if index<len(p.parts)-2 and not stat.S_ISDIR(info.st_mode):raise ValueError('non_directory_ancestor')
    return name
def inspect(name,include=False):
    name=checked(name)
    try:info=os.lstat(name)
    except FileNotFoundError:return {'path':name,'status':'missing','sha256':None}
    if not stat.S_ISREG(info.st_mode):raise ValueError('subject_path_not_regular_file')
    with open(name,'rb') as stream:data=stream.read()
    after=os.lstat(name)
    if (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError('subject_file_changed_during_read')
    row={'path':name,'status':'present','sha256':digest(data),'bytes':len(data),'mode':stat.S_IMODE(info.st_mode)}
    if include:row['content_base64']=base64.b64encode(data).decode()
    return row
result={'status':'complete','files':[]}
try:
    if r['operation']=='read':
        for name in r['paths']:result['files'].append(inspect(name,True))
    elif r['operation']=='write':
        planned=[]
        names=[row['path'] for row in r['files']]
        if len(names)!=len(set(names)) or any(a!=b and b.startswith(a+'/') for a in names for b in names):
            raise ValueError('file_directory_collision')
        for row in r['files']:
            before=inspect(row['path'])
            if row['new_file']:
                if before['status']!='missing':raise ValueError('new_file_already_exists')
            elif before['status']!='present' or before['sha256']!=row['before_sha256']:
                raise ValueError('predecessor_hash_mismatch')
            data=base64.b64decode(row['content_base64'],validate=True)
            if digest(data)!=row['after_sha256']:raise ValueError('replacement_hash_mismatch')
            planned.append((row,before,data))
        for row,before,data in planned:
            name=checked(row['path']);parent=os.path.dirname(name)
            os.makedirs(parent,exist_ok=True);checked(name)
            fd,temporary=tempfile.mkstemp(prefix='.tramask-write-',dir=parent)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                os.chmod(temporary,before.get('mode',0o644))
                os.replace(temporary,name)
            finally:
                if os.path.exists(temporary):os.unlink(temporary)
            actual=inspect(name)
            if actual['sha256']!=row['after_sha256']:raise ValueError('write_verification_failed')
            result['files'].append({'path':name,'new_file':row['new_file'],
                'before_sha256':before['sha256'],'after_sha256':actual['sha256'],
                'bytes':actual['bytes'],'mode':actual['mode']})
    else:raise ValueError('unknown_file_operation')
except Exception as error:
    result.update(status='error',error_type=type(error).__name__,error=str(error))
print(json.dumps(result))
'''


# Explicit /bin/sh, no login-shell defaults, task-specific timer, independent
# byte streams, and only this action's process group is killed on timeout.
_EXECUTE = r'''
import hashlib,json,os,signal,subprocess,sys,time
r=json.load(sys.stdin);started=time.monotonic()
result={'returncode':None,'timed_out':False,'transport_error':False,'execution_error':False}
stdout=b'';stderr=b''
try:
    p=subprocess.Popen(['/bin/sh','-c',r['command']],cwd=r['workdir'],env=os.environ|r['env'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:stdout,stderr=p.communicate(timeout=r['timeout'])
    except subprocess.TimeoutExpired:
        result['timed_out']=True
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        try:stdout,stderr=p.communicate(timeout=10)
        except subprocess.TimeoutExpired as error:
            stdout=error.stdout or b'';stderr=error.stderr or b''
            result.update(execution_error=True,error='descendant_pipes_remained_open_after_group_kill')
            p.stdout.close();p.stderr.close()
    result['returncode']=p.returncode
except Exception as error:
    result.update(execution_error=True,error_type=type(error).__name__,error=str(error))
for key,data in [('stdout',stdout),('stderr',stderr)]:
    with open(r[key],'wb') as stream:stream.write(data)
    result[key+'_sha256']=hashlib.sha256(data).hexdigest()
    result[key+'_bytes']=len(data)
result['elapsed_seconds']=time.monotonic()-started
print(json.dumps(result))
'''


def _control_json(runtime, script: str, request: dict, out: Path, *, timeout: float = 180) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    _write(out / "request.json", request)
    try:
        # Isolated Python prevents a repository json.py or inherited PYTHONPATH
        # from shadowing the standard-library helpers that attest file bytes.
        process = runtime._control(["python3", "-I", "-c", script], input_bytes=json.dumps(request).encode(),
                                   timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        for key in ("stdout", "stderr"):
            raw = getattr(error, key, None) or b""
            (out / ("transport." + key + ".bin")).write_bytes(raw if isinstance(raw, bytes) else raw.encode())
        result = {"status": "transport_error", "transport_error": True,
                  "error_type": type(error).__name__}
        _write(out / "result.json", result)
        return result
    (out / "transport.stdout.bin").write_bytes(process.stdout)
    (out / "transport.stderr.bin").write_bytes(process.stderr)
    try:
        if process.returncode:
            raise ValueError("control_nonzero_exit")
        result = json.loads(process.stdout)
        if not isinstance(result, dict):
            raise ValueError("control_result_not_object")
    except (ValueError, TypeError) as error:
        result = {"status": "transport_error", "transport_error": True,
                  "error_type": type(error).__name__, "control_returncode": process.returncode}
    _write(out / "result.json", result)
    return result


def _read_files(runtime, paths, out: Path) -> dict:
    paths = list(dict.fromkeys(_path(path) for path in paths))
    result = _control_json(runtime, _FILES, {"operation": "read", "paths": paths}, out / "control")
    records = []
    for record in result.get("files", []):
        row = dict(record)
        encoded = row.pop("content_base64", None)
        if encoded is not None:
            raw = base64.b64decode(encoded, validate=True)
            if _sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
                raise ValueError("exported_bytes_receipt_mismatch")
            saved = out / "files" / row["path"].lstrip("/")
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(raw)
            row["raw_path"] = str(saved.resolve())
            try:
                row["content"] = raw.decode("utf-8")
            except UnicodeDecodeError:
                row["text_status"] = "not_utf8"
        records.append(row)
    result = {**result, "files": records}
    _write(out / "manifest.json", result)
    return result


def export_checkpoint_files(checkpoint: dict, out, paths, *, resources: dict | None = None) -> dict:
    """Export only explicit file paths from a fresh, immutable checkpoint clone.

    Missing paths remain missing; historical snapshots are never consulted.
    Raw bytes and SHA256 receipts are preserved even for non-UTF8 files.
    """
    checkpoint = _checkpoint(checkpoint)
    paths = list(dict.fromkeys(_path(path) for path in paths))
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    result = {"checkpoint": checkpoint, "requested_paths": paths}
    _write(out / "plan.json", result)
    try:
        with Container(checkpoint["image_id"], out / "container", checkpoint["head"], **(resources or {})) as runtime:
            result.update(_read_files(runtime, paths, out / "export"))
    except Exception as error:
        result.update(status="export_error", error_type=type(error).__name__, error=str(error))
    _write(out / "result.json", result)
    return result


def _run(runtime, command: str, timeout: float, out: Path, env: dict, workdir: str) -> dict:
    remote = runtime.scratch + "/" + out.name
    request = {"command": command, "timeout": timeout, "env": env, "workdir": workdir,
               "stdout": remote + ".stdout", "stderr": remote + ".stderr"}
    result = _control_json(runtime, _EXECUTE, request, out / "control", timeout=timeout + 30)
    result.update(command=command, command_sha256=_sha(command.encode()), timeout_seconds=timeout,
                  shell="/bin/sh", working_directory=workdir, environment_overlay=env,
                  checkpoint_image_id=runtime.image_id, container=runtime.name,
                  timeout_cleanup="SIGKILL action process group; no container restart")
    (out / "command.sh").write_text(command)
    if not result.get("transport_error"):
        for key in ("stdout", "stderr"):
            local = out / (key + ".bin")
            try:
                runtime.copy_from(request[key], local)
                raw = local.read_bytes()
                if _sha(raw) != result[key + "_sha256"] or len(raw) != result[key + "_bytes"]:
                    raise ValueError("execution_output_receipt_mismatch")
                result[key] = raw.decode("utf-8", errors="replace")
                result["raw_" + key] = str(local.resolve())
                (out / (key + ".txt")).write_text(result[key])
            except Exception as error:
                result.update(transport_error=True, error_type=type(error).__name__, error=str(error))
    result["status"] = ("transport_error" if result.get("transport_error") else
                        "timeout" if result.get("timed_out") else
                        "execution_error" if result.get("execution_error") else "completed")
    result["exit_status_is_not_test_verdict"] = True
    _write(out / "execution.json", result)
    runtime.records.append(result)
    runtime._persist()
    return result


def execute_variant(checkpoint: dict, out, command: str, timeout: float, *,
                    files: dict | None = None, observation_paths=(), build_commands=(),
                    env: dict | None = None, workdir: str = "/app",
                    resources: dict | None = None, production_paths=(),
                    generated_runtime: bool = False) -> dict:
    """Execute one raw or instrumented P/Q variant in its own clean container.

    ``files`` maps /app or /tmp paths to complete replacement specifications:
    ``{content: str, before_sha256: str}`` for replacements, or
    ``{content: str, new_file: True}`` for explicitly new files. Hashes always
    refer to the untouched checkpoint, including for Q and instrumented variants.
    The caller composes Q, context edits and instrumentation before this call.

    ``generated_runtime=True`` requires a build command whenever supplied files
    touch ``production_paths``. Each build must finish with exit 0; otherwise no
    test runs against a potentially stale binary. All commands share the task
    timeout, run in /bin/sh, and retain independent byte-exact stdout/stderr.
    A nonzero test exit is a completed execution, never an inferred test failure.
    """
    checkpoint, timeout = _checkpoint(checkpoint), _timeout(timeout)
    if not isinstance(command, str) or not command or "\0" in command:
        raise ValueError("command_requires_nonempty_exact_shell_text")
    if workdir not in {"/app", "/tmp"}:
        _path(workdir)
    env = _environment(env)
    specs = _file_specs(files)
    observations = list(dict.fromkeys(_path(path) for path in observation_paths))
    production = {_path(path) for path in production_paths}
    if not isinstance(build_commands, (list, tuple)) or any(
        not isinstance(item, str) or not item or "\0" in item for item in build_commands
    ):
        raise ValueError("build_commands_require_exact_shell_strings")
    if generated_runtime and production.intersection(row["path"] for row in specs) and not build_commands:
        raise ValueError("changed_generated_runtime_source_requires_build_command")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    public_specs = [{k: v for k, v in row.items() if k != "content_base64"} for row in specs]
    result = {"checkpoint": checkpoint, "status": "prepared", "files": public_specs,
              "builds": [], "execution": None, "observations": [],
              "claim_scope": "Execution evidence only; no inferred test verdict, masking, or oracle qualification."}
    _write(out / "plan.json", {**result, "command": command, "timeout_seconds": timeout,
           "workdir": workdir, "env": env, "build_commands": list(build_commands),
           "observation_paths": observations, "production_paths": sorted(production),
           "generated_runtime": generated_runtime, "resources": resources or {}})
    try:
        with Container(checkpoint["image_id"], out / "container", checkpoint["head"], **(resources or {})) as runtime:
            writes = _control_json(runtime, _FILES, {"operation": "write", "files": specs}, out / "writes")
            result["file_receipts"] = writes
            if writes.get("status") != "complete":
                result.update(status="file_precondition_failed" if not writes.get("transport_error") else "transport_error")
            else:
                for index, build in enumerate(build_commands):
                    record = _run(runtime, build, timeout, out / f"build_{index:02d}", env, workdir)
                    result["builds"].append(record)
                    if record["status"] != "completed" or record["returncode"] != 0:
                        result["status"] = "build_failed"
                        break
                else:
                    record = _run(runtime, command, timeout, out / "test", env, workdir)
                    result["execution"] = record
                    result["status"] = record["status"]
                    if observations and not record.get("transport_error"):
                        captured = _read_files(runtime, observations, out / "observations")
                        result["observations"] = captured.get("files", [])
                        result["observation_export_status"] = captured["status"]
    except Exception as error:
        result.update(status="runtime_error", error_type=type(error).__name__, error=str(error))
    _write(out / "result.json", result)
    return result
