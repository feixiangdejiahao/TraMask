"""Frozen, metadata-only reserved sampling and explicit raw-file acquisition.

Importing this module never selects cases or reads subject data. Selection reads
only the supplied protocol, its prompt/code receipts, and the benchmark index.
Acquisition is a separate explicit action, with no model or subject execution.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import HTTPRedirectHandler, Request, build_opener


INPUT_NAMES = ("instruction.md", "task.toml", "model.patch", "trajectory.json")
PUBLIC_ROOT = "https://d3ujjcmjq6o8v6.cloudfront.net/v1.1/trial-artifacts/"
SUFFIXES = {"trajectory.json": "agent/trajectory.json", "model.patch": "artifacts/model.patch"}
FROZEN_STATUS = "frozen_before_reserved_content_access_and_new_model_outputs"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _receipt(path, data=None):
    path = Path(path).absolute()
    data = path.read_bytes() if data is None else data
    return {"path": str(path), "bytes": len(data), "sha256": _sha(data)}


def _check_receipt(row, base):
    path = _path(row.get("path"))
    if not path.is_absolute():
        path = Path(base) / path
    if type(row.get("bytes")) is not int or not re.fullmatch(r"[a-f0-9]{64}", str(row.get("sha256", ""))):
        raise ValueError("invalid_file_receipt")
    actual = _receipt(path)
    if actual["bytes"] != row["bytes"] or actual["sha256"] != row["sha256"]:
        raise ValueError("frozen_receipt_mismatch")
    return actual


def _name(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        raise ValueError("invalid_" + field)
    return value


def _path(value):
    if isinstance(value, dict):
        value = value.get("path")
    if not isinstance(value, (str, Path)) or not str(value) or "://" in str(value) or "\x00" in str(value):
        raise ValueError("invalid_local_path")
    return Path(value)


def _raw_directory(case):
    """Resolve a raw-failure metadata path lexically, without opening it."""
    values = []
    for key in ("rawfailmetadata_source", "source", "old_source_path"):
        if case.get(key) is not None:
            path = _path(case[key])
            values.append(path.parent if path.name == "metadata.json" else path)
    if values and any(p != values[0] for p in values[1:]):
        raise ValueError("conflicting_raw_source_paths")
    return values[0] if values else None


def choose_reserved(audit, protocol_path):
    """Return a fixed 15-failed/5-successful manifest, never acquire subjects.

    The audit defines eligible issues; the complete benchmark index supplies all
    qualifying DeepSeek-v4-flash trials. Both issue and within-issue trial order
    use the NEW frozen seed. Sampling is independent of replay/search outcomes;
    selected acquisition/replay failures remain in the denominator, not replaced.
    """
    protocol_path = _path(protocol_path).absolute()
    protocol_bytes = protocol_path.read_bytes()
    protocol = json.loads(protocol_bytes)
    if protocol.get("freeze_status") not in {FROZEN_STATUS, "frozen"}:
        raise ValueError("protocol_not_frozen")
    reserved = protocol["sampling"]["reserved"]
    if reserved.get("failed") != 15 or reserved.get("successful") != 5 or reserved.get("replacements") is not False:
        raise ValueError("reserved_design_must_be_fixed_15_failed_5_successful")
    seed = reserved.get("seed")
    if not isinstance(seed, str) or not seed:
        raise ValueError("frozen_sampling_seed_missing")
    implementation = protocol.get("implementation_receipts", [])
    prompt_rows = [r for r in implementation if _path(r.get("path")).name == "prompts.py"]
    prompt_rows += protocol.get("prompt_receipts", [])
    if not prompt_rows:
        raise ValueError("frozen_prompt_receipt_missing")
    prompt_receipts = [_check_receipt(r, protocol_path.parent) for r in prompt_rows]
    # Bind the sampling implementation too when its receipt is registered.
    for row in implementation:
        if _path(row.get("path")).name == "sampling.py":
            _check_receipt(row, protocol_path.parent)
    index_path = _path(audit["source_index"]["path"]).absolute()
    index_bytes = index_path.read_bytes()
    index_receipt = _receipt(index_path, index_bytes)
    for row in audit.get("sources", []):
        if _path(row["path"]).absolute() == index_path:
            if any(row[k] != index_receipt[k] for k in ("bytes", "sha256")):
                raise ValueError("audited_index_receipt_mismatch")
    index_rows = json.loads(index_bytes)["rows"]
    old_cases = audit["corrected_submission_checkpoints"]["cases"]
    old_issues = {r["task"] for r in old_cases}
    old_issues.update(r["task"] for r in audit.get("excluded_metadata", [])
                      if r.get("reason") == "issue_seen_in_old_tramask_inputs_runs_or_environment_preparation")
    old_issues.update(audit.get("exposure", {}).get("old_tramask_exposed_issues", []))
    calibration = {r["task"] for r in audit.get("calibration", {}).get("cases", [])}
    prior = {r["task"] for r in audit.get("exposure", {}).get("prior_other_method_issue_overlap_with_tramask_unexposed", [])}
    candidate_groups = audit["candidate_metadata_order"]
    for rows in candidate_groups.values():
        prior.update(r["task"] for r in rows if r.get("prior_registered_method_pilots"))
    templates, exclusions = {}, []
    for kind, cohort in (("failed_order", "failed"), ("successful_order", "successful")):
        for row in candidate_groups[kind]:
            task = _name(row["task"], "task")
            reasons = []
            if task in old_issues:
                reasons.append("prior_tramask_issue")
            if task in calibration:
                reasons.append("calibration_issue")
            if task in prior or row.get("eligible_under_recommended_extra_pilot_exclusion") is False:
                reasons.append("prior_other_method_issue")
            if reasons:
                exclusions.append({"task": task, "cohort": cohort, "reasons": reasons})
            else:
                templates.setdefault((cohort, task), row)
    trials = {}
    for row in index_rows:
        cohort = {"fail": "failed", "pass": "successful"}.get(row.get("outcome"))
        key = (cohort, row.get("task_name"))
        if (key in templates and row.get("source") == "deep-swe"
                and row.get("model") == "deepseek-v4-flash"
                and row.get("has_trajectory") is True and row.get("has_model_patch") is True):
            trial = _name(row["trial_name"], "trial")
            if trial in trials and trials[trial] != key:
                raise ValueError("conflicting_index_trial_identity")
            trials[trial] = key
    order = lambda value: (_sha((seed + ":" + value).encode()), value)
    selected, used, candidate_order = [], set(), {}
    for cohort, target, prefix in (("failed", 15, "HF"), ("successful", 5, "HS")):
        tasks = sorted({task for kind, task in trials.values() if kind == cohort}, key=order)
        candidate_order[cohort] = []
        chosen_in_stratum = 0
        for task in tasks:
            eligible = sorted((trial for trial, key in trials.items() if key == (cohort, task)), key=order)
            candidate_order[cohort].append({"task": task, "trial_order": eligible})
            if task in used:
                exclusions.append({"task": task, "cohort": cohort, "reasons": ["selected_failed_issue"]})
                continue
            if chosen_in_stratum >= target:
                continue
            chosen_in_stratum += 1
            template, trial = templates[cohort, task], eligible[0]
            source = _raw_directory(template)
            if source is not None:
                if source.name != template["trial"]:
                    raise ValueError("raw_source_directory_not_bound_to_trial")
                source = source.parent / trial
            row = {k: template[k] for k in ("language", "base_commit", "image", "task_directory") if k in template}
            if "task_directory" in row:
                row["task_directory"] = str(_path(row["task_directory"]))
            row.update(id=f"{prefix}{chosen_in_stratum:03}", task=task, trial=trial,
                       model="deepseek-v4-flash", cohort=cohort, partition="reserved",
                       source_case_id=template["id"], metadata_template_trial=template["trial"],
                       source=str(source) if source else None,
                       rawfailmetadata_source=str(source / "metadata.json") if source else None,
                       index_source=index_receipt, historical_manual_failure_review_issue=bool(
                           template.get("historical_manual_failure_review_issue", cohort == "failed")))
            selected.append(row)
            used.add(task)
        if chosen_in_stratum != target:
            raise ValueError("insufficient_independent_" + cohort + "_issues")
    if len(used) != 20 or used & (old_issues | calibration | prior):
        raise ValueError("reserved_issue_disjointness_failed")
    return {"status": "fixed_reserved_sample_before_content_access", "cases": selected,
            "counts": {"failed": 15, "successful": 5, "distinct_issues": 20}, "seed": seed,
            "protocol_receipt": _receipt(protocol_path, protocol_bytes), "prompt_receipts": prompt_receipts,
            "index_receipt": index_receipt, "audit_sha256": _sha(_json_bytes(audit)),
            "candidate_order": candidate_order, "exclusions": exclusions, "replacements": False,
            "selection_scope": "Audit supplies eligible issues; complete index supplies all filtered trials, both ordered by new seed.",
            "denominator_policy": "Acquisition/replay/no-test/invalid-Q failures retain their fixed slots; no outcome-based replacement.",
            "subject_content_read": False}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _download_public(url):
    """One unauthenticated request, no redirects/retries or exception URL logging."""
    if not url.startswith(PUBLIC_ROOT):
        raise ValueError("nonpublic_download_url")
    request = Request(url, headers={"User-Agent": "tramask-raw-acquisition/1"})
    with build_opener(_NoRedirect()).open(request, timeout=90) as response:
        if response.status != 200:
            raise RuntimeError("public_download_http_failure")
        data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024:
            raise ValueError("public_artifact_too_large")
        return data


def _write_json(path, value):
    fd, temp = tempfile.mkstemp(prefix=".acquisition-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(_json_bytes(value))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def acquire_case(case, input_dir):
    """Copy/fetch exactly four raw artifacts with durable, idempotent receipts.

    Only acquisition invokes this content boundary. It never parses trajectories,
    sources, or manual summaries. A public fetch is attempted at most once per
    artifact/destination, even after an interruption. A failed fetch requires an
    explicit new acquisition destination; it never changes the selected case.
    Unknown case fields (including credentials) are not copied to provenance.
    """
    identity = {k: _name(case[k], k) for k in ("id", "task", "trial")}
    destination = _path(input_dir).absolute()
    if destination.is_symlink():
        raise ValueError("symlink_input_directory")
    destination.mkdir(parents=True, exist_ok=True)
    state_path, provenance_path = destination / "acquisition.json", destination / "provenance.json"
    if any((destination / n).is_symlink() for n in (*INPUT_NAMES, "acquisition.json", "provenance.json")):
        raise ValueError("symlink_input_artifact")
    source, task_dir = _raw_directory(case), _path(case["task_directory"])
    plans = {}
    for name in INPUT_NAMES:
        local = source / name if source else task_dir / name if name not in SUFFIXES else None
        if local is not None and local.is_symlink():
            raise ValueError("symlink_raw_source_file")
        if local is not None and local.is_file():
            plans[name] = {"kind": "local_raw_file", "path": str(local.absolute())}
        elif name in SUFFIXES:
            plans[name] = {"kind": "public_download", "url": PUBLIC_ROOT + identity["trial"] + "/" + SUFFIXES[name]}
        elif source and (task_dir / name).is_symlink():
            raise ValueError("symlink_raw_source_file")
        elif source and (task_dir / name).is_file():
            plans[name] = {"kind": "local_raw_file", "path": str((task_dir / name).absolute())}
        else:
            raise FileNotFoundError("required_raw_task_file_missing: " + name)
    if state_path.exists():
        state = json.loads(state_path.read_bytes())
        if state.get("case") != identity or state.get("plans") != plans:
            raise ValueError("acquisition_identity_or_source_changed")
    else:
        state = {"case": identity, "plans": plans, "files": {}}
    for name in INPUT_NAMES:
        target, plan = destination / name, plans[name]
        previous = state["files"].get(name)
        if previous and previous.get("status") == "complete":
            actual = _receipt(target)
            if actual != previous["receipt"]:
                raise ValueError("existing_artifact_receipt_mismatch: " + name)
            if plan["kind"] == "local_raw_file":
                source_receipt = _receipt(plan["path"])
                if source_receipt != previous["source_receipt"]:
                    raise ValueError("local_raw_source_changed: " + name)
            continue
        if previous:
            raise RuntimeError("previous_fetch_failed_or_interrupted: " + name)
        if plan["kind"] == "local_raw_file":
            data = Path(plan["path"]).read_bytes()
            source_receipt = _receipt(plan["path"], data)
        else:
            if target.exists():
                raise ValueError("unreceipted_existing_public_artifact: " + name)
            state["files"][name] = {"status": "fetch_started", "source": plan}
            _write_json(state_path, state)
            try:
                data = _download_public(plan["url"])
            except Exception as exc:
                state["files"][name].update(status="fetch_failed", error_type=type(exc).__name__)
                _write_json(state_path, state)
                raise RuntimeError("public_artifact_fetch_failed: " + name) from None
            source_receipt = {"url": plan["url"], "bytes": len(data), "sha256": _sha(data)}
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError("existing_artifact_content_mismatch: " + name)
        else:
            with target.open("xb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
        state["files"][name] = {"status": "complete", "source": plan,
                                "source_receipt": source_receipt, "receipt": _receipt(target, data)}
        _write_json(state_path, state)
    manifest = {"case": identity, "status": "acquired", "files": [state["files"][n] for n in INPUT_NAMES],
                "subject_execution": False, "model_calls": False,
                "source_policy": "Four explicitly named public raw inputs only; no summaries, hidden evaluators, or reference solutions."}
    if provenance_path.exists():
        if provenance_path.read_bytes() != _json_bytes(manifest):
            raise ValueError("existing_provenance_mismatch")
    else:
        with provenance_path.open("xb") as out:
            out.write(_json_bytes(manifest))
    return manifest
