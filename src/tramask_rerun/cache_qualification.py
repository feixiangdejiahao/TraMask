"""Runner-only Go cache qualification, separate from all masking evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from tramask_pilot.fidelity import test_evidence
from tramask_pilot.submission_replay import ENV
from .runtime import execute_variant


PREFIX = 'export GOFLAGS="${GOFLAGS-$(go env GOFLAGS)} -count=1"\n'


def _read(path):
    return json.loads(Path(path).read_bytes())


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _receipt(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _verify(receipt):
    if _receipt(receipt["path"]) != receipt:
        raise ValueError("frozen_receipt_changed: " + receipt["path"])


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def cache_bypass_command(original_command):
    if not isinstance(original_command, str) or not original_command or "\0" in original_command:
        raise ValueError("original_command_required")
    if re.search(r"(?:^|[\s;])(?:export\s+)?GOFLAGS=", original_command):
        raise ValueError("original_command_overrides_GOFLAGS; explicit_review_required")
    if re.search(r"(?:^|\s)-count(?:=|\s)", original_command):
        raise ValueError("original_command_has_explicit_count; do_not_rewrite_silently")
    return PREFIX + original_command


def freeze_protocol(run, case_ids):
    run = Path(run).resolve()
    path = run / "cache_qualification_protocol.json"
    if path.exists():
        result = _read(path)
        if result["case_ids"] != sorted(set(case_ids)):
            raise ValueError("existing_cache_protocol_case_mismatch")
        for receipt in result["bound_artifacts"]:
            _verify(receipt)
        return result
    cases = {row["id"]: row for row in _read(run / "previously_explored_cases.json")["cases"]}
    qualification = _read(run / "baseline_qualification_v01.json")
    eligible = set(qualification["priority_followups"]["runner_cache_qualification"])
    selected = sorted(set(case_ids))
    if not selected or not set(selected) <= eligible or not set(selected) <= set(cases):
        raise ValueError("cache_case_not_in_explicit_technical_followup")
    paths = [run / "previously_explored_cases.json", run / "baseline_qualification_v01.json",
             Path(__file__), Path(__file__).with_name("runtime.py")]
    commands = []
    for case_id in selected:
        directory = run / "runs" / case_id
        selected_test = _read(directory / "selection.json")
        command = selected_test["command"]
        if not re.search(r"\bgo\s+test\b", command):
            raise ValueError("cache_qualification_requires_go_test_command")
        effective = cache_bypass_command(command)
        paths += [directory / "selection.json", directory / "terminal_sources/result.json", directory / "baseline/summary.json"]
        baseline = _read(directory / "baseline/summary.json")
        if len(baseline["runs"]) != 3:
            raise ValueError("requires_three_original_cached_baseline_records")
        for row in baseline["runs"]:
            _verify(row["result"])
            paths.append(Path(row["result"]["path"]))
        commands.append({"case_id": case_id, "original_command": command, "original_sha256": _sha(command),
                         "effective_command": effective, "effective_sha256": _sha(effective),
                         "checkpoint": cases[case_id]["checkpoint"],
                         "test_timeout_seconds": cases[case_id]["test_timeout_seconds"]})
    result = {"version": "go-cache-qualification.v1", "frozen_at": datetime.now(timezone.utc).isoformat(),
        "case_ids": selected, "repeats_per_case": 3, "fresh_checkpoint_clone_per_repeat": True,
        "adaptation": "Only prefix the unchanged original command with GOFLAGS plus -count=1. Preserve set GOFLAGS, or read go env GOFLAGS when unset to preserve persistent configuration.",
        "prefix": PREFIX, "commands": commands, "bound_artifacts": [_receipt(p) for p in paths],
        "file_edits": [], "build_commands": [], "old_baseline_and_selection_overwritten": False,
        "cache_bypass_is_context_repair": False, "cache_bypass_is_masking_witness": False,
        "acceptance": "Three clean executions with noncached Go package results, no missing-test/build/transport blockers, stable package/test outcome signatures and matching selected original source/test file hashes; never shell exit 0 alone.",
        "target_reachability_limit": "Package assertions executing does not independently establish target-local E2; scope remains the original filtered command.",
        "source_integrity_scope": "No file edits supplied to runtime; selected source/test SHA256 before from terminal export and after from read-only observation export. Not a universal filesystem write monitor.",
        "output": "runs/<case_id>/baseline_uncached; all cached baseline evidence remains intact",
        "provider_calls": 0, "scientific_labels": None}
    _write_new(path, result)
    return result


def runner_observations(execution):
    text = execution.get("stdout", "") + "\n" + execution.get("stderr", "")
    facts = test_evidence(text)
    packages = [row for row in facts["identities"] if row["runner"] == "go_package"]
    duration_rows = re.findall(r"^(ok|FAIL)\s+(\S+)\s+([0-9]+(?:\.[0-9]+)?s)(?:\s|$)", text, flags=re.M)
    blocked = bool(re.search(r"\[no tests to run\]|\[no test files\]|\[build failed\]|\[setup failed\]|no Go files|no required module provides|syntax error|undefined:", text, re.I))
    cached = "(cached)" in text or any(row.get("cached") for row in packages)
    signature = sorted((row["runner"], row["id"], row["status"]) for row in facts["identities"]
                       if row["runner"] in {"go", "go_package"})
    qualifying = bool(packages and duration_rows) and not cached and not blocked and not facts["execution_blockers"]
    return {"runner_text_facts": facts, "cached_output_present": cached,
            "timed_package_result_rows": [list(row) for row in duration_rows],
            "missing_test_or_build_blocker": blocked, "outcome_signature": [list(row) for row in signature],
            "uncached_test_execution_reported": qualifying,
            "scope": "Original command's visible Go package/test reports; no target-local E2 inference."}


def qualify_case(case_id, run):
    run = Path(run).resolve()
    protocol_path = run / "cache_qualification_protocol.json"
    protocol = _read(protocol_path)
    if case_id not in protocol["case_ids"]:
        raise ValueError("case_not_in_frozen_cache_qualification_protocol")
    for bound in protocol["bound_artifacts"]:
        _verify(bound)
    cases = {row["id"]: row for row in _read(run / "previously_explored_cases.json")["cases"]}
    case = cases[case_id]
    directory = run / "runs" / case_id
    selected = _read(directory / "selection.json")
    baseline = _read(directory / "baseline/summary.json")
    export = _read(directory / "terminal_sources/result.json")
    originals = {row["path"]: row for row in export.get("files", []) if row.get("status") == "present"}
    monitored = sorted(set(selected["source_paths"] + selected["test_paths"]))
    if any(path not in originals or not originals[path].get("sha256") for path in monitored):
        raise ValueError("original_source_or_test_missing_from_terminal_export")
    original = selected["command"]
    effective = cache_bypass_command(original)
    frozen_command = next(row for row in protocol["commands"] if row["case_id"] == case_id)
    if effective != frozen_command["effective_command"] or case["checkpoint"] != frozen_command["checkpoint"]:
        raise ValueError("frozen_cache_command_or_checkpoint_changed")
    out = directory / "baseline_uncached"
    if out.exists():
        raise FileExistsError("Cache-qualification output already exists; retain it and review before a new attempt: " + str(out))
    out.mkdir()
    _write_new(out / "plan.json", {"case_id": case_id, "protocol": _receipt(protocol_path),
        "original_command": original, "original_command_sha256": _sha(original),
        "effective_command": effective, "effective_command_sha256": _sha(effective),
        "original_cached_baseline": _receipt(directory / "baseline/summary.json"),
        "file_edits": [], "monitored_paths": monitored,
        "before_files": [{"path": path, "sha256": originals[path]["sha256"]} for path in monitored]})
    records = []
    for repeat in (1, 2, 3):
        destination = out / f"repeat_{repeat:02d}"
        result = execute_variant(case["checkpoint"], destination, effective, case["test_timeout_seconds"],
            files={}, observation_paths=sorted(set(monitored + selected["observation_paths"])),
            build_commands=[], env=ENV, workdir=selected["working_directory"], resources=case["resources"])
        execution = result.get("execution") or {}
        facts = runner_observations(execution)
        observed = {row["path"]: row for row in result.get("observations", [])}
        file_matches = [{"path": path, "before_sha256": originals[path]["sha256"],
                         "after_sha256": observed.get(path, {}).get("sha256"),
                         "matches": observed.get(path, {}).get("sha256") == originals[path]["sha256"]} for path in monitored]
        original_record = next(row for row in baseline["runs"] if row["repeat"] == repeat)
        original_execution = _read(original_record["result"]["path"]).get("execution") or {}
        row = {"repeat": repeat, "result": _receipt(destination / "result.json"),
               "execution": _receipt(destination / "test/execution.json") if (destination / "test/execution.json").exists() else None,
               "original_command": original, "original_command_sha256": _sha(original),
               "effective_command": effective, "effective_command_sha256": _sha(effective),
               "status": result.get("status"), "returncode": execution.get("returncode"),
               "timed_out": execution.get("timed_out"), "transport_error": execution.get("transport_error"),
               "task_timeout_seconds": case["test_timeout_seconds"], "elapsed_seconds": execution.get("elapsed_seconds"),
               "checkpoint": case["checkpoint"], "files_supplied_to_runtime": {}, "file_hash_comparison": file_matches,
               "selected_source_and_test_hashes_unchanged": all(item["matches"] for item in file_matches),
               "original_cached_repeat": original_record["result"],
               "original_cached_runner_observations": runner_observations(original_execution), **facts}
        _write_new(destination / "cache_qualification.json", row)
        records.append(row)
    clean = all(row["status"] == "completed" and not row["timed_out"] and not row["transport_error"]
                and row["uncached_test_execution_reported"] and row["selected_source_and_test_hashes_unchanged"] for row in records)
    signatures = [json.dumps(row["outcome_signature"], sort_keys=True) for row in records]
    stable = clean and len(set(signatures)) == 1
    matches_cached = all(row["outcome_signature"] == row["original_cached_runner_observations"]["outcome_signature"] for row in records)
    summary = {"case_id": case_id, "status": "stable_uncached_runner_outcomes" if stable else "requires_technical_review",
        "protocol": _receipt(protocol_path), "runs": records, "fresh_subject_test_executions": len(records),
        "three_clean_uncached_executions": clean, "runner_outcomes_stable": stable,
        "outcomes_match_original_cached_reports": matches_cached,
        "original_cached_baseline_preserved": True, "original_selection_preserved": True,
        "cache_bypass_is_context_repair": False, "cache_bypass_is_masking_witness": False,
        "E1_technical_component": "Fresh original-runner outcome stability established" if stable else "Unresolved",
        "E2_target_local_reachability": "Not established by runner-cache qualification alone",
        "scientific_label": None, "provider_calls": 0}
    _write_new(out / "summary.json", summary)
    return summary


def summarize(run):
    run = Path(run).resolve()
    protocol = _read(run / "cache_qualification_protocol.json")
    rows = []
    for case_id in protocol["case_ids"]:
        path = run / "runs" / case_id / "baseline_uncached/summary.json"
        result = _read(path)
        rows.append({key: result[key] for key in ("case_id", "status", "fresh_subject_test_executions",
            "three_clean_uncached_executions", "runner_outcomes_stable", "outcomes_match_original_cached_reports")}
            | {"summary": _receipt(path)})
    result = {"version": "go-cache-qualification-summary.v1", "protocol": _receipt(run / "cache_qualification_protocol.json"),
        "cases": rows, "fresh_subject_test_executions": sum(row["fresh_subject_test_executions"] for row in rows),
        "stable_uncached_cases": sum(row["runner_outcomes_stable"] for row in rows),
        "old_cached_results_retained": True, "scientific_labels": None,
        "scope": "Technical evidence for E1/E2 reviewers. Cache bypass changes only test runner measurement; it is not context repair or a masking witness. Target-local E2 still requires independent execution evidence."}
    _write_new(run / "cache_qualification_summary.json", result)
    return result
