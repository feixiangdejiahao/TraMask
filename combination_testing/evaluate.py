"""Aggregate all generated outcomes, including invalid or reference-rejected tests.

Candidate alarms are computed without looking at the reference. Reference runs
are evaluation controls only; they must never be used to prune generation output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from combination_testing.runner import compare_pair, load_artifact, sha256


def _matches(expected: str, actual: str) -> bool:
    return (expected == actual or actual.endswith("::" + expected)
            or actual.endswith("[" + expected + "]")
            or ("::" + expected + "[") in actual)


def _metadata_lists(metadata: dict, key: str) -> list:
    value = metadata.get(key, [])
    rows = list(value) if isinstance(value, (list, tuple)) else [value] if value else []
    generators = metadata.get("generators", [])
    if isinstance(generators, dict):
        generators = generators.values()
    for generator in generators:
        if isinstance(generator, dict):
            rows += _metadata_lists(generator.get("metadata", generator), key)
    return rows


def _dependency_map(metadata: dict, test_ids: list[str]) -> tuple[dict[str, list[str]], set[str]]:
    obligations = _metadata_lists(metadata, "obligations")
    dependencies, control_ids = {}, set()
    for obligation in obligations:
        expected = obligation.get("id") or obligation.get("test")
        if not expected:
            continue
        controls = obligation.get("controls", [])
        if isinstance(controls, str):
            controls = [controls]
        if obligation.get("control"):
            controls = [*controls, obligation["control"]]
        if obligation.get("control_id"):
            controls = [*controls, obligation["control_id"]]
        if obligation.get("is_control"):
            control_ids.update(test_id for test_id in test_ids if _matches(expected, test_id))
        for test_id in test_ids:
            if _matches(expected, test_id):
                dependencies[test_id] = list(dict.fromkeys(controls))
        for control in controls:
            control_ids.update(test_id for test_id in test_ids if _matches(control, test_id))
    # Early frozen protocol artifacts recorded generated IDs and a seed count,
    # but omitted the explicit controls array. Recover only an exact partition;
    # do not silently relabel arbitrary failing tests as controls.
    if (not metadata.get("controls") and isinstance(metadata.get("seed_controls"), int)
            and metadata.get("obligations")):
        declared = [row.get("id") or row.get("test") for row in metadata["obligations"]]
        remaining = {test_id for test_id in test_ids
                     if not any(name and _matches(name, test_id) for name in declared)}
        if len(remaining) == metadata["seed_controls"]:
            control_ids.update(remaining)
    for control in _metadata_lists(metadata, "controls"):
        expected = control if isinstance(control, str) else control.get("id") or control.get("test")
        if expected:
            control_ids.update(test_id for test_id in test_ids if _matches(expected, test_id))
    return dependencies, control_ids


def _controls_pass(names: list[str], outcomes: dict[str, dict]) -> bool:
    for name in names:
        matches = [row for key, row in outcomes.items() if _matches(name, key)]
        if not matches or any(row["status"] != "pass" for row in matches):
            return False
    return True


def evaluate_case(artifact_dir: Path, execution_dir: Path) -> dict:
    artifact_dir, execution_dir = Path(artifact_dir), Path(execution_dir)
    manifest = load_artifact(artifact_dir)
    candidate = json.loads((execution_dir / "candidate/result.json").read_text())
    reference = json.loads((execution_dir / "reference/result.json").read_text())
    if sha256(artifact_dir / "manifest.json") != candidate["artifact_sha256"]:
        raise ValueError("Evaluation artifact differs from executed artifact")
    comparison = compare_pair(candidate, reference)
    ctests = {row["id"]: row for row in candidate["tests"]}
    rtests = {row["id"]: row for row in reference["tests"]}
    test_ids = sorted(ctests.keys() | rtests.keys())
    metadata = manifest.get("metadata", {})
    dependencies, control_ids = _dependency_map(metadata, test_ids)
    for test_id in test_ids:
        for outcome in (ctests.get(test_id), rtests.get(test_id)):
            if not outcome:
                continue
            if outcome.get("is_control"):
                control_ids.add(test_id)
            if outcome.get("control_id"):
                dependencies.setdefault(test_id, [])
                if outcome["control_id"] not in dependencies[test_id]:
                    dependencies[test_id].append(outcome["control_id"])
    rows = []
    for compared in comparison["tests"]:
        test_id = compared["id"]
        c, r = ctests.get(test_id), rtests.get(test_id)
        controls = dependencies.get(test_id, [])
        cp, rp = _controls_pass(controls, ctests), _controls_pass(controls, rtests)
        is_control = test_id in control_ids
        # Per-obligation invalid probes do not hide valid siblings. Global runner
        # errors invalidate the entire run, including any partial report.
        candidate_alert = bool(c and c["status"] == "fail" and cp
                               and not candidate.get("errors") and not is_control)
        reference_alert = bool(r and r["status"] == "fail" and rp
                               and not reference.get("errors") and not is_control)
        confirmed = candidate_alert and rp and compared["classification"] == "differential_witness"
        rows.append({**compared, "is_control": is_control, "controls": controls,
                     "control_basis": "declared_tests" if controls else "embedded_oracle_preconditions",
                     "candidate_controls_pass": cp, "reference_controls_pass": rp,
                     "candidate_alert": candidate_alert, "reference_alert": reference_alert,
                     "confirmed_witness": confirmed})
    obligations = [row for row in rows if not row["is_control"]]
    declared = _metadata_lists(metadata, "obligations")
    declared_ids = [row.get("id") or row.get("test") for row in declared]
    declared_missing = [name for name in declared_ids if name and not any(_matches(name, actual) for actual in test_ids)]
    skipped = _metadata_lists(metadata, "skipped") + _metadata_lists(metadata, "rejected") + _metadata_lists(metadata, "unsupported")
    counts = {"observed_obligations": len(obligations), "declared_obligations": len(declared),
              "declared_unexecuted": len(declared_missing), "controls": len(control_ids),
              "candidate_control_failures": sum(ctests.get(key, {}).get("status") == "fail" for key in control_ids),
              "reference_control_failures": sum(rtests.get(key, {}).get("status") == "fail" for key in control_ids),
              "candidate_control_errors": sum(ctests.get(key, {}).get("status") == "error" for key in control_ids),
              "reference_control_errors": sum(rtests.get(key, {}).get("status") == "error" for key in control_ids),
              "candidate_skipped": sum(row.get("candidate") == "skip" for row in obligations),
              "reference_skipped": sum(row.get("reference") == "skip" for row in obligations),
              "candidate_executed": sum(row.get("candidate") in {"pass", "fail"} for row in obligations),
              "reference_executed": sum(row.get("reference") in {"pass", "fail"} for row in obligations),
              "candidate_alerts": sum(row["candidate_alert"] for row in obligations),
              "reference_alerts": sum(row["reference_alert"] for row in obligations),
              "confirmed_witnesses": sum(row["confirmed_witness"] for row in obligations),
              "blocked_by_control": sum(not row["candidate_controls_pass"] or not row["reference_controls_pass"] for row in obligations),
              "reference_rejected": sum(row["classification"] == "reference_rejected_test" for row in obligations),
              "oracle_precondition_rejected": sum(row["classification"] == "oracle_precondition_rejected" for row in obligations),
              "execution_errors": sum(row["classification"] == "execution_error" for row in obligations),
              "missing_test_results": sum(row["classification"] == "missing_test_result" for row in obligations),
              "unsupported_static_sites": len(skipped)}
    from combination_testing.target_audit import audit_known_target
    target = audit_known_target(manifest["case_id"], metadata, rows, ctests)
    return {"case_id": manifest["case_id"], "artifact_sha256": candidate["artifact_sha256"],
            "known_target": target,
            "detected": bool(counts["confirmed_witnesses"]),
            "detection_scope": "Any controlled differential witness; known pilot defect matching requires separate evaluator-only review.",
            "candidate_alarm": bool(counts["candidate_alerts"]),
            "reference_alarm": bool(counts["reference_alerts"]),
            "candidate_run_status": candidate["status"], "reference_run_status": reference["status"],
            "counts": counts, "declared_unexecuted": declared_missing,
            "global_errors": {"candidate": candidate.get("errors", []), "reference": reference.get("errors", [])},
            "tests": rows}


def evaluate_experiment(artifacts: dict[str, Path], executions: dict[str, Path], case_ids: list[str]) -> dict:
    cases, missing = [], []
    for case_id in case_ids:
        artifact = artifacts.get(case_id)
        execution = executions.get(case_id)
        if (artifact is None or execution is None or not (artifact / "manifest.json").is_file()
                or not (execution / "candidate/result.json").is_file()
                or not (execution / "reference/result.json").is_file()):
            missing.append(case_id)
            continue
        cases.append(evaluate_case(artifact, execution))
    counts = {name: sum(case["counts"][name] for case in cases) for name in cases[0]["counts"]} if cases else {}
    detected = [case["case_id"] for case in cases if case["detected"]]
    missed = [case_id for case_id in case_ids if case_id not in detected]
    reference_alarms = [case["case_id"] for case in cases if case["reference_alarm"]]
    target_detected = [case["case_id"] for case in cases if case["known_target"]["detected"]]
    return {"cases": cases, "counts": counts,
            "known_target_detection": {"detected": target_detected,
                                       "missed_or_unverified": [cid for cid in case_ids if cid not in target_detected],
                                       "requested": len(case_ids)},
            "case_detection": {"detected": detected, "missed_or_unverified": missed,
                               "evaluated": len(cases), "requested": len(case_ids)},
            "reference_controls": {"cases_with_alarm": reference_alarms,
                                   "evaluated": len(cases)},
            "missing_experiments": missing,
            "target_matching": "Evaluator-only criteria in configs/combination_targets.json; known_target_detection differs from any-witness case_detection.",
            "scope": "Discovery-set case detection and alarms on independent reference implementations; not a population false-positive rate or proof of complete combination coverage.",
            "oracle_policy": "Candidate and reference alarms computed independently before differential comparison; no reference-based filtering of generated artifacts."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--executions", type=Path)
    parser.add_argument("--cases", nargs="+", default=[f"P{i}" for i in range(1, 8)])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    execution_root = args.executions or args.artifacts
    result = evaluate_experiment({cid: args.artifacts / cid for cid in args.cases},
                                {cid: execution_root / f"{cid}_execution" for cid in args.cases}, args.cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, indent=2))


if __name__ == "__main__":
    main()
