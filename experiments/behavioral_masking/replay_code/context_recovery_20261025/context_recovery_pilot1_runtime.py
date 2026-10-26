"""Explicit, offline replay and execution; raw exit codes are never verdicts."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import tomllib

from tramask_pilot.runtime import Container
from tramask_pilot.submission_state import validate_submission_state
from tramask_rerun.runtime import _checkpoint, _environment, _path, _run, _timeout
from tramask_rerun.replay_v02 import INPUT_NAMES, replay_case


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "results/behavioral_masking/20261025_context_recovery_pilot1_r01"
DEFAULT_CHECKPOINTS = ROOT / "experiments/behavioral_masking/replay_code/checkpoints_20261025.json"
GIT = "git -c safe.directory=/app -C /app --literal-pathspecs"


def _read(path):
    return json.loads(Path(path).read_bytes())


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _receipt(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _command(value):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("command_requires_nonempty_exact_shell_text")
    return value


def _local(value, base, *, directory=False):
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("local_path_requires_string")
    path = Path(value)
    path = (path if path.is_absolute() else base / path).resolve(strict=True)
    if directory != path.is_dir() or (not directory and not path.is_file()):
        raise ValueError("expected_local_directory" if directory else "expected_regular_local_file")
    return str(path)


def _repository_path(value):
    if (not isinstance(value, str) or not value or "\0" in value or "\n" in value
            or str(PurePosixPath(value)) != value or PurePosixPath(value).is_absolute()
            or any(part in {"..", ".git"} for part in PurePosixPath(value).parts)):
        raise ValueError("invalid_repository_relative_path")
    return value


def _state_valid(report, checkpoint, base_commit, patch_sha256):
    return (report.get("submission_state_status") == "matched"
            and all(report.get(key) is True for key in ("submitted_commit_tree_matches",
                "working_tree_matches_submitted_commit", "index_tree_matches_submitted_commit"))
            and report.get("subject_files_or_real_index_patched") is False
            and report.get("image_id") == checkpoint["image_id"]
            and report.get("runtime_initial_head") == checkpoint["head"]
            and report.get("base_commit") == base_commit
            and report.get("submitted_patch_sha256") == patch_sha256)


def _validated_receipt(receipt):
    if not isinstance(receipt, dict) or _receipt(receipt["path"]) != receipt:
        raise ValueError("checkpoint_validation_receipt_changed")
    return Path(receipt["path"])


def patch_paths(text):
    """Use the official grader's ordered diff-header rule, with path validation."""
    seen, result = set(), []
    for line in text.splitlines():
        match = re.match(r'^diff --git (?:"?a/(.*?)"?) (?:"?b/(.*?)"?)$', line)
        path = match.group(2) if match else line[6:] if line.startswith(("+++ b/", "--- a/")) else None
        if path and path != "/dev/null" and path not in seen:
            # Escaped Git filenames need a dedicated parser, never a guessed path.
            if '"' in path or "\\" in path:
                raise ValueError("escaped_patch_path_requires_explicit_support")
            result.append(_repository_path(path))
            seen.add(path)
    if text.strip() and not result:
        raise ValueError("nonempty_patch_without_supported_paths")
    return result


