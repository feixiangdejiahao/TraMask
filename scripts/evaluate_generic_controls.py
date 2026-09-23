"""Evaluator-only audit of frozen synthetic-control experiments.

No generation, model calls, artifact filtering, or reference-patch reads occur
here. A passing reference is not an oracle verdict. Semantic verdicts require a
separate human contract audit tied to frozen artifact and sealed-evidence hashes.
Unreviewed obligations remain unknown, including obligations passing both runs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from combination_testing.evaluate import _matches
from combination_testing.runner import load_artifact

VARIANTS = ("r1", "r2", "direct")
SEMANTIC_VERDICTS = {"valid_in_sealed_domain", "valid_by_contract", "invalid_oracle",
                     "invalid_precondition", "unknown"}
VALID_VERDICTS = {"valid_in_sealed_domain", "valid_by_contract"}


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(Path(path).read_text())


def sealed_assets(directory: Path) -> dict:
    """Verify archived original bytes and reconstructed correct repositories."""
    directory = Path(directory).resolve()
    seal = read_json(directory / "seal.json")
    for filename, key in (("source_manifest.json", "manifest_sha256"),
                           ("oracle_table.json", "oracle_table_sha256"),
                           ("correct_replacements.json", "correct_replacements_sha256")):
        if sha256(directory / filename) != seal[key]:
            raise ValueError(f"Sealed evaluator asset changed: {filename}")
    manifest = read_json(directory / "source_manifest.json")
    replacements = read_json(directory / "correct_replacements.json")
    truth = read_json(directory / "oracle_table.json")
    for case in manifest:
        for item in case["files"]:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid evaluator source path")
            candidate = directory / "inputs" / case["id"] / relative
            if sha256(candidate) != item["sha256"]:
                raise ValueError(f"Sealed control input changed: {case['id']}/{relative}")
            replacement = replacements.get(case["id"], {}).get(item["path"])
            expected = replacement.encode() if replacement is not None else candidate.read_bytes()
            actual = directory / "correct" / case["id"] / relative
            if actual.read_bytes() != expected:
                raise ValueError(f"Correct control reconstruction changed: {case['id']}/{relative}")
    return {"root": directory, "seal": seal, "manifest": manifest, "truth": truth,
            "seal_sha256": sha256(directory / "seal.json")}


def load_reviews(path: Path | None, assets: dict) -> dict:
    """Check evidence provenance, not the soundness of a human's proof."""
    if path is None:
        return {}
    records = read_json(path)
    records = records["reviews"] if isinstance(records, dict) else records
    indexed = {}
    for record in records:
        key = (record["case_id"], record["variant"], record["id"], record["artifact_sha256"])
        if key in indexed or record["variant"] not in VARIANTS or record["case_id"] not in assets["truth"]:
            raise ValueError("Duplicate review or unregistered variant")
        verdict = record.get("verdict")
        if verdict not in SEMANTIC_VERDICTS:
            raise ValueError("Unknown semantic verdict")
        if verdict != "unknown":
            if not record.get("reviewer") or not record.get("basis"):
                raise ValueError("A semantic verdict requires an identified reviewer and independent reasoning")
            if record.get("basis_kind") not in {"sealed_finite_table", "contract_derivation"}:
                raise ValueError("Runtime agreement/reference pass is not an independent oracle basis")
            if not record.get("evidence"):
                raise ValueError("Semantic verdict needs hash-pinned sealed evidence")
            for evidence in record["evidence"]:
                relative = Path(evidence["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Evidence must be relative to the evaluator archive")
                source = (assets["root"] / relative).resolve()
                if not source.is_relative_to(assets["root"]) or sha256(source) != evidence["sha256"]:
                    raise ValueError("Semantic evidence changed")
            if verdict == "valid_in_sealed_domain":
                rows = record.get("gold_rows", [])
                maximum = len(assets["truth"][record["case_id"]]["rows"])
                if not rows or any(not isinstance(row, int) or not 0 <= row < maximum for row in rows):
                    raise ValueError("Sealed-domain validity requires existing finite-table row indices")
        indexed[key] = record
    return indexed


def matching(name: str, tests: list[dict]) -> list[dict]:
    return [row for row in tests if _matches(name, row["id"])]


def control_state(names: list[str], result: dict | None) -> dict:
    if result is None:
        return {"declared": len(names), "passed": False, "missing": list(names), "failed": [], "skipped": [], "errors": [], "global_error": False}
    missing, failed, skipped, errors = [], [], [], []
    for name in names:
        rows = matching(name, result.get("tests", []))
        if not rows:
            missing.append(name)
        elif any(row["status"] == "error" for row in rows):
            errors.append(name)
        elif any(row["status"] == "fail" for row in rows):
            failed.append(name)
        elif any(row["status"] != "pass" for row in rows):
            skipped.append(name)
    global_error = bool(result.get("errors"))
    return {"declared": len(names), "passed": bool(names) and not (missing or failed or skipped or errors or global_error),
            "missing": missing, "failed": failed, "skipped": skipped, "errors": errors,
            "global_error": global_error}


def _dependencies(obligation: dict) -> list[str]:
    values = []
    for key in ("controls", "control_ids"):
        value = obligation.get(key, [])
        values.extend([value] if isinstance(value, str) else value)
    values.extend(obligation[key] for key in ("control", "control_id") if obligation.get(key))
    return list(dict.fromkeys(values))


def audit_cell(experiment: Path, case: dict, variant: str, assets: dict, reviews: dict) -> dict:
    case_id = case["id"]
    directory = Path(experiment) / case_id
    artifact = directory / "frozen" / variant
    result = {"case_id": case_id, "variant": variant,
              "negative_control": assets["truth"][case_id]["candidate_known_correct"],
              "status": "not_frozen", "generated": 0, "obligations": [], "counts": {}}
    if not (artifact / "manifest.json").exists():
        admission = directory / "admission" / f"{variant}.json"
        if admission.exists():
            result["admission_status"] = read_json(admission).get("status")
        return result
    manifest = load_artifact(artifact)
    if manifest["case_id"] != case_id:
        raise ValueError("Frozen artifact has a different case ID")
    artifact_hash = sha256(artifact / "manifest.json")
    receipt = directory / "freezes" / f"{variant}.json"
    if receipt.exists() and read_json(receipt)["artifact_sha256"] != artifact_hash:
        raise ValueError("Artifact differs from freeze receipt")
    metadata = manifest.get("metadata", {})
    declarations = metadata.get("obligations", [])
    control_names = set(metadata.get("controls", []))
    control_names.update(row["id"] for row in declarations if row.get("is_control"))
    obligations = [row for row in declarations if not row.get("is_control") and row["id"] not in control_names]
    result.update(artifact_sha256=artifact_hash, generated=len(obligations),
                  accepted=len(metadata.get("accepted_candidate_ids", [])),
                  proposed=metadata.get("candidate_count"), unsupported=metadata.get("unsupported", []),
                  status="zero_generated" if not obligations else "awaiting_execution")
    runs = {}
    for program in ("candidate", "reference"):
        path = directory / "execution" / variant / program / "result.json"
        run = read_json(path) if path.exists() else None
        if run is not None and run["artifact_sha256"] != artifact_hash:
            raise ValueError(f"{program} ran a different artifact")
        runs[program] = run
    result["source_controls"] = {program: control_state(sorted(control_names), run) for program, run in runs.items()}
    result["run_status"] = {program: run.get("status") if run else "missing" for program, run in runs.items()}
    for declaration in obligations:
        oid = declaration["id"]
        dependencies = _dependencies(declaration)
        programs = {}
        for program, run in runs.items():
            rows = matching(oid, run.get("tests", [])) if run else []
            controls = control_state(dependencies, run)
            infrastructure = bool(run and run.get("errors")) or any(row["status"] == "error" for row in rows)
            programs[program] = {"controls": controls, "outcomes": [{key: row.get(key) for key in ("id", "status", "kind")} for row in rows],
                                 "infrastructure": infrastructure, "executed": bool(rows),
                                 "passed": bool(rows) and all(row["status"] == "pass" for row in rows),
                                 "alarm": bool(rows) and any(row["status"] == "fail" for row in rows) and controls["passed"] and not infrastructure}
        candidate, reference = programs["candidate"], programs["reference"]
        review = reviews.get((case_id, variant, oid, artifact_hash))
        semantic = review["verdict"] if review else "unknown"
        disposition = "semantic_unknown"
        if candidate["infrastructure"]:
            disposition = "infrastructure"
        elif not candidate["executed"]:
            disposition = "not_executed"
        elif not dependencies:
            disposition = "source_controls_undeclared"
        elif not candidate["controls"]["passed"]:
            disposition = "source_controls_failed_or_missing"
        elif semantic == "invalid_precondition":
            disposition = "invalid_input_or_precondition"
        elif semantic == "invalid_oracle":
            disposition = "invalid_oracle"
        elif semantic in VALID_VERDICTS:
            if candidate["alarm"] and result["negative_control"]:
                disposition = "negative_control_semantic_contradiction"
            elif candidate["alarm"]:
                disposition = "confirmed_interaction_defect"
            elif candidate["passed"]:
                disposition = "valid_no_candidate_alarm"
            else:
                disposition = "inconclusive_execution"
        result["obligations"].append({"id": oid, "candidate_id": declaration.get("candidate_id"),
            "disposition": disposition, "semantic_verdict": semantic, "reviewed": review is not None,
            "candidate": candidate, "reference": reference,
            "differential_candidate": candidate["alarm"] and reference["passed"] and reference["controls"]["passed"] and not reference["infrastructure"],
            "reference_contract_conflict": semantic in VALID_VERDICTS and reference["alarm"],
            "confirmed_defect": disposition == "confirmed_interaction_defect",
            "confirmed_false_alarm": candidate["alarm"] and semantic in {"invalid_precondition", "invalid_oracle"}})
    counts = Counter(row["disposition"] for row in result["obligations"])
    for field in ("differential_candidate", "reference_contract_conflict", "confirmed_defect", "confirmed_false_alarm", "reviewed"):
        counts[field] = sum(bool(row[field]) for row in result["obligations"])
    counts["candidate_alarms"] = sum(row["candidate"]["alarm"] for row in result["obligations"])
    counts["reference_alarms"] = sum(row["reference"]["alarm"] for row in result["obligations"])
    counts["semantic_unknown_alarms"] = sum(row["candidate"]["alarm"] and row["semantic_verdict"] == "unknown" for row in result["obligations"])
    for label in ("failed", "missing", "skipped", "errors"):
        counts["obligations_with_source_control_" + label] = sum(bool(row["candidate"]["controls"][label]) for row in result["obligations"])
    result["counts"] = dict(counts)
    result["detected_known_interaction"] = bool(counts["confirmed_defect"])
    if obligations and runs["candidate"] is not None:
        result["status"] = "audited" if runs["reference"] is not None else "candidate_only"
    return result


def summarize(cells: list[dict], assets: dict) -> dict:
    totals = {}
    known_fault_cases = sum(not row["candidate_known_correct"] for row in assets["truth"].values())
    known_correct_cases = len(assets["truth"]) - known_fault_cases
    for variant in VARIANTS:
        selected = [row for row in cells if row["variant"] == variant]
        counts = Counter()
        for row in selected:
            counts.update(row.get("counts", {}))
        totals[variant] = {"cases": len(selected), "status_counts": dict(Counter(row["status"] for row in selected)),
            "generated": sum(row["generated"] for row in selected), "counts": dict(counts),
            "known_fault_cases": known_fault_cases,
            "known_fault_cases_detected": sum(row.get("detected_known_interaction", False) for row in selected),
            "known_correct_cases": known_correct_cases,
            "known_correct_cases_with_confirmed_false_alarms": sum(row["negative_control"] and bool(row.get("counts", {}).get("confirmed_false_alarm")) for row in selected),
            "known_correct_cases_with_unreviewed_alarms": sum(row["negative_control"] and bool(row.get("counts", {}).get("semantic_unknown_alarms")) for row in selected)}
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", required=True, type=Path)
    parser.add_argument("--assets", default=ROOT / "evaluation_assets/generic_controls_v1", type=Path)
    parser.add_argument("--adjudications", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new audit output path; prior audits are immutable")
    assets = sealed_assets(args.assets)
    reviews = load_reviews(args.adjudications, assets)
    cells = [audit_cell(args.experiment_root, case, variant, assets, reviews)
             for case in assets["manifest"] for variant in VARIANTS]
    report = {"evaluator_sha256": sha256(Path(__file__)), "assets_seal_sha256": assets["seal_sha256"],
              "adjudications_sha256": sha256(args.adjudications) if args.adjudications else None,
              "experiment_root": str(args.experiment_root.resolve()), "cells": cells,
              "by_variant": summarize(cells, assets),
              "interpretation": "Reference outcomes are comparisons, not semantic labels. Evidence hashes validate provenance; human contract proofs remain reviewable judgments. Finite-table claims are restricted to their sealed domains. Unknowns, zero output, missing controls and infrastructure remain visible.",
              "generation_feedback": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["by_variant"], indent=2))


if __name__ == "__main__":
    main()
