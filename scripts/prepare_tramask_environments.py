"""Prepare provisional TraMask images/public inputs; never start a container.

Only docker image inspect and docker pull are permitted here. The first forty
failed-order entries and first twelve eligible successful-order entries are
fixed before any operation. This is acquisition, not formal cohort selection.
An explicit failed range has its own frozen plan and summary; earlier records
are neither replaced nor retried by such an extension.
Existing result records are reused; incomplete attempts are retained without
silently retrying a pull or download.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from tramask_pilot.corpus import RUN, read, receipt, write
from scripts.run_tramask_pilot import acquire

OUTPUT = RUN / "environment_preparation"
PULL_TIMEOUT_SECONDS = 300
WORKERS = 3


def now():
    return datetime.now(timezone.utc).isoformat()


def selection():
    path = RUN / "selection_order.json"
    document = read(path)
    failures = document["failed_order"][:40]
    excluded_tasks = {case["task"] for case in failures + document["calibration"]}
    successes = [case for case in document["successful_order"] if case["task"] not in excluded_tasks][:12]
    plan = {"version": 1, "selection_order": receipt(path), "formal_selection": False,
            "rule": "First forty failed_order entries; first twelve successful_order entries excluding those forty tasks and all calibration tasks, without label-dependent replacement.",
            "failed_image_preparation": failures, "provisional_success_acquisitions": successes,
            "max_parallel_operations": WORKERS, "pull_timeout_seconds": PULL_TIMEOUT_SECONDS,
            "subject_execution": False, "model_calls": False,
            "public_acquisition_files": ["instruction.md", "task.toml", "model.patch", "trajectory.json"],
            "public_remote_root": "https://d3ujjcmjq6o8v6.cloudfront.net/v1.1/trial-artifacts/"}
    return plan, failures, successes


def _begin(case, kind):
    directory = OUTPUT / case["id"]
    directory.mkdir(parents=True, exist_ok=True)
    result = directory / (kind + "_result.json")
    if result.exists():
        return directory, read(result)
    marker = directory / (kind + "_started.json")
    if marker.exists():
        interrupted = {"id": case["id"], "task": case["task"], "status": "interrupted_previous_attempt",
                       "started_record": receipt(marker), "formal_selection": False,
                       "retry_performed": False, "finished_at": now()}
        write(result, interrupted)
        return directory, interrupted
    with marker.open("x") as stream:
        json.dump({"id": case["id"], "kind": kind, "started_at": now(), "case": case,
                   "formal_selection": False}, stream, indent=2)
        stream.write("\n")
    return directory, None


def _docker(case, directory, label, arguments, timeout):
    argv = ["docker", *arguments]
    started = time.monotonic()
    record = {"argv": argv, "timeout_seconds": timeout, "started_at": now(), "timed_out": False}
    with (directory / (label + ".stdout.log")).open("xb") as stdout, (directory / (label + ".stderr.log")).open("xb") as stderr:
        try:
            process = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
            record["returncode"] = process.returncode
        except subprocess.TimeoutExpired:
            record.update(returncode=None, timed_out=True)
        except OSError as exc:
            record.update(returncode=None, error_type=type(exc).__name__)
    record["seconds"] = time.monotonic() - started
    record["stdout"] = receipt(directory / (label + ".stdout.log"))
    record["stderr"] = receipt(directory / (label + ".stderr.log"))
    write(directory / (label + ".json"), record)
    return record


def image(case):
    directory, previous = _begin(case, "image")
    if previous is not None:
        return previous
    result = {"id": case["id"], "task": case["task"], "trial": case["trial"], "requested_image": case["image"],
              "declared_base_commit": case["base_commit"], "base_commit_verified_in_container": False,
              "formal_selection": False, "subject_execution": False, "started_at": now()}
    try:
        inspect = _docker(case, directory, "inspect_before", ["image", "inspect", "--format", "{{.Id}}", case["image"]], 30)
        result["initial_inspection"] = inspect
        final_inspect = inspect
        if inspect["returncode"] != 0:
            error_text = (directory / "inspect_before.stderr.log").read_text(errors="replace").lower()
            if "no such image" not in error_text and "no such object" not in error_text:
                result["status"] = "docker_inspection_failure"
            else:
                pull = _docker(case, directory, "pull", ["pull", case["image"]], PULL_TIMEOUT_SECONDS)
                result["pull"] = pull
                final_inspect = _docker(case, directory, "inspect_after", ["image", "inspect", "--format", "{{.Id}}", case["image"]], 30)
                result["final_inspection"] = final_inspect
                result["status"] = "available_after_pull" if final_inspect["returncode"] == 0 else "pull_timeout" if pull["timed_out"] else "pull_failed"
        else:
            result["status"] = "available_locally"
        if final_inspect["returncode"] == 0:
            image_id = Path(final_inspect["stdout"]["path"]).read_text().strip()
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                raise ValueError("invalid_full_image_id")
            result["image_id"] = image_id
        result["available"] = "image_id" in result
    except Exception as exc:
        result.update(status="preparation_error", available=False, error_type=type(exc).__name__, error=str(exc))
    result["finished_at"] = now()
    write(directory / "image_result.json", result)
    return result


def public_inputs(case):
    directory, previous = _begin(case, "acquisition")
    if previous is not None:
        return previous
    result = {"id": case["id"], "task": case["task"], "trial": case["trial"],
              "declared_base_commit": case["base_commit"], "requested_image": case["image"],
              "formal_selection": False, "status": "acquiring_provisional_public_inputs", "started_at": now(),
              "public_source_directory": case.get("source"),
              "public_remote_paths": [] if case.get("source") else [
                  f"https://d3ujjcmjq6o8v6.cloudfront.net/v1.1/trial-artifacts/{case['trial']}/{suffix}"
                  for suffix in ("artifacts/model.patch", "agent/trajectory.json")]}
    try:
        result["acquire_result"] = acquire(case)
        result["provenance"] = receipt(RUN / "inputs" / case["id"] / "provenance.json")
        artifacts = read(result["provenance"]["path"])["files"]
        verified = all(receipt(artifact["path"]) == artifact for artifact in artifacts)
        result["receipt_verification"] = {"files_verified": len(artifacts), "all_hashes_match": verified}
        if not verified:
            raise ValueError("acquired_artifact_receipt_mismatch")
        result["status"] = "public_inputs_acquired_provisional"
    except Exception as exc:
        result.update(status="public_acquisition_failed", error_type=type(exc).__name__, error=str(exc))
    result["finished_at"] = now()
    write(directory / "acquisition_result.json", result)
    return result


def prepare_range(start, end, *, plan_only=False):
    path = RUN / "selection_order.json"
    selection_document = read(path)
    if not 1 <= start <= end <= len(selection_document["failed_order"]):
        raise ValueError("invalid_failed_range")
    cases = selection_document["failed_order"][start - 1:end]
    if [case["id"] for case in cases] != [f"F{index:03d}" for index in range(start, end + 1)]:
        raise ValueError("failed_range_ids_do_not_match_frozen_order")
    label = f"F{start:03d}_F{end:03d}"
    plan = {"version": 1, "kind": "additional_fixed_failed_range", "formal_selection": False,
            "selection_order": receipt(path), "range_inclusive": [start, end], "cases": cases,
            "rule": "Acquire public inputs and prepare exactly this contiguous frozen failed_order range; do not retry earlier records or replace failed cases.",
            "max_parallel_operations": WORKERS, "pull_timeout_seconds": PULL_TIMEOUT_SECONDS,
            "subject_execution": False, "model_calls": False}
    if plan_only:
        print(json.dumps({"range": label, "ids": [case["id"] for case in cases],
                          "selection_sha256": plan["selection_order"]["sha256"]}))
        return
    directory = OUTPUT / "ranges" / label
    directory.mkdir(parents=True, exist_ok=True)
    plan_path = directory / "plan.json"
    if plan_path.exists():
        if read(plan_path) != plan:
            raise ValueError("failed_range_preparation_plan_changed")
    else:
        write(plan_path, plan)
    def prepare(case):
        acquisition = public_inputs(case)
        prepared = image(case)
        return {"id": case["id"], "acquisition_status": acquisition["status"],
                "image_status": prepared["status"], "available": prepared.get("available", False)}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(prepare, case): case for case in cases}
        for future in as_completed(futures):
            print(json.dumps(future.result()), flush=True)
    image_records = [read(OUTPUT / case["id"] / "image_result.json") for case in cases]
    acquisition_records = [read(OUTPUT / case["id"] / "acquisition_result.json") for case in cases]
    summary = {"formal_selection": False, "range": label, "finished_at": now(),
               "selection_order_sha256": plan["selection_order"]["sha256"], "cases": [case["id"] for case in cases],
               "available_images": [row["id"] for row in image_records if row.get("available")],
               "unavailable_images": [row["id"] for row in image_records if not row.get("available")],
               "acquired_public_inputs": [row["id"] for row in acquisition_records if row["status"] == "public_inputs_acquired_provisional"],
               "failed_public_acquisitions": [row["id"] for row in acquisition_records if row["status"] != "public_inputs_acquired_provisional"],
               "verified_artifact_count": sum(row.get("receipt_verification", {}).get("files_verified", 0) for row in acquisition_records),
               "no_containers_started": True, "no_subject_tests": True, "no_model_calls": True,
               "earlier_failed_cases_not_retried": True}
    write(directory / "summary.json", summary)
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("phase", choices=("plan", "all", "images", "controls", "range"))
    parser.add_argument("--failed-range", nargs=2, type=int, metavar=("START", "END"))
    args = parser.parse_args()
    if args.failed_range is not None:
        if args.phase not in ("plan", "range"):
            parser.error("--failed-range requires phase plan or range")
        prepare_range(*args.failed_range, plan_only=args.phase == "plan")
        return
    if args.phase == "range":
        parser.error("range requires --failed-range START END")
    plan, failures, successes = selection()
    if args.phase == "plan":
        print(json.dumps({"failed_ids": [case["id"] for case in failures],
                          "provisional_success_ids": [case["id"] for case in successes],
                          "selection_sha256": plan["selection_order"]["sha256"]}))
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plan_path = OUTPUT / "plan.json"
    if plan_path.exists():
        if read(plan_path) != plan:
            raise ValueError("environment_preparation_plan_changed")
    else:
        write(plan_path, plan)
    work = []
    if args.phase in ("all", "controls"):
        work.extend((public_inputs, case) for case in successes)
    if args.phase in ("all", "images"):
        work.extend((image, case) for case in failures)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(operation, case): case for operation, case in work}
        for future in as_completed(futures):
            result = future.result()
            print(json.dumps({key: result[key] for key in ("id", "status", "available", "image_id") if key in result}), flush=True)
    images = [read(OUTPUT / case["id"] / "image_result.json") for case in failures if (OUTPUT / case["id"] / "image_result.json").exists()]
    controls = [read(OUTPUT / case["id"] / "acquisition_result.json") for case in successes if (OUTPUT / case["id"] / "acquisition_result.json").exists()]
    summary = {"formal_selection": False, "finished_at": now(), "selection_order_sha256": plan["selection_order"]["sha256"],
               "images_planned": len(failures), "images_recorded": len(images),
               "available_images": [row["id"] for row in images if row.get("available")],
               "unavailable_images": [row["id"] for row in images if not row.get("available")],
               "controls_planned": len(successes), "controls_recorded": len(controls),
               "acquired_controls": [row["id"] for row in controls if row["status"] == "public_inputs_acquired_provisional"],
               "failed_control_acquisitions": [row["id"] for row in controls if row["status"] != "public_inputs_acquired_provisional"],
               "no_containers_started": True, "no_subject_tests": True, "no_model_calls": True}
    write(OUTPUT / ("summary_" + args.phase + ".json"), summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