def validate_plan(plan, *, base_directory=None):
    """Validate local inputs before creating output or contacting Docker."""
    if not isinstance(plan, dict):
        raise ValueError("plan_must_be_object")
    required = {"checkpoint", "checkpoint_validation", "base_commit", "implementation", "task_directory",
                "input_directory", "mode", "command", "timeout"}
    allowed = required | {"build_commands", "files", "env", "requires_build", "workdir",
                          "build_timeout", "resources", "production_paths"}
    if required - plan.keys() or plan.keys() - allowed:
        raise ValueError("missing_or_unknown_plan_fields: " + str(sorted((required - plan.keys()) | (plan.keys() - allowed))))
    base = Path(base_directory or Path.cwd()).resolve()
    result = dict(plan)
    result["checkpoint"] = _checkpoint(plan["checkpoint"])
    if not isinstance(plan["base_commit"], str) or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", plan["base_commit"]):
        raise ValueError("base_commit_requires_full_git_object_id")
    result["base_commit"] = plan["base_commit"].lower()
    if plan["implementation"] not in {"delivered", "reference"} or plan["mode"] not in {"agent", "verifier"}:
        raise ValueError("unsupported_implementation_or_mode")
    for key in ("task_directory", "input_directory"):
        result[key] = _local(plan[key], base, directory=True)
    raw = Path(result["input_directory"])
    for name in INPUT_NAMES:
        _local(str(raw / name), base)
    config = tomllib.loads((raw / "task.toml").read_text())
    if config["metadata"]["base_commit_hash"].lower() != result["base_commit"]:
        raise ValueError("plan_base_differs_from_raw_task")
    qualification_path = _local(plan["checkpoint_validation"], base)
    qualification = _read(qualification_path)
    report = _read(_validated_receipt(qualification["validation_report"]))
    observation = _validated_receipt(qualification["validation_observation"])
    _validated_receipt(qualification["checkpoint_reference"])
    patch_receipt = _receipt(raw / "model.patch")
    if (qualification.get("passed") is not True
            or qualification.get("checkpoint") != result["checkpoint"]
            or qualification.get("base_commit") != result["base_commit"]
            or qualification["model_patch"]["sha256"] != patch_receipt["sha256"]
            or report.get("observation_sha256") != _receipt(observation)["sha256"]
            or not _state_valid(report, result["checkpoint"], result["base_commit"], patch_receipt["sha256"])):
        raise ValueError("fresh_checkpoint_validation_not_passed_or_not_bound_to_plan")
    result["checkpoint_validation"] = qualification_path
    task = Path(result["task_directory"])
    if plan["implementation"] == "reference":
        _local(str(task / "solution/solution.patch"), base)
    if plan["mode"] == "verifier":
        _local(str(task / "tests/test.patch"), base)
        official = _read(task / "tests/config.json")
        if official["base_commit"].lower() != result["base_commit"]:
            raise ValueError("official_verifier_base_differs_from_plan")
        patch_paths((task / "tests/test.patch").read_text())
    result["command"] = _command(plan["command"])
    result["timeout"] = _timeout(plan["timeout"])
    result["build_timeout"] = _timeout(plan.get("build_timeout", result["timeout"]))
    builds = plan.get("build_commands", [])
    if not isinstance(builds, list):
        raise ValueError("build_commands_must_be_list")
    result["build_commands"] = [_command(command) for command in builds]
    requires_build = plan.get("requires_build", False)
    if not isinstance(requires_build, bool) or (requires_build and not builds):
        raise ValueError("requires_build_needs_explicit_build_commands")
    result["requires_build"] = requires_build
    result["env"] = _environment(plan.get("env"))
    workdir = plan.get("workdir", "/app")
    if workdir not in {"/app", "/tmp"}:
        _path(workdir)
    result["workdir"] = workdir
    files = plan.get("files", [])
    if not isinstance(files, list):
        raise ValueError("files_must_be_explicit_source_destination_list")
    result["files"] = []
    for row in files:
        if not isinstance(row, dict) or set(row) != {"source", "destination"}:
            raise ValueError("file_requires_source_and_destination")
        result["files"].append({"source": _local(row["source"], base), "destination": _path(row["destination"])})
    destinations = [row["destination"] for row in result["files"]]
    if len(set(destinations)) != len(destinations):
        raise ValueError("duplicate_destination")
    if plan["implementation"] == "reference":
        production = {"/app/" + path for path in patch_paths((task / "solution/solution.patch").read_text())}
        if production.intersection(destinations):
            raise ValueError("supplied_files_must_not_override_reference_solution")
    if plan["mode"] == "verifier":
        official_paths = {"/app/" + path for path in patch_paths((task / "tests/test.patch").read_text())}
        if official_paths.intersection(destinations):
            raise ValueError("supplied_files_must_not_override_official_verifier_tests")
    resources = plan.get("resources", {})
    if not isinstance(resources, dict) or resources.keys() - {"cpus", "memory", "pids_limit"}:
        raise ValueError("unsupported_container_resources")
    cpus, memory, pids = resources.get("cpus", 2), resources.get("memory", "8g"), resources.get("pids_limit", 1024)
    if (isinstance(cpus, bool) or not isinstance(cpus, (int, float)) or not math.isfinite(cpus) or cpus <= 0
            or not isinstance(memory, str) or not re.fullmatch(r"[1-9][0-9]*(?:[kmgtKMGT])?", memory)
            or isinstance(pids, bool) or not isinstance(pids, int) or pids <= 0):
        raise ValueError("invalid_container_resources")
    result["resources"] = dict(resources)
    production = plan.get("production_paths", [])
    if not isinstance(production, list):
        raise ValueError("production_paths_must_be_list")
    result["production_paths"] = [_repository_path(path) for path in production]
    return result


