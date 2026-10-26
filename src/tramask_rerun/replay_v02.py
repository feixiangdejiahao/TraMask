"""Full terminal replay from explicitly supplied raw inputs, in a new attempt.

Nothing executes at import. This module has no implicit corpus/RUN lookup, never
patches a replay into matching, and never substitutes a selected historical test
context. Interrupted attempts are evidence, not an invitation to replay commands
again in the same directory.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tomllib

from tramask_pilot.runtime import Container
from tramask_pilot.submission_replay import ENV, INVENTORY, execute_action
from .replay_boundaries import resolve_submission_actions
from tramask_pilot.submission_state import validate_submission_state


INPUT_NAMES = ("instruction.md", "task.toml", "model.patch", "trajectory.json")


def _receipt(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _read(path):
    return json.loads(Path(path).read_bytes())


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _verify(receipt):
    if _receipt(receipt["path"]) != receipt:
        raise ValueError("attempt_artifact_receipt_changed: " + receipt["path"])


def inspect_image_availability(image: str) -> dict:
    """Read-only Docker image inspection; never pulls, starts or removes images."""
    if not isinstance(image, str) or not image or image.startswith("-") or "\0" in image:
        raise ValueError("invalid_image_reference")
    try:
        result = Container._docker(["image", "inspect", "--format", "{{.Id}}", image], timeout=30, check=False)
        resolved = result.stdout.decode(errors="replace").strip()
        available = result.returncode == 0 and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", resolved))
        return {"image": image, "available": available, "image_id": resolved if available else None,
                "returncode": result.returncode, "stderr": result.stderr.decode(errors="replace"),
                "operation": "read_only_image_inspect", "pull_attempted": False}
    except Exception as error:
        return {"image": image, "available": False, "image_id": None,
                "error_type": type(error).__name__, "operation": "read_only_image_inspect", "pull_attempted": False}


def resolve_task_base_commit(configured: str, case: dict) -> dict:
    """Resolve an original abbreviated task revision without rewriting its input."""
    full = case["base_commit"].lower()
    configured = configured.lower()
    if configured == full:
        return {"configured": configured, "resolved": full, "resolution": "already_full"}
    if (not re.fullmatch(r"[0-9a-f]{7,63}", configured)
            or len(configured) >= len(full) or not full.startswith(configured)):
        raise ValueError("case_identity_differs_from_explicit_task_configuration")
    # Git must establish that the short name is unambiguous in the actual image.
    command = ["run", "--rm", "--network", "none", "--entrypoint", "git", case["image"],
               "-C", "/app", "rev-parse", configured + "^{commit}"]
    result = Container._docker(command, timeout=60, check=False)
    resolved = result.stdout.decode(errors="replace").strip().lower()
    if result.returncode != 0 or resolved != full:
        raise ValueError("task_abbreviated_base_does_not_resolve_to_case_commit")
    return {"configured": configured, "resolved": resolved, "resolution": "git_in_original_image",
            "docker_argv": command, "stdout": result.stdout.decode(errors="replace"),
            "stderr": result.stderr.decode(errors="replace")}


# PID plus Linux start ticks distinguishes a surviving process from a reused
# numeric PID. The inventory helper excludes itself and never kills a process.
_PROCESSES = r'''
import json,os
rows=[];errors=[];own=os.getpid()
for value in sorted(os.listdir('/proc')):
    if not value.isdigit() or int(value)==own:continue
    try:
        text=open('/proc/'+value+'/stat').read();tail=text[text.rfind(')')+2:].split()
        raw=open('/proc/'+value+'/cmdline','rb').read()
        rows.append({'pid':int(value),'ppid':int(tail[1]),'pgid':int(tail[2]),'session':int(tail[3]),
            'state':tail[0],'start_ticks':int(tail[19]),
            'argv':[item.decode('utf-8','replace') for item in raw.split(b'\0') if item]})
    except (FileNotFoundError,ProcessLookupError):pass
    except Exception as error:errors.append({'pid':int(value),'error_type':type(error).__name__})
print(json.dumps({'processes':rows,'errors':errors,'observer_pid':own}))
'''


def _process_inventory(runtime, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    process = runtime._control(["python3", "-I", "-c", _PROCESSES], timeout=30, check=False)
    (out / "stdout.bin").write_bytes(process.stdout)
    (out / "stderr.bin").write_bytes(process.stderr)
    try:
        if process.returncode:
            raise ValueError("process_inventory_command_failed")
        result = json.loads(process.stdout)
        if not isinstance(result.get("processes"), list) or not isinstance(result.get("errors"), list):
            raise ValueError("invalid_process_inventory")
        result["status"] = "complete" if not result["errors"] else "partial"
    except (ValueError, TypeError, AttributeError) as error:
        result = {"status": "unavailable", "processes": [], "errors": [{"error_type": type(error).__name__}],
                  "returncode": process.returncode}
    _write_new(out / "inventory.json", result)
    return result


def _process_risks(baseline, terminal):
    identities = {(row["pid"], row["start_ticks"]) for row in baseline["processes"]}
    additional = [row for row in terminal["processes"] if (row["pid"], row["start_ticks"]) not in identities]
    active = [row for row in additional if row["state"] not in {"Z", "X", "x"}]
    available = baseline["status"] == terminal["status"] == "complete"
    return {"inventory_complete": available, "terminal_nonbaseline_processes": additional,
            "active_background_processes": active, "known_processes_quiescent": available and not active,
            "process_memory_captured_by_checkpoint": False,
            "interpretation": "Background processes are recorded without repair or termination; a checkpoint preserves filesystem bytes only."}


def inspect_attempt(out) -> dict:
    """Report reuse/resumability without creating or changing any artifact."""
    out = Path(out).resolve()
    if not out.exists():
        return {"status": "not_started", "directory": str(out), "can_start": True}
    if not out.is_dir():
        raise ValueError("attempt_path_is_not_directory")
    if (out / "completion.json").exists():
        completion = _read(out / "completion.json")
        for item in completion["receipts"]:
            _verify(item)
        return {"status": "complete", "directory": str(out), "can_reuse_recorded_result": True,
                "can_resume_commands": False, "completion": completion}
    checkpoint_path = out / "checkpoint.json"
    progress = sorted((out / "progress").glob("*.json")) if (out / "progress").exists() else []
    interrupted_artifacts = []
    def partial_record(path):
        try:
            return _read(path)
        except (OSError, ValueError) as error:
            interrupted_artifacts.append({"path": str(path), "error_type": type(error).__name__})
            return None
    checkpoint = partial_record(checkpoint_path) if checkpoint_path.exists() else None
    last_progress = partial_record(progress[-1]) if progress else None
    return {"status": "requires_new_attempt", "directory": str(out),
            "can_reuse_recorded_result": False, "can_resume_commands": False,
            "can_validate_saved_checkpoint_in_new_attempt": isinstance(checkpoint, dict) and bool(checkpoint.get("image_id")),
            "checkpoint": checkpoint, "last_progress": last_progress,
            "interrupted_artifacts": interrupted_artifacts,
            "reason": "An action may have changed state before its receipt was persisted. Do not replay it implicitly; preserve this attempt and choose an explicit new output directory."}


def _existing(out, case, inputs):
    state = inspect_attempt(out)
    if (out / "plan.json").exists():
        plan = _read(out / "plan.json")
        if plan["case_identity"] != {key: case[key] for key in ("id", "image", "base_commit")} or plan["source_inputs"] != inputs:
            raise ValueError("existing_attempt_input_or_case_mismatch")
    if state["status"] == "complete":
        return {**_read(out / "summary.json"), "study_checkpoint": _read(out / "checkpoint_reference.json"),
                "resumed": True, "resumability": state}
    return {"id": case["id"], "status": state["status"], "resumed": False, "resumability": state}


def replay_case(case: dict, input_dir, out) -> dict:
    """Replay all raw actions through the terminal submission boundary once.

    ``out`` is a single immutable attempt directory, not a corpus root. Inputs
    are frozen from the four explicit raw files before execution. Existing
    completed attempts are reused only after receipt verification. Partial
    attempts return resumability metadata; no action is silently rerun.
    """
    if (not isinstance(case, dict) or not all(isinstance(case.get(key), str) and case[key]
            for key in ("id", "image", "base_commit"))):
        raise ValueError("case_requires_id_image_base_commit")
    if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", case["base_commit"]):
        raise ValueError("case_base_commit_must_be_full_object_id")
    source, out = Path(input_dir).resolve(strict=True), Path(out).resolve()
    if out == source or source.is_relative_to(out) or out.is_relative_to(source):
        raise ValueError("input_and_attempt_directories_must_be_disjoint")
    inputs = {name: _receipt(source / name) for name in INPUT_NAMES}
    if out.exists():
        return _existing(out, case, inputs)
    raw = {name: (source / name).read_bytes() for name in INPUT_NAMES}
    if any(len(raw[name]) != item["bytes"] or hashlib.sha256(raw[name]).hexdigest() != item["sha256"]
           for name, item in inputs.items()):
        raise ValueError("input_changed_during_freeze")
    config = tomllib.loads(raw["task.toml"].decode())
    if config["environment"]["docker_image"] != case["image"]:
        raise ValueError("case_identity_differs_from_explicit_task_configuration")
    task_base = resolve_task_base_commit(config["metadata"]["base_commit_hash"], case)
    actions, boundary = resolve_submission_actions(json.loads(raw["trajectory.json"]))
    marker = {"id": boundary["last_requested_action_id"]}
    if (case["id"] == "HF001" and (boundary["kind"] != "explicit_unexecuted_submission_request"
            or boundary["executed_action_count"] != 134
            or boundary["last_executed_action_id"] != "s136_c0"
            or boundary["last_requested_action_id"] != "s137_c0")):
        raise ValueError("HF001_expected_observed_boundary_changed")
    out.mkdir(parents=True, exist_ok=False)
    frozen_inputs = out / "inputs"
    frozen_inputs.mkdir()
    for name, data in raw.items():
        with (frozen_inputs / name).open("xb") as stream:
            stream.write(data)
    resources = {"cpus": config["environment"].get("cpus", 2),
                 "memory": str(config["environment"].get("memory_mb", 8192)) + "m"}
    _write_new(out / "plan.json", {
        "created_at": _now(), "case_identity": {key: case[key] for key in ("id", "image", "base_commit")},
        "source_inputs": inputs, "frozen_inputs": {name: _receipt(frozen_inputs / name) for name in INPUT_NAMES},
        "task_base_commit_resolution": task_base,
        "action_ids": [action["id"] for action in actions], "terminal_marker": marker["id"], "observed_submission_boundary": boundary,
        "shell": "/bin/sh", "timeout_seconds": 30, "environment_overlay": ENV,
        "resources": resources, "strategy": "Every observed executed original action, in order; exclude only explicitly unexecuted calls as whole commands, no source/test transplant.",
        "historical_environment_limit": "ATIF does not record all environment overrides or model-thinking delays; retain the established mini-swe-agent replay shell/timeout defaults.",
        "code": [_receipt(Path(__file__)), _receipt(Path(__file__).with_name("replay_boundaries.py")), _receipt(Path(__file__).parents[1] / "tramask_pilot/submission_replay.py"),
                 _receipt(Path(__file__).parents[1] / "tramask_pilot/submission_state.py")],
    })
    records, stage, checkpoint = [], "start", None
    def progress(phase, **details):
        ordinal = len(list((out / "progress").glob("*.json"))) if (out / "progress").exists() else 0
        _write_new(out / "progress" / f"{ordinal:06d}.json", {"at": _now(), "phase": phase,
                   "completed_actions": len(records), "planned_actions": len(actions), **details})
    try:
        with Container(case["image"], out / "runtime", case["base_commit"], **resources) as runtime:
            stage = "baseline_process_inventory"
            baseline = _process_inventory(runtime, out / "processes_before_replay")
            for action in actions:
                stage = "action:" + action["id"]
                progress("action_started", action_id=action["id"])
                records.append(execute_action(runtime, action))
                progress("action_completed", action_id=action["id"])
            if [row["id"] for row in records] != [action["id"] for action in actions]:
                raise ValueError("full_action_coverage_mismatch")
            stage = "terminal_process_inventory"
            terminal = _process_inventory(runtime, out / "processes_at_submission")
            process_qualification = _process_risks(baseline, terminal)
            _write_new(out / "process_state.json", process_qualification)
            stage = "freeze_submission_checkpoint"
            progress("checkpoint_started")
            checkpoint = runtime.checkpoint("before_submission")
            _write_new(out / "checkpoint.json", checkpoint)
            changed = runtime._docker(["diff", runtime.name], timeout=60, check=False)
            (out / "docker_diff.stdout.bin").write_bytes(changed.stdout)
            (out / "docker_diff.stderr.bin").write_bytes(changed.stderr)
            replay_image, original_scratch = runtime.image_id, runtime.scratch
            progress("checkpoint_saved", image_id=checkpoint["image_id"])
        # Freeze and close the chronological replay before any validator runs.
        stage = "validate_frozen_checkpoint"
        with Container(checkpoint["image_id"], out / "frozen_state", checkpoint["head"], **resources) as frozen:
            remote = original_scratch + "/submission_inventory.json"
            inventory_process = frozen._control(["python3", "-c", INVENTORY], timeout=600,
                input_bytes=json.dumps({"scratch": original_scratch, "destination": remote}).encode(), check=False)
            (out / "inventory.stdout.bin").write_bytes(inventory_process.stdout)
            (out / "inventory.stderr.bin").write_bytes(inventory_process.stderr)
            if inventory_process.returncode:
                raise RuntimeError("frozen_filesystem_inventory_failed")
            frozen.copy_from(remote, out / "filesystem_inventory.json")
            inventory = _read(out / "filesystem_inventory.json")
            validation = validate_submission_state(frozen, frozen_inputs / "model.patch", out / "validation",
                                                   base_commit=case["base_commit"])
        stage = "record_validation"
        state_matches = all(validation.get(key) is True for key in (
            "submitted_commit_tree_matches", "working_tree_matches_submitted_commit", "index_tree_matches_submitted_commit"))
        state_matches = state_matches and validation.get("submission_state_status") == "matched"
        if validation.get("image_id") != checkpoint["image_id"] or validation.get("subject_files_or_real_index_patched") is not False:
            raise ValueError("validator_not_bound_to_untouched_frozen_checkpoint")
        risks = []
        if not state_matches:
            risks.append("submitted_head_worktree_or_index_not_verified")
        if not process_qualification["known_processes_quiescent"]:
            risks.append("terminal_background_process_or_process_inventory_unresolved")
        if inventory.get("errors"):
            risks.append("frozen_filesystem_inventory_errors")
        timeouts = [row["id"] for row in records if row.get("timed_out")]
        differences = [row["id"] for row in records if row.get("original_returncode") is not None
                       and row["returncode"] != row["original_returncode"]]
        if timeouts:
            risks.append("recorded_action_timeouts_require_replay_qualification")
        if differences:
            risks.append("archived_returncode_differences_require_replay_qualification")
        if changed.returncode:
            risks.append("docker_filesystem_diff_unavailable")
        source_drift = [name for name, bound in inputs.items() if _receipt(source / name) != bound]
        if source_drift:
            risks.append("original_inputs_changed_after_attempt_freeze")
        result = {"id": case["id"], "status": "replayed_pending_manual_qualification" if risks else "replayed",
            "actions_executed": len(records), "action_ids": [row["id"] for row in records],
            "terminal_marker": marker["id"], "observed_submission_boundary": boundary, "image_id": replay_image, "checkpoint": checkpoint,
            "validation": validation, "validation_receipt": _receipt(out / "validation/report.json"),
            "state_validation_passed": state_matches, "requires_manual_qualification": bool(risks), "risks": risks,
            "process_state": _receipt(out / "process_state.json"), "process_qualification": process_qualification,
            "inventory": _receipt(out / "filesystem_inventory.json"), "timeouts": timeouts,
            "returncode_differences": differences, "source_drift": source_drift,
            "source_inputs": inputs, "frozen_inputs": {name: _receipt(frozen_inputs / name) for name in INPUT_NAMES},
            "output_equality_used": False, "repair_actions_performed": False,
            "scope": "Full chronological filesystem replay; submitted HEAD, literal worktree and index compared independently with base plus submitted patch. /tmp, ignored dependencies and untracked files are inventoried, without an original terminal manifest or live-process equivalence claim."}
        _write_new(out / "summary.json", result)
        reference = {"image_id": checkpoint["image_id"], "head": checkpoint["head"],
                     "summary": _receipt(out / "summary.json"), "validation": _receipt(out / "validation/report.json"),
                     "state_validation_passed": state_matches, "requires_manual_qualification": bool(risks), "scope": result["scope"]}
        _write_new(out / "checkpoint_reference.json", reference)
        progress("completed", requires_manual_qualification=bool(risks))
        critical = [path for path in out.rglob("*") if path.is_file()]
        _write_new(out / "completion.json", {"completed_at": _now(), "receipts": [_receipt(path) for path in sorted(critical)]})
        return {**result, "study_checkpoint": reference, "resumed": False,
                "resumability": {"status": "complete", "can_reuse_recorded_result": True, "can_resume_commands": False}}
    except Exception as error:
        failure = {"id": case["id"], "status": "interrupted_attempt", "stage": stage,
                   "completed_actions": len(records), "planned_actions": len(actions),
                   "error_type": type(error).__name__, "error": str(error), "checkpoint": checkpoint,
                   "source_inputs": inputs, "repair_actions_performed": False}
        _write_new(out / "failure.json", failure)
        return {**failure, "resumability": inspect_attempt(out)}
