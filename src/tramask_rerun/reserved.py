"""Explicit fixed reserved-cohort acquisition and terminal replay phases."""
from pathlib import Path
import subprocess
import time
import tomllib

from tramask_pilot.corpus import read, receipt
from .replay import inspect_image_availability, replay_case
from .sampling import acquire_case, choose_reserved
from .study import PREPARATION, RUN, now, write_new


def sample(run=RUN):
    run = Path(run)
    destination = run / "reserved_selection.json"
    if destination.exists():
        return read(destination)
    audit_path = PREPARATION / "inventory_audit.json"
    selection = choose_reserved(read(audit_path), run / "protocol.json")
    selection["audit_receipt"] = receipt(audit_path)
    selection["selected_at"] = now()
    write_new(destination, selection)
    previous = read(run / "previously_explored_cases.json")["cases"]
    cases = previous + selection["cases"]
    if len(cases) != 60 or len({row["task"] for row in cases}) != 60:
        raise ValueError("Expected 60 disjoint issue-level cases")
    write_new(run / "cases.json", {"count": 60, "cases": cases,
        "counts": {"previously_explored_failed": 30, "previously_explored_successful": 10,
                   "reserved_failed": 15, "reserved_successful": 5},
        "outcome_based_replacement": False, "selection": receipt(destination)})
    return selection


def acquire(case, run=RUN):
    if case.get("partition") != "reserved":
        raise ValueError("Only reserved acquisition belongs to this phase")
    run = Path(run)
    result = acquire_case(case, run / "inputs" / case["id"])
    source = run / "inputs" / case["id"] / "task.toml"
    if not source.exists() or not all((source.parent / n).exists() for n in ("instruction.md", "model.patch", "trajectory.json")):
        return {"case_id": case["id"], "status": "acquisition_incomplete", "acquisition": result}
    config = tomllib.loads(source.read_text())
    if config["metadata"]["base_commit_hash"] != case["base_commit"] or config["environment"]["docker_image"] != case["image"]:
        raise ValueError("Task metadata does not match fixed case identity")
    environment = {"test_timeout_seconds": float(config["verifier"]["timeout_sec"]),
        "timeout_source": "task.toml:[verifier].timeout_sec",
        "build_timeout_seconds": float(config["environment"]["build_timeout_sec"]),
        "resources": {"cpus": config["environment"].get("cpus", 2),
                      "memory": str(config["environment"].get("memory_mb", 8192)) + "m"},
        "task_receipt": receipt(source)}
    write_new(run / "runs" / case["id"] / "environment.json", environment)
    return {"case_id": case["id"], "status": "acquired", "files": 4}


def ensure_image(case, run=RUN):
    out = Path(run) / "runs" / case["id"] / "image_preparation"
    available = inspect_image_availability(case["image"])
    if available["available"]:
        if not (out / "available.json").exists():
            write_new(out / "available.json", available)
        return available
    if "No such image" not in available.get("stderr", ""):
        raise RuntimeError("Image inspection failed; do not mistake Docker access failure for a missing image")
    if (out / "pull_plan.json").exists():
        return {"status": "prior_pull_requires_inspection", "available": False}
    write_new(out / "pull_plan.json", {"image": case["image"], "created_at": now(),
        "source": "public benchmark task.toml image", "retry": "no implicit retry"})
    started = time.monotonic()
    try:
        process = subprocess.run(["docker", "pull", case["image"]], capture_output=True, timeout=1800, check=False)
        (out / "stdout.bin").write_bytes(process.stdout)
        (out / "stderr.bin").write_bytes(process.stderr)
        result = {"returncode": process.returncode, "elapsed_seconds": time.monotonic() - started,
                  "inspection": inspect_image_availability(case["image"])}
    except subprocess.TimeoutExpired as error:
        (out / "stdout.bin").write_bytes(error.stdout or b"")
        (out / "stderr.bin").write_bytes(error.stderr or b"")
        result = {"status": "pull_timeout_requires_inspection", "elapsed_seconds": time.monotonic() - started,
                  "inspection": inspect_image_availability(case["image"])}
    write_new(out / "pull_result.json", result)
    return result["inspection"]


def replay(case, run=RUN):
    run = Path(run)
    image = ensure_image(case, run)
    if not image.get("available"):
        return {"case_id": case["id"], "status": "image_unavailable", "image_status": image}
    result = replay_case(case, run / "inputs" / case["id"], run / "runs" / case["id"] / "submission_replay_v01")
    if result.get("state_validation_passed"):
        write_new(run / "runs" / case["id"] / "active_submission_state.json", result["study_checkpoint"])
    return {"case_id": case["id"], "status": result.get("status"),
            "actions_executed": result.get("actions_executed"),
            "state_validation_passed": result.get("state_validation_passed"), "risks": result.get("risks")}


def load_cases(run=RUN):
    run = Path(run)
    path = run / "cases.json"
    if not path.exists():
        path = run / "previously_explored_cases.json"
    result = []
    for case in read(path)["cases"]:
        case = dict(case)
        environment = run / "runs" / case["id"] / "environment.json"
        checkpoint = environment.with_name("active_submission_state.json")
        if environment.exists():
            case.update(read(environment))
        if checkpoint.exists():
            case["checkpoint"] = read(checkpoint)
        result.append(case)
    return result