# One path per preparation record. A missing HEAD preimage is the official
# reset_paths removal branch; every other Git failure stops preparation.
_RESET_PATH = r'''
import json,os,shutil,subprocess,sys
path=sys.argv[1];git=['git','-c','safe.directory=/app','-C','/app','--literal-pathspecs']
r=subprocess.run(git+['ls-tree','-z','HEAD','--',path],capture_output=True)
sys.stdout.buffer.write(r.stdout);sys.stderr.buffer.write(r.stderr)
print(json.dumps({'operation':'ls-tree','path':path,'returncode':r.returncode}),flush=True)
if r.returncode:sys.exit(r.returncode)
if r.stdout:
    r=subprocess.run(git+['checkout','-q','HEAD','--',path])
    print(json.dumps({'operation':'checkout','path':path,'returncode':r.returncode}),flush=True)
    sys.exit(r.returncode)
target='/app/'+path
parent=os.path.dirname(target)
while parent!='/app':
    if os.path.islink(parent):raise RuntimeError('symlink_parent_of_reset_path')
    parent=os.path.dirname(parent)
if os.path.islink(target) or os.path.isfile(target):os.unlink(target)
elif os.path.isdir(target):shutil.rmtree(target)
elif os.path.lexists(target):raise RuntimeError('unsupported_reset_path_kind')
print(json.dumps({'operation':'remove_absent_HEAD_preimage','path':path,'returncode':0}),flush=True)
'''

_COPY_PARENT = r'''
import os,sys
path=sys.argv[1];parent=os.path.dirname(path)
current='/'
for part in path.lstrip('/').split('/'):
    current=os.path.join(current,part)
    if os.path.islink(current):raise RuntimeError('copy_path_must_not_follow_symlink')
if os.path.isdir(path):raise RuntimeError('file_destination_is_directory')
os.makedirs(parent,exist_ok=True)
'''

_VERIFY_COPY = r'''
import hashlib,json,sys
data=open(sys.argv[1],'rb').read();actual=hashlib.sha256(data).hexdigest()
print(json.dumps({'path':sys.argv[1],'bytes':len(data),'sha256':actual}))
if actual!=sys.argv[2]:raise RuntimeError('docker_copy_bytes_changed')
'''

_PRODUCTION_SNAPSHOT = r'''
import hashlib,json,os,stat,sys
root=sys.argv[1];rows=[]
for path in sys.argv[2:]:
    target=os.path.join(root,path)
    row={'path':path,'exists':False,'kind':'absent','bytes':None,'sha256':None}
    try:info=os.lstat(target)
    except FileNotFoundError:
        rows.append(row)
        continue
    row.update(exists=True,mode=stat.S_IMODE(info.st_mode))
    if stat.S_ISREG(info.st_mode):
        row['kind']='file'
        with open(target,'rb') as stream:data=stream.read()
    elif stat.S_ISLNK(info.st_mode):
        row['kind']='symlink'
        row['link_target']=os.readlink(target)
        data=os.fsencode(row['link_target'])
    else:
        row['kind']='directory' if stat.S_ISDIR(info.st_mode) else 'special'
        rows.append(row)
        continue
    row.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    rows.append(row)
print(json.dumps({'paths':rows,'hash_policy':'file_bytes_or_symlink_target_bytes'}))
'''


def _python(script, *args):
    return shlex.join(["python3", "-I", "-c", script, *args])


def _succeeded(record):
    return (record.get("returncode") == 0 and record.get("status") == "completed"
            and not any(record.get(key) for key in ("timed_out", "transport_error", "execution_error")))


