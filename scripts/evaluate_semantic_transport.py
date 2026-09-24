"""Independently inventory/seal/evaluate the fixed seven-case, two-round matrix.

This evaluator imports no generator, provider, runner, or target repository. It
never executes tests or expressions. Reference result JSON is read only with
--include-reference and a previously sealed oracle file. Mechanical completion
acceptance is deliberately not a semantic verdict.

inventory --experiment-root ROOT --output NEW.json
seal --experiment-root ROOT --reviews FILLED_TEMPLATE.json --output NEW.json
evaluate --experiment-root ROOT --sealed-oracles SEAL.json --output NEW.json

ROOT contains P1..P7 (or pilot/P1..P7); each contains rounds/r1 and rounds/r2.
The nested frozen/direct directory is an adapter detail, not another method.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

CASES = tuple(f"P{i}" for i in range(1, 8))
ROUNDS = ("r1", "r2")
VERDICTS = {"valid_oracle", "invalid_oracle", "inapplicable", "unknown"}
VERSION = "semantic-transport-independent-evaluation-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def read(path: Path):
    return json.loads(path.read_bytes())


def write_new(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def checked_path(root: Path, relative: str) -> Path:
    path = root / relative
    if not isinstance(relative, str) or not relative or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Evidence path escapes its declared directory")
    return path


def check_files(root: Path, hashes: dict) -> None:
    for name, expected in hashes.items():
        if digest(checked_path(root, name)) != expected:
            raise ValueError(f"Frozen file hash differs: {name}")


def case_directory(root: Path, case: str) -> Path:
    return root / "pilot" / case if (root / "pilot").is_dir() else root / case


def matches(name: str, actual: str) -> bool:
    local = actual.rsplit("::", 1)[-1]
    return any(value == name or value.startswith(name + "[") or value.startswith(name + "/")
               for value in (actual, local))


def matching(name: str, result: dict | None) -> list[dict]:
    return [row for row in (result or {}).get("tests", []) if matches(name, row["id"])]


def dependencies(row: dict) -> list[str]:
    names = []
    for key in ("controls", "control_ids"):
        value = row.get(key, [])
        names.extend([value] if isinstance(value, str) else value)
    names.extend(row[key] for key in ("control", "control_id") if row.get(key))
    return list(dict.fromkeys(names))


def global_errors(result: dict | None) -> list[str]:
    if result is None:
        return []
    errors = list(result.get("errors", []))
    if result.get("status") == "error":
        errors.append("reported_run_error")
    if result.get("counts", {}).get("error", 0):
        errors.append("reported_error_testcases")
    if any(row.get("status") == "error" for row in result.get("tests", [])):
        errors.append("testcase_setup_or_suite_error")
    ids = [row.get("id") for row in result.get("tests", [])]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_testcase_ids")
    process = result.get("process", {})
    transport = result.get("transport", {})
    if process.get("error") or process.get("timed_out"):
        errors.append("process_error_or_timeout")
    if transport.get("error") or transport.get("returncode") not in (None, 0):
        errors.append("transport_error")
    if process and process.get("returncode") is None:
        errors.append("missing_command_returncode")
    return sorted(set(errors))


def control_state(names: list[str], result: dict | None) -> dict:
    rows = {name: matching(name, result) for name in names}
    missing = [name for name, leaves in rows.items() if not leaves]
    failed = [name for name, leaves in rows.items() if any(row["status"] == "fail" for row in leaves)]
    skipped = [name for name, leaves in rows.items() if any(row["status"] == "skip" for row in leaves)]
    errors = [name for name, leaves in rows.items() if any(row["status"] == "error" for row in leaves)]
    run_errors = global_errors(result)
    passed = bool(names) and all(leaves and all(row["status"] == "pass" for row in leaves)
                                 for leaves in rows.values()) and not run_errors
    return {"declared": names, "passed": bool(passed), "missing": missing,
            "failed": failed, "skipped": skipped, "errors": errors, "global_errors": run_errors}


def obligation_state(name: str, controls: list[str], result: dict | None) -> dict:
    leaves = matching(name, result)
    state = control_state(controls, result)
    errors = global_errors(result)
    failure = any(row["status"] == "fail" for row in leaves)
    return {"run_present": result is not None, "controls": state,
            "outcomes": [{key: row.get(key) for key in ("id", "status", "kind")} for row in leaves],
            "runtime_leaves": len(leaves), "observed": bool(leaves),
            "executed": any(row["status"] in {"pass", "fail"} for row in leaves),
            "raw_failure": failure, "global_errors": errors,
            "passed": bool(leaves) and all(row["status"] == "pass" for row in leaves) and not errors,
            "alarm": failure and state["passed"] and not errors}


def completion_summary(directory: Path) -> dict:
    marker = directory / "completion_round.json"
    cache = directory / "completion/manifest.json"
    summary = {"status": "missing", "valid": False, "attempts": None,
               "external_model_calls": None, "usage": None, "protocol_failure": False}
    if marker.exists():
        record = read(marker)
        summary.update(status=record.get("status", "missing"), marker_sha256=digest(marker),
                       attempts=record.get("model_request_attempts"))
    if cache.exists():
        record = read(cache)
        check_files(cache.parent, record.get("files_sha256", {}))
        summary.update({key: record.get(key) for key in
                        ("valid", "external_model_calls", "usage", "failure_kind", "seconds",
                         "model", "response_model", "finish_reason", "http_status")})
        summary.update(cache_sha256=digest(cache), cache_status=record.get("status"),
                       attempts=record.get("model_request_attempts"),
                       accepted=len(record.get("accepted", [])), rejected=len(record.get("rejected", [])))
    summary["protocol_failure"] = summary["status"] in {"invalid", "failed"} or (
        cache.exists() and not summary["valid"])
    return summary


def inspect_cell(root: Path, case: str, round_id: str, *, include_reference=False) -> dict:
    base = case_directory(root, case)
    directory = base / "rounds" / round_id
    cell = {"case_id": case, "round": round_id, "directory": str(directory.resolve()),
            "status": "not_prepared", "frozen": False, "generated": 0, "obligations": [],
            "integrity_errors": [], "reference_read": False, "generation_terminal": False}
    try:
        prepare = base / "transport_prepare.json"
        if not prepare.exists():
            return cell
        prepared = read(prepare)
        if prepared.get("case_id") != case or prepared.get("declared_completion_rounds") != list(ROUNDS):
            raise ValueError("Preparation case/rounds differ from the fixed matrix")
        check_files(base, prepared["files_sha256"])
        check_files(base / "algorithm_snapshot", {**prepared["algorithm_sha256"],
                                                   **prepared["transport_algorithm_sha256"]})
        cell.update(status="not_completed", transport_prepare_sha256=digest(prepare),
                    budget=prepared.get("budget", {}), proposal_counts=prepared.get("proposal_counts", {}))
        completion = completion_summary(directory)
        cell["completion"] = completion
        manifest_path = directory / "frozen/direct/manifest.json"
        if not manifest_path.exists():
            cell["status"] = "completion_failed" if completion["protocol_failure"] else "not_frozen"
            cell["generation_terminal"] = completion["status"] in {"invalid", "failed"} and bool(completion.get("cache_sha256"))
            ledger_path = root / "freeze_ledger.json"
            if completion["valid"] and ledger_path.exists():
                failed = [row for row in read(ledger_path)
                          if row.get("case") == case and row.get("round") == round_id
                          and row.get("stage") == "freeze" and row.get("returncode") not in (None, 0)]
                if len(failed) == 1:
                    log = Path(failed[0]["log"]).resolve()
                    if not log.is_relative_to(root.resolve()):
                        raise ValueError("Freeze-failure evidence escapes the experiment directory")
                    cell.update(status="mechanical_freeze_failed", generation_terminal=True,
                                freeze_failure={"ledger_sha256": digest(ledger_path), "log_sha256": digest(log),
                                                "record": failed[0]})
            return cell
        manifest = read(manifest_path)
        meta = manifest.get("metadata", {})
        artifact_hash = digest(manifest_path)
        if manifest.get("case_id") != case or meta.get("completion_round") != round_id:
            raise ValueError("Frozen artifact case/completion_round mismatch")
        if not completion["valid"] or completion["status"] != "complete":
            raise ValueError("Frozen artifact lacks a valid completed model round")
        for row in manifest.get("files", []):
            if digest(checked_path(manifest_path.parent, row["source"])) != row["sha256"]:
                raise ValueError("Frozen test bytes differ from their manifest")
        receipt = read(directory / "freezes/direct.json")
        if receipt.get("artifact_sha256") != artifact_hash:
            raise ValueError("Freeze receipt hash mismatch")
        compatible = read(directory / "prepare.json")
        check_files(directory, compatible["files_sha256"])
        if compatible.get("transport_prepare_sha256") != digest(prepare):
            raise ValueError("Round input provenance differs from case preparation")
        declarations = meta.get("obligations", [])
        control_names = set(meta.get("controls", []))
        control_names.update(row["id"] for row in declarations if row.get("is_control"))
        obligations = [row for row in declarations if not row.get("is_control") and row["id"] not in control_names]
        ids = [row["id"] for row in obligations]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate static obligation IDs")
        runs = {}
        for program in ("candidate", "reference") if include_reference else ("candidate",):
            path = directory / "execution/direct" / program / "result.json"
            run = read(path) if path.exists() else None
            if run and (run.get("artifact_sha256") != artifact_hash or run.get("case_id") != case
                        or run.get("program") != program):
                raise ValueError(f"{program} ran a different case/artifact")
            runs[program] = run
            if run is not None:
                cell[program + "_result_sha256"] = digest(path)
        cell.update(frozen=True, generation_terminal=True, artifact_sha256=artifact_hash,
                    generated=len(obligations), status="zero_generated" if not obligations else "frozen",
                    unsupported=meta.get("unsupported", []),
                    generation_counts=compatible.get("generation_counts", {}),
                    reference_read=include_reference,
                    run_status={name: run.get("status") if run else "missing" for name, run in runs.items()},
                    run_errors={name: global_errors(run) for name, run in runs.items()},
                    source_controls={name: control_state(sorted(control_names), run) for name, run in runs.items()})
        for row in obligations:
            item = {"id": row["id"], "candidate_id": row.get("candidate_id"),
                    "controls": dependencies(row), "semantic_verdict": "unknown"}
            for name, run in runs.items():
                item[name] = obligation_state(row["id"], item["controls"], run)
            cell["obligations"].append(item)
    except (OSError, ValueError, KeyError, TypeError) as error:
        cell["status"] = "integrity_error"
        cell["integrity_errors"].append(f"{type(error).__name__}: {error}")
        cell["generation_terminal"] = False
    return cell


def inspect_matrix(root: Path, *, include_reference=False) -> list[dict]:
    return [inspect_cell(root, case, round_id, include_reference=include_reference)
            for case in CASES for round_id in ROUNDS]


def generation_identity(cells: list[dict]) -> list[dict]:
    return [{"case_id": row["case_id"], "round": row["round"],
             "transport_prepare_sha256": row.get("transport_prepare_sha256"),
             "artifact_sha256": row.get("artifact_sha256"),
             "completion_marker_sha256": row.get("completion", {}).get("marker_sha256"),
             "completion_cache_sha256": row.get("completion", {}).get("cache_sha256"),
             **({"freeze_failure": row["freeze_failure"]} if row.get("freeze_failure") else {}),
             "generation_terminal": row["generation_terminal"]} for row in cells]


def review_key(row: dict) -> tuple:
    return (row["case_id"], row["round"], row["obligation_id"], row["artifact_sha256"])


def review_template(cells: list[dict]) -> list[dict]:
    return [{"case_id": cell["case_id"], "round": cell["round"], "obligation_id": row["id"],
             "artifact_sha256": cell["artifact_sha256"], "verdict": "unknown",
             "reviewer": "", "reason": "", "evidence": []}
            for cell in cells for row in cell["obligations"]]


def check_evidence(records: list[dict], source: Path) -> None:
    for record in records:
        path = Path(record["path"])
        if not path.is_absolute():
            path = source.parent / path
        if path.name.startswith(".env"):
            raise ValueError("Credential files are not semantic evidence")
        if digest(path) != record["sha256"]:
            raise ValueError("Semantic evidence hash differs from review")


def validated_reviews(document: dict, cells: list[dict], source: Path) -> dict:
    expected = {review_key(row) for row in review_template(cells)}
    indexed = {}
    for row in document["reviews"]:
        key = review_key(row)
        if key not in expected or key in indexed:
            raise ValueError("Unknown, mismatched, or duplicate oracle review")
        if row.get("verdict") not in VERDICTS:
            raise ValueError("Unknown oracle verdict")
        if not row.get("reviewer") or not row.get("reason"):
            raise ValueError("Every sealed review needs reviewer and reasoning, including unknown")
        if row["verdict"] != "unknown" and not row.get("evidence"):
            raise ValueError("Semantic verdict requires independently reviewable evidence")
        check_evidence(row.get("evidence", []), source)
        indexed[key] = row
    if set(indexed) != expected:
        raise ValueError("Oracle seal must cover every frozen obligation; use explicit unknown when unresolved")
    return indexed


def seal_reviews(root: Path, review_path: Path) -> dict:
    cells = inspect_matrix(root)
    if not all(row["generation_terminal"] and not row["integrity_errors"] for row in cells):
        raise ValueError("All 14 generation units must terminate before oracle sealing")
    for cell in cells:
        reference = Path(cell["directory"]) / "execution/direct/reference"
        if reference.exists():
            raise ValueError("Reference execution directory already exists before oracle seal")
    document = read(review_path)
    indexed = validated_reviews(document, cells, review_path)
    # Store absolute evidence paths so relocating the input review is unambiguous.
    reviews = []
    for row in indexed.values():
        row = dict(row)
        row["evidence"] = [dict(item, path=str((review_path.parent / item["path"]).resolve()))
                           for item in row.get("evidence", [])]
        reviews.append(row)
    identity = generation_identity(cells)
    return {"version": VERSION, "kind": "oracle_seal", "sealed_at": datetime.now(timezone.utc).isoformat(),
            "experiment_root": str(root.resolve()), "generation_identity": identity,
            "generation_identity_sha256": canonical_hash(identity), "reviews": reviews,
            "source_reviews_sha256": digest(review_path), "reference_directories_absent_at_seal": True,
            "review_metadata": {key: value for key, value in document.items() if key != "reviews"},
            "candidate_results_available_at_seal": [f"{row['case_id']}/{row['round']}" for row in cells
                                                    if row.get("candidate_result_sha256")],
            "limitations": "Hashes establish byte provenance, not truth of human proofs or historical data blindness."}


def load_seal(path: Path, cells: list[dict]) -> dict:
    document = read(path)
    if document.get("kind") != "oracle_seal" or not document.get("reference_directories_absent_at_seal"):
        raise ValueError("Expected an independently created pre-reference oracle seal")
    identity = generation_identity(cells)
    if document.get("generation_identity") != identity or document.get("generation_identity_sha256") != canonical_hash(identity):
        raise ValueError("Generation changed after oracle sealing")
    return validated_reviews(document, cells, path)


def adjudications(path: Path | None, cells: list[dict]) -> dict:
    if path is None:
        return {}
    expected = {review_key(row) for row in review_template(cells)}
    indexed = {}
    for row in read(path)["adjudications"]:
        key = review_key(row)
        if key not in expected or key in indexed:
            raise ValueError("Unknown, mismatched, or duplicate defect adjudication")
        if not row.get("reviewer") or not row.get("reason") or not row.get("evidence"):
            raise ValueError("Defect adjudication needs reviewer, evidence and reasoning")
        if type(row.get("confirmed_defect")) is not bool or type(row.get("known_target")) is not bool:
            raise ValueError("Defect/target decisions must be explicit booleans")
        if row["known_target"] and not row["confirmed_defect"]:
            raise ValueError("A known target hit must be an independently confirmed defect")
        if row["confirmed_defect"] and not row.get("root_cause_id"):
            raise ValueError("Confirmed defects require a root-cause identity for deduplication")
        check_evidence(row["evidence"], path)
        indexed[key] = row
    return indexed


def apply_reviews(cells: list[dict], reviews: dict, decisions: dict) -> None:
    for cell in cells:
        for row in cell["obligations"]:
            key = (cell["case_id"], cell["round"], row["id"], cell["artifact_sha256"])
            review, decision = reviews.get(key), decisions.get(key)
            verdict = review["verdict"] if review else "unknown"
            candidate = row["candidate"]
            row.update(semantic_verdict=verdict, independently_reviewed=review is not None,
                       semantic_evidence=review, defect_adjudication=decision,
                       confirmed_false_alarm=candidate["alarm"] and verdict in {"invalid_oracle", "inapplicable"},
                       unknown_oracle_alarm=candidate["alarm"] and verdict == "unknown",
                       confirmed_defect=False, known_target_hit=False)
            if decision and decision["confirmed_defect"]:
                if not candidate["alarm"] or verdict != "valid_oracle":
                    raise ValueError("Confirmed defect lacks a valid independent oracle and controlled candidate alarm")
                row.update(confirmed_defect=True, known_target_hit=decision["known_target"])
            row["unresolved_valid_alarm"] = candidate["alarm"] and verdict == "valid_oracle" and not row["confirmed_defect"]
            if "reference" in row:
                reference = row["reference"]
                row["differential_candidate"] = bool(candidate["alarm"] and reference["passed"] and reference["controls"]["passed"])
                row["reference_contract_conflict"] = reference["alarm"] and verdict == "valid_oracle"


def summarize(cells: list[dict]) -> dict:
    by_round = {}
    for round_id in ROUNDS:
        selected = [cell for cell in cells if cell["round"] == round_id]
        obligations = [row for cell in selected for row in cell["obligations"]]
        hits = [cell["case_id"] for cell in selected if any(row.get("known_target_hit") for row in cell["obligations"])]
        counts = {"case_units": len(selected), "frozen_units": sum(cell["frozen"] for cell in selected),
                  "generation_terminal_units": sum(cell["generation_terminal"] for cell in selected),
                  "generated_obligations": len(obligations), "target_hits": len(hits), "target_hit_cases": hits,
                  "target_case_denominator": len(CASES), "zero_output_units": sum(cell["frozen"] and not cell["generated"] for cell in selected),
                  "integrity_error_units": sum(bool(cell["integrity_errors"]) for cell in selected),
                  "model_protocol_failure_units": sum(cell.get("completion", {}).get("protocol_failure", False) for cell in selected),
                  "mechanical_freeze_failure_units": sum(bool(cell.get("freeze_failure")) for cell in selected),
                  "candidate_run_error_units": sum(bool(cell.get("run_errors", {}).get("candidate")) for cell in selected),
                  "unit_status": dict(Counter(cell["status"] for cell in selected)),
                  "semantic_verdicts": dict(Counter(row["semantic_verdict"] for row in obligations))}
        for field in ("confirmed_false_alarm", "unknown_oracle_alarm", "unresolved_valid_alarm", "confirmed_defect", "known_target_hit", "differential_candidate"):
            counts[field] = sum(bool(row.get(field)) for row in obligations)
        for field in ("alarm", "executed", "passed", "raw_failure"):
            counts["candidate_" + field] = sum(bool(row["candidate"][field]) for row in obligations)
        counts["candidate_runtime_leaves"] = sum(row["candidate"]["runtime_leaves"] for row in obligations)
        counts["candidate_source_control_blocked"] = sum(not row["candidate"]["controls"]["passed"] for row in obligations)
        counts["candidate_unexecuted_obligations"] = sum(not row["candidate"]["executed"] for row in obligations)
        counts["unknown_oracle_passed"] = sum(row["semantic_verdict"] == "unknown" and row["candidate"]["passed"] for row in obligations)
        counts["valid_oracle_passed"] = sum(row["semantic_verdict"] == "valid_oracle" and row["candidate"]["passed"] for row in obligations)
        counts["unique_confirmed_root_causes"] = len({(cell["case_id"], row["defect_adjudication"]["root_cause_id"])
                                                     for cell in selected for row in cell["obligations"] if row.get("confirmed_defect")})
        counts["strict_success"] = len(hits) == len(CASES) and all(cell["frozen"] and cell["generation_terminal"] for cell in selected) and not any(
            counts[field] for field in ("confirmed_false_alarm", "unknown_oracle_alarm", "unresolved_valid_alarm",
                                       "integrity_error_units", "model_protocol_failure_units", "candidate_run_error_units",
                                       "candidate_source_control_blocked", "candidate_unexecuted_obligations"))
        by_round[round_id] = counts
    completions = [cell.get("completion", {}) for cell in cells]
    return {"by_round": by_round, "strict_two_round_success": all(row["strict_success"] for row in by_round.values()),
            "reported_model_attempts": sum(row.get("attempts") or 0 for row in completions),
            "reported_external_model_calls": sum(row.get("external_model_calls") or 0 for row in completions),
            "attempt_records_unknown": sum(row.get("attempts") is None for row in completions),
            "reported_total_tokens": sum((row.get("usage") or {}).get("total_tokens") or 0 for row in completions),
            "token_usage_unknown_attempts": sum((row.get("attempts") or 0) for row in completions
                                                if (row.get("usage") or {}).get("total_tokens") is None),
            "counting_note": "Diagnostic counts overlap. Runtime leaves, static obligations, case units and root causes are separate."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=("inventory", "seal", "evaluate"))
    parser.add_argument("--experiment-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--sealed-oracles", type=Path)
    parser.add_argument("--target-reviews", type=Path)
    parser.add_argument("--include-reference", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Evaluation outputs are immutable; choose a new path")
    root = args.experiment_root.resolve()
    if args.stage == "seal":
        if args.reviews is None or args.include_reference:
            parser.error("seal requires --reviews and cannot read reference results")
        result = seal_reviews(root, args.reviews.resolve())
    else:
        if args.include_reference and (args.stage != "evaluate" or args.sealed_oracles is None):
            parser.error("Reference results require evaluate and a sealed oracle file")
        # Verify seal against candidate-only inventory before opening reference JSON.
        cells = inspect_matrix(root)
        reviews = load_seal(args.sealed_oracles.resolve(), cells) if args.sealed_oracles else {}
        if args.include_reference:
            cells = inspect_matrix(root, include_reference=True)
        decisions = adjudications(args.target_reviews.resolve() if args.target_reviews else None, cells)
        apply_reviews(cells, reviews, decisions)
        result = {"version": VERSION, "stage": args.stage, "created_at": datetime.now(timezone.utc).isoformat(),
                  "experiment_root": str(root), "declared_cases": CASES, "declared_rounds": ROUNDS,
                  "declared_units": len(CASES) * len(ROUNDS), "cells": cells,
                  "summary": summarize(cells), "generation_identity": generation_identity(cells),
                  "oracle_review_template": {"reviews": review_template(cells)},
                  "oracle_seal_sha256": digest(args.sealed_oracles) if args.sealed_oracles else None,
                  "target_reviews_sha256": digest(args.target_reviews) if args.target_reviews else None,
                  "reference_results_read": args.include_reference,
                  "interpretation": "Mechanical acceptance and reference agreement do not establish semantic validity. Unknowns and incomplete units are retained; pilots are discovery data, not blind evaluation."}
    result["evaluator_sha256"] = digest(Path(__file__))
    result["subject_executions"] = 0
    result["external_model_calls_by_evaluator"] = 0
    write_new(args.output, result)
    summary = result["summary"] if "summary" in result else {"stage": "seal", "reviews": len(result["reviews"])}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