class _PreparationFailed(Exception):
    pass


def execute_plan(plan, out, *, base_directory=None):
    plan = validate_plan(plan, base_directory=base_directory)
    out = Path(out).resolve()
    sources = [Path(row["source"]) for row in plan["files"]]
    sources += [Path(plan[key]) for key in ("task_directory", "input_directory")]
    if any(source == out or source.is_relative_to(out) or out.is_relative_to(source) for source in sources):
        raise ValueError("output_must_be_disjoint_from_inputs")
    out.mkdir(parents=True, exist_ok=False)
    _write_new(out / "plan.json", plan)
    qualification = _read(plan["checkpoint_validation"])
    _write_new(out / "checkpoint_validation_binding.json", {
        "qualification": _receipt(plan["checkpoint_validation"]),
        **{key: qualification[key] for key in (
            "validation_report", "validation_observation", "checkpoint_reference", "model_patch")},
    })
    result = {"status": "preparing", "target_executed": False, "steps": [],
              "checkpoint": plan["checkpoint"], "implementation": plan["implementation"],
              "mode": plan["mode"], "exit_status_is_not_test_verdict": True,
              "production_diff_scope": plan["production_paths"] or "all_tracked_files_including_tests"}
    if plan["production_paths"]:
        result["production_snapshots"] = {}
    frozen = out / "inputs"
    frozen.mkdir()

    def freeze(source, name):
        source = Path(source)
        before = _receipt(source)
        target = frozen / name
        shutil.copyfile(source, target)
        target.chmod(stat.S_IMODE(source.stat().st_mode))
        after = _receipt(target)
        if (before["sha256"], before["bytes"]) != (after["sha256"], after["bytes"]):
            raise ValueError("input_changed_during_freeze")
        return target, {"source": before, "frozen": after}

    try:
        copies, receipts = [], []
        for i, row in enumerate(plan["files"]):
            path, receipt = freeze(row["source"], f"file_{i:03d}")
            copies.append((path, row["destination"]))
            receipts.append({"destination": row["destination"], **receipt})
        implementation_patch = None
        if plan["mode"] == "verifier" or plan["implementation"] == "reference":
            source = (Path(plan["task_directory"]) / "solution/solution.patch"
                      if plan["implementation"] == "reference" else Path(plan["input_directory"]) / "model.patch")
            implementation_patch, receipt = freeze(source, "implementation.patch")
            receipts.append(receipt)
        test_patch = None
        if plan["mode"] == "verifier":
            test_patch, receipt = freeze(Path(plan["task_directory"]) / "tests/test.patch", "test.patch")
            receipts.append(receipt)
        _write_new(out / "input_receipts.json", receipts)
        with Container(plan["checkpoint"]["image_id"], out / "container", plan["checkpoint"]["head"],
                       **plan["resources"]) as runtime:
            def command(label, text, *, timeout=None, required=True, workdir="/app"):
                directory = out / "steps" / f"{len(result['steps']):03d}_{label}"
                record = _run(runtime, text, timeout or plan["timeout"], directory, plan["env"], workdir)
                result["steps"].append({"label": label, "directory": str(directory), "execution": record})
                if required and not _succeeded(record):
                    result["failed_step"] = label
                    raise _PreparationFailed(label)
                return record

            def copy(source, destination, label):
                command(label + "_parent", _python(_COPY_PARENT, destination))
                directory = out / "steps" / f"{len(result['steps']):03d}_{label}_docker_cp"
                directory.mkdir(parents=True, exist_ok=False)
                argv = ["cp", str(source), runtime.name + ":" + destination]
                record = {"docker_argv": ["docker", *argv], "source": _receipt(source), "destination": destination}
                try:
                    process = runtime._docker(argv, timeout=60, check=False)
                    stdout, stderr = process.stdout, process.stderr
                    record.update(returncode=process.returncode, status="completed")
                except (OSError, subprocess.SubprocessError) as error:
                    stdout, stderr = getattr(error, "stdout", None) or b"", getattr(error, "stderr", None) or b""
                    record.update(returncode=None, status="transport_error", error_type=type(error).__name__)
                for name, data in (("stdout", stdout), ("stderr", stderr)):
                    (directory / (name + ".bin")).write_bytes(data if isinstance(data, bytes) else data.encode())
                _write_new(directory / "execution.json", record)
                result["steps"].append({"label": label + "_docker_cp", "directory": str(directory), "execution": record})
                if not _succeeded(record):
                    result["failed_step"] = label + "_docker_cp"
                    raise _PreparationFailed(result["failed_step"])
                command(label + "_verify", _python(_VERIFY_COPY, destination, record["source"]["sha256"]))

            try:
                if implementation_patch is not None:
                    command("reset_base", GIT + " reset --hard " + plan["base_commit"])
                    command("clean_untracked", GIT + " clean -fd")
                    remote = runtime.scratch + "/implementation.patch"
                    copy(implementation_patch, remote, "implementation_patch")
                    command("apply_implementation", GIT + " apply --whitespace=nowarn --allow-empty " + shlex.quote(remote))
                if test_patch is not None:
                    for i, path in enumerate(patch_paths(test_patch.read_text())):
                        command(f"reset_official_test_path_{i:03d}", _python(_RESET_PATH, path))
                    remote = runtime.scratch + "/test.patch"
                    copy(test_patch, remote, "official_test_patch")
                    command("apply_official_tests", GIT + " apply --whitespace=nowarn --allow-empty " + shlex.quote(remote))
                for i, (source, destination) in enumerate(copies):
                    copy(source, destination, f"agent_file_{i:03d}")
                if plan["production_paths"]:
                    result["production_snapshots"]["before_build"] = command(
                        "production_snapshot_before_build",
                        _python(_PRODUCTION_SNAPSHOT, "/app", *plan["production_paths"]))
                for i, build in enumerate(plan["build_commands"]):
                    command(f"build_{i:03d}", build, timeout=plan["build_timeout"], workdir=plan["workdir"])
                result["target_executed"] = True
                result["execution"] = command("target", plan["command"], required=False, workdir=plan["workdir"])
                result["status"] = result["execution"]["status"]
            except _PreparationFailed:
                result["status"] = "preparation_failed"
            finally:
                if plan["production_paths"]:
                    result["production_snapshots"]["final"] = command(
                        "production_snapshot_final",
                        _python(_PRODUCTION_SNAPSHOT, "/app", *plan["production_paths"]), required=False)
                paths = " ".join(shlex.quote(path) for path in plan["production_paths"]) or "."
                result["production_diff"] = command("final_production_diff", GIT + " diff --binary " + plan["base_commit"] + " -- " + paths, required=False)
                result["final_head"] = command("final_head", GIT + " rev-parse HEAD", required=False)
                result["final_status"] = command("final_status", GIT + " status --porcelain=v1", required=False)
    except Exception as error:
        result.update(status="execution_error", error_type=type(error).__name__, error=str(error))
    _write_new(out / "result.json", result)
    return result


def replay_screen(screen_id, *, run=DEFAULT_RUN, checkpoint_index=DEFAULT_CHECKPOINTS,
                  attempt="replay_attempt_001"):
    """Cache metadata requires fresh validation; it carries no experimental labels."""
    if not isinstance(screen_id, str) or not re.fullmatch(r"S[0-9]{3,}", screen_id):
        raise ValueError("invalid_screen_id")
    if not isinstance(attempt, str) or not re.fullmatch(r"replay_attempt_[0-9]{3,}", attempt):
        raise ValueError("attempt_requires_explicit_replay_attempt_number")
    run = Path(run).resolve(strict=True)
    matches = [row for row in _read(run / "screening_order.json")["trials"] if row["screen_id"] == screen_id]
    if len(matches) != 1:
        raise ValueError("screen_id_must_identify_one_trial")
    case = matches[0]
    destination = run / "cases" / screen_id
    pointer = destination / "checkpoint.json"
    if pointer.exists():
        raise FileExistsError(pointer)
    inputs = {name: _receipt(Path(case["input_directory"]) / name) for name in INPUT_NAMES}
    entries = _read(checkpoint_index)["checkpoints"]
    cached = [entry for entry in entries if entry["trial"] == case["trial"]]
    if len(cached) > 1:
        raise ValueError("duplicate_cached_trial")
    result = {"screen_id": screen_id, "trial": case["trial"], "base_commit": case["base_commit"],
              "input_directory": case["input_directory"], "task_directory": case["task_directory"],
              "raw_inputs": inputs, "fresh_validation_required": True}
    if cached:
        cached = cached[0]
        if cached["base_commit"] != case["base_commit"] or cached["image"] != case["image"]:
            raise ValueError("cached_checkpoint_identity_mismatch")
        for name, receipt in inputs.items():
            if any(receipt[key] != cached["raw_inputs"][name][key] for key in ("sha256", "bytes")):
                raise ValueError("cached_checkpoint_raw_input_mismatch")
        result.update(_checkpoint(cached["checkpoint"]), source="neutral_checkpoint_cache", cache_index=_receipt(checkpoint_index))
    else:
        attempt_directory = destination / attempt
        if attempt_directory.exists():
            raise FileExistsError("Replay attempt already exists; inspect it before choosing a new attempt")
        replay = replay_case({"id": screen_id, "image": case["image"], "base_commit": case["base_commit"]},
                             case["input_directory"], attempt_directory)
        checkpoint = replay.get("study_checkpoint")
        if not checkpoint:
            raise RuntimeError("Replay produced no complete checkpoint reference; inspect " + str(attempt_directory))
        if replay.get("state_validation_passed") is not True or checkpoint.get("state_validation_passed") is not True:
            raise RuntimeError("Replay checkpoint state validation did not pass; no usable pointer written: " + str(attempt_directory))
        result.update(_checkpoint(checkpoint), source="fresh_replay", replay_attempt=str(attempt_directory),
                      replay_checkpoint_reference=_receipt(attempt_directory / "checkpoint_reference.json"))
    _write_new(pointer, result)
    return result


def validate_screen(screen_id, *, run=DEFAULT_RUN):
    """Independently validate one checkpoint in a fresh clone, without repair."""
    if not isinstance(screen_id, str) or not re.fullmatch(r"S[0-9]{3,}", screen_id):
        raise ValueError("invalid_screen_id")
    run = Path(run).resolve(strict=True)
    rows = [row for row in _read(run / "screening_order.json")["trials"] if row["screen_id"] == screen_id]
    if len(rows) != 1:
        raise ValueError("screen_id_must_identify_one_trial")
    case = rows[0]
    pointer_path = run / "cases" / screen_id / "checkpoint.json"
    pointer_receipt = _receipt(pointer_path)
    pointer = _read(pointer_path)
    checkpoint = _checkpoint(pointer)
    if pointer["trial"] != case["trial"] or pointer["base_commit"] != case["base_commit"]:
        raise ValueError("checkpoint_identity_differs_from_screening_row")
    patch = Path(case["input_directory"]) / "model.patch"
    patch_receipt = _receipt(patch)
    if any(patch_receipt[key] != pointer["raw_inputs"]["model.patch"][key] for key in ("sha256", "bytes")):
        raise ValueError("checkpoint_original_patch_changed")
    out = pointer_path.parent / "checkpoint_validation"
    out.mkdir(parents=True, exist_ok=False)
    qualification = {"screen_id": screen_id, "trial": case["trial"], "checkpoint": checkpoint,
                     "base_commit": case["base_commit"], "model_patch": patch_receipt,
                     "checkpoint_reference": pointer_receipt, "passed": False}
    try:
        with Container(checkpoint["image_id"], out / "container", checkpoint["head"]) as container:
            report = validate_submission_state(container, patch, out / "validation", base_commit=case["base_commit"])
        qualification["validation_report"] = _receipt(out / "validation/report.json")
        qualification["validation_observation"] = _receipt(out / "validation/observation.json")
        qualification["passed"] = _state_valid(report, checkpoint, case["base_commit"], patch_receipt["sha256"])
        if _receipt(pointer_path) != pointer_receipt or _receipt(patch) != patch_receipt:
            raise ValueError("checkpoint_or_patch_changed_during_validation")
    except Exception as error:
        qualification.update(passed=False, error_type=type(error).__name__, error=str(error))
    _write_new(out / "qualification.json", qualification)
    return qualification
