#!/usr/bin/env python3
"""Recompute phase-1 counts from adjudicated records and the fixed cohort.

This script does not infer or change scientific labels.  By default its output
is PROVISIONAL, even if all 88 adjudications have status "complete".  To emit
FROZEN output, pass --completion-freeze observation/completion.json (relative to
--run).  That existing file must satisfy src/fragment_reuse/blind.py's
require_observation_freeze guard and additionally bind:

    "case_count": 88,
    "task_count": 58,
    "cohort_receipt": {"path": "cases.json", "sha256": "..."},
    "canonical_sha256": {"S001": "...", ..., "S088": "..."}

Frozen mode requires Python 3.11+ because the existing guard imports tomllib.
The existing guard requires status=complete, adjudicated_cases=88, at least 264
unique unchanged receipts and all 88 independent review-A/review-B/adjudication
bindings.  This script never creates or edits completion.json.  Review files
are read only by that freeze validator; all statistics use cases.json and the
root adjudications, never reviewer proposals or precomputed `counts` fields.

Examples:
    python3.12 observation/build_census.py --output observation/census_provisional.json
    python3.12 observation/build_census.py \
        --completion-freeze observation/completion.json \
        --output observation/census_frozen.json
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


EXPECTED_IDS = tuple(f"S{i:03d}" for i in range(1, 89))
EXPECTED_TASKS = 58
ROLES = ("Trigger", "Context", "Check")
PROVENANCES = (
    "Exact Executed Fragment",
    "Related Executed Components",
    "Absent",
    None,
)
CLASS_KEYS = {
    "Exact Executed Fragment": "exact",
    "Related Executed Components": "related",
    "Absent": "absent",
    None: "null",
}
BUCKETS = ("allExact", "allKnown", "hasAbsent", "unresolved")

# These four records predate the common proposed-cardinality fields.  No
# fallback into source_proposal/source_proposals, lists or reviewer counts is
# permitted: an absent/null explicit field remains an unknown cardinality.
LEGACY_CARDINALITY_FIELDS = {
    "S001": ("verified_selected_source_units", "transferred_fragments"),
    "S002": ("verified_selected_source_units", "transferred_fragments"),
    "S006": ("executed_source_units", "transferred_fragments"),
    "S085": ("executed_source_units", "transferred_semantic_fragments"),
}
COMMON_CARDINALITY_FIELDS = (
    "proposed_source_units",
    "proposed_transferred_fragments",
)


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_document(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value, digest_bytes(raw)


def rooted(run: Path, value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else run / path).resolve()


def receipt(path: Path, run: Path, sha: str) -> dict:
    try:
        name = str(path.relative_to(run))
    except ValueError:
        name = str(path)
    return {"path": name, "sha256": sha}


def cardinality(record: dict) -> dict:
    sid = record["case_id"]
    assembly = record.get("minimal_assembly")
    if not isinstance(assembly, dict):
        raise ValueError(f"{sid}: minimal_assembly object required")
    names = LEGACY_CARDINALITY_FIELDS.get(sid, COMMON_CARDINALITY_FIELDS)
    scope = "observed_construction" if sid in LEGACY_CARDINALITY_FIELDS else "proposed_construction"
    result = {}
    for key, field in zip(("source_units", "transferred_fragments"), names):
        value = assembly.get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{sid}: nonnegative integer or null required at minimal_assembly.{field}")
        result[key] = {
            "value": value,
            "source_field": "minimal_assembly." + field,
            "scope": scope,
            "missing_reason": (
                "field_absent" if field not in assembly else "explicit_null" if value is None else None
            ),
        }
    return result


def provenance_bucket(values: list[str | None]) -> str:
    """Mutually exclusive, with unresolved > absent > related > all exact."""
    if any(value is None for value in values):
        return "unresolved"
    if "Absent" in values:
        return "hasAbsent"
    if "Related Executed Components" in values:
        return "allKnown"
    # Universal all-exact also covers an explicitly empty missing-factor list;
    # such cases are separately listed and never count as "has exact factor".
    return "allExact"


def build_census(run: Path, cohort_path: Path, canonical_dir: Path) -> tuple[dict, dict]:
    cohort, cohort_sha = read_document(cohort_path)
    rows = cohort.get("cases")
    if not isinstance(rows, list):
        raise ValueError("cohort cases list required")
    by_id = {}
    for row in rows:
        sid = row.get("screen_id")
        if sid in by_id:
            raise ValueError(f"duplicate cohort case: {sid}")
        by_id[sid] = row
    if set(by_id) != set(EXPECTED_IDS) or len(rows) != 88:
        raise ValueError("cohort must contain precisely S001 through S088")
    tasks = {row.get("task") for row in rows}
    if any(not isinstance(task, str) or not task for task in tasks) or len(tasks) != EXPECTED_TASKS:
        raise ValueError("cohort must identify precisely 58 nonempty task names")
    if cohort.get("cohort_size") != 88 or cohort.get("tasks") != EXPECTED_TASKS:
        raise ValueError("cohort declared case/task counts differ from 88/58")

    records, shas, paths, case_data, factor_rows = {}, {}, {}, {}, []
    for sid in EXPECTED_IDS:
        path = canonical_dir / (sid + ".json")
        record, sha = read_document(path)
        if record.get("case_id") != sid or record.get("trial") != by_id[sid]["trial"]:
            raise ValueError(f"{sid}: canonical identity differs from cohort")
        if "task" in record and record["task"] != by_id[sid]["task"]:
            raise ValueError(f"{sid}: canonical task differs from cohort")
        known = by_id[sid].get("known_case")
        if "known_case" in record and record["known_case"] != known:
            raise ValueError(f"{sid}: canonical known_case differs from cohort")
        missing = record.get("missing_factors")
        if not isinstance(missing, list):
            raise ValueError(f"{sid}: missing_factors list required")
        factor_ids = set()
        values = []
        for index, factor in enumerate(missing):
            fid = factor.get("factor_id")
            if not isinstance(fid, str) or not fid or fid in factor_ids:
                raise ValueError(f"{sid}: missing/duplicate factor_id at index {index}")
            factor_ids.add(fid)
            role = factor.get("role")
            if role not in ROLES or "provenance_class" not in factor:
                raise ValueError(f"{sid}/{fid}: explicit supported role/provenance required")
            value = factor["provenance_class"]
            if value not in PROVENANCES:
                raise ValueError(f"{sid}/{fid}: unknown provenance {value!r}")
            values.append(value)
            factor_rows.append({
                "case_id": sid,
                "factor_id": fid,
                "role": role,
                "provenance_class": value,
                "canonical_sha256": sha,
                "semantic_condition": factor.get("semantic_condition"),
            })
        joint = record.get("historical_joint_witness")
        if not isinstance(joint, dict) or "complete_assertion_witness" not in joint:
            raise ValueError(f"{sid}: explicit historical_joint_witness.complete_assertion_witness required")
        complete = joint["complete_assertion_witness"]
        other_complete = joint.get("other_task_behavior_complete_assertion_witness")
        if complete is not None and type(complete) is not bool:
            raise ValueError(f"{sid}: complete historical witness must be boolean or null")
        if other_complete is not None and type(other_complete) is not bool:
            raise ValueError(f"{sid}: other-task historical witness must be boolean or null")
        records[sid], shas[sid], paths[sid] = record, sha, path
        case_data[sid] = {
            "case_id": sid,
            "task": by_id[sid]["task"],
            "trial": by_id[sid]["trial"],
            "known_case": known,
            "canonical": receipt(path, run, sha),
            "canonical_status": record.get("status"),
            "missing_factor_count": len(missing),
            "missing_factor_counts": {CLASS_KEYS[value]: values.count(value) for value in PROVENANCES},
            "provenance_bucket": provenance_bucket(values),
            "has_exact_missing_factor": "Exact Executed Fragment" in values,
            "has_absent_missing_factor": "Absent" in values,
            "has_null_missing_factor": None in values,
            "historical_primary_complete_assertion_witness": complete,
            "historical_other_task_complete_assertion_witness": other_complete,
            "historical_joint_witness_source_field": "historical_joint_witness",
            "assembly_cardinality": cardinality(record),
        }

    def group(ids) -> dict:
        ids = sorted(set(ids))
        grouped_tasks = defaultdict(list)
        for sid in ids:
            grouped_tasks[case_data[sid]["task"]].append(sid)
        return {
            "case_count": len(ids),
            "task_count": len(grouped_tasks),
            "case_ids": ids,
            "canonical_sha256": {sid: shas[sid] for sid in ids},
            "task_case_ids": dict(sorted(grouped_tasks.items())),
        }

    role_class = {}
    for role in ROLES:
        role_class[role] = {}
        for value in PROVENANCES:
            factors = [f for f in factor_rows if f["role"] == role and f["provenance_class"] == value]
            entry = group(f["case_id"] for f in factors)
            entry.update(factor_count=len(factors), factors=factors)
            role_class[role][CLASS_KEYS[value]] = entry

    all_class = {}
    for value in PROVENANCES:
        factors = [f for f in factor_rows if f["provenance_class"] == value]
        entry = group(f["case_id"] for f in factors)
        entry.update(factor_count=len(factors), factors=factors)
        all_class[CLASS_KEYS[value]] = entry

    buckets = {name: group(sid for sid, row in case_data.items() if row["provenance_bucket"] == name)
               for name in BUCKETS}
    if sum(entry["case_count"] for entry in buckets.values()) != 88:
        raise AssertionError("case bucket partition failed")
    task_buckets = {name: [] for name in BUCKETS}
    for task in sorted(tasks):
        ids = [sid for sid in EXPECTED_IDS if case_data[sid]["task"] == task]
        values = [f["provenance_class"] for f in factor_rows if f["case_id"] in ids]
        task_buckets[provenance_bucket(values)].extend(ids)

    def histogram(metric: str, scope: str | None = None) -> dict:
        selected = [(sid, row["assembly_cardinality"][metric]) for sid, row in case_data.items()
                    if scope is None or row["assembly_cardinality"][metric]["scope"] == scope]
        values = sorted({item["value"] for _, item in selected if item["value"] is not None})
        result = {}
        for value in [*values, None]:
            ids = [sid for sid, item in selected if item["value"] == value]
            if ids or value is None:
                result["null" if value is None else str(value)] = group(ids)
        return result

    known_groups = {}
    for label in sorted({row["known_case"] for row in case_data.values() if row["known_case"] is not None}):
        known_groups[label] = group(sid for sid, row in case_data.items() if row["known_case"] == label)
    cohort_receipt = receipt(cohort_path, run, cohort_sha)
    input_manifest = {"cohort": cohort_receipt, "canonical_sha256": shas}
    result = {
        "schema_version": "fragment-phase1-census.v1",
        "status": "provisional",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_policy": "Statistics use only fixed cohort cases.json and root canonical records; reviewer proposals, precomputed counts and source/execution outcomes are not reinterpreted.",
        "inputs": input_manifest,
        "input_manifest_sha256": digest_bytes(json.dumps(input_manifest, sort_keys=True, separators=(",", ":")).encode()),
        "definitions": {
            "denominator": "88 trajectories and 58 distinct cohort task names; missing factors only, excluding required factors already present in the base.",
            "case_buckets": {
                "precedence": ["unresolved", "hasAbsent", "allKnown", "allExact"],
                "allExact": "Every missing factor is Exact; empty lists satisfy this universally and are separately listed.",
                "allKnown": "Every missing factor is Exact/Related and at least one is Related; excludes allExact to keep the buckets mutually exclusive.",
                "hasAbsent": "At least one Absent and no null factor.",
                "unresolved": "At least one explicit null provenance, regardless of other factors; no oracle/execution uncertainty is inferred into this bucket.",
            },
            "task_buckets": "Apply the same precedence to all missing factors pooled over trajectories of that task. Case-group task counts otherwise count membership and may overlap across case buckets.",
            "historical_witness": "Only the explicit primary complete_assertion_witness flag; printed effects, implicit relations, P/R results and additional prose are not reclassified. Explicit other_task_behavior_complete_assertion_witness is reported separately.",
            "cardinality": "Reported construction counts, not global or validated minima. The four legacy fields are mapped explicitly; null/absent fields stay unknown. Nested reviewer/source proposals, list lengths, conditional components and record-edit counts are not substitutes.",
            "legacy_cardinality_fields": {sid: {"source_units": "minimal_assembly." + fields[0], "transferred_fragments": "minimal_assembly." + fields[1]} for sid, fields in LEGACY_CARDINALITY_FIELDS.items()},
            "common_cardinality_fields": {"source_units": "minimal_assembly." + COMMON_CARDINALITY_FIELDS[0], "transferred_fragments": "minimal_assembly." + COMMON_CARDINALITY_FIELDS[1]},
            "S085_fragment_scope": "transferred_semantic_fragments; two record edits are not counted as two semantic fragments.",
        },
        "denominator": group(EXPECTED_IDS),
        "missing_factors": {"factor_count": len(factor_rows), "by_provenance": all_class, "by_role_and_provenance": role_class},
        "case_buckets": buckets,
        "task_buckets": {name: group(ids) for name, ids in task_buckets.items()},
        "cumulative_case_flags": {
            "has_at_least_one_exact_missing_factor": group(sid for sid, row in case_data.items() if row["has_exact_missing_factor"]),
            "all_missing_factors_known_including_allExact": group(sid for sid, row in case_data.items() if row["provenance_bucket"] in ("allExact", "allKnown")),
            "has_any_absent_factor_including_unresolved_cases": group(sid for sid, row in case_data.items() if row["has_absent_missing_factor"]),
            "no_missing_factors": group(sid for sid, row in case_data.items() if row["missing_factor_count"] == 0),
        },
        "historical_witness": {
            "primary_complete": group(sid for sid, row in case_data.items() if row["historical_primary_complete_assertion_witness"] is True),
            "primary_not_complete": group(sid for sid, row in case_data.items() if row["historical_primary_complete_assertion_witness"] is False),
            "primary_null": group(sid for sid, row in case_data.items() if row["historical_primary_complete_assertion_witness"] is None),
            "explicit_other_task_complete": group(sid for sid, row in case_data.items() if row["historical_other_task_complete_assertion_witness"] is True),
            "primary_or_explicit_other_task_complete": group(sid for sid, row in case_data.items() if row["historical_primary_complete_assertion_witness"] is True or row["historical_other_task_complete_assertion_witness"] is True),
        },
        "known_cases": {
            "marked": group(sid for sid, row in case_data.items() if row["known_case"] is not None),
            "unmarked": group(sid for sid, row in case_data.items() if row["known_case"] is None),
            "by_marker": known_groups,
        },
        "assembly_cardinality": {
            "source_units": histogram("source_units"),
            "transferred_fragments": histogram("transferred_fragments"),
            "observed_constructions": {
                "source_units": histogram("source_units", "observed_construction"),
                "transferred_fragments": histogram("transferred_fragments", "observed_construction"),
            },
            "proposed_constructions": {
                "source_units": histogram("source_units", "proposed_construction"),
                "transferred_fragments": histogram("transferred_fragments", "proposed_construction"),
            },
        },
        "cases": [case_data[sid] for sid in EXPECTED_IDS],
    }
    snapshot = {"cohort_path": cohort_path, "cohort_sha256": cohort_sha, "canonical_paths": paths,
                "canonical_sha256": shas, "canonical_status": {sid: r.get("status") for sid, r in records.items()}}
    return result, snapshot


def assert_snapshot_unchanged(snapshot: dict) -> None:
    if digest_bytes(snapshot["cohort_path"].read_bytes()) != snapshot["cohort_sha256"]:
        raise ValueError("cohort changed while census was being built")
    for sid, path in snapshot["canonical_paths"].items():
        if digest_bytes(path.read_bytes()) != snapshot["canonical_sha256"][sid]:
            raise ValueError(f"{sid}: canonical changed while census was being built")


def validate_freeze(run: Path, path: Path, snapshot: dict) -> dict:
    expected = (run / "observation/completion.json").resolve()
    if path != expected:
        raise ValueError("completion freeze must be this run's observation/completion.json")
    # Use the existing gate, rather than a weaker status-only local definition.
    if sys.version_info < (3, 11):
        raise ValueError("frozen mode needs Python 3.11+ for the project freeze guard; use python3.12")
    project = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(project / "src"))
    from fragment_reuse.blind import require_observation_freeze
    gate_receipt = require_observation_freeze(run)
    completion, completion_sha = read_document(path)
    if completion_sha != gate_receipt["sha256"]:
        raise ValueError("completion changed during gate validation")
    if completion.get("case_count") != 88 or completion.get("task_count") != EXPECTED_TASKS:
        raise ValueError("completion must explicitly bind case_count=88 and task_count=58")
    cohort_receipt = completion.get("cohort_receipt", {})
    if (rooted(run, cohort_receipt.get("path", "")) != snapshot["cohort_path"]
            or cohort_receipt.get("sha256") != snapshot["cohort_sha256"]):
        raise ValueError("completion cohort receipt differs from current census input")
    if completion.get("canonical_sha256") != snapshot["canonical_sha256"]:
        raise ValueError("completion must bind the exact current 88 canonical SHA256 values")
    snapshot["frozen_bound_paths"] = {rooted(run, item["path"]) for item in completion["receipts"]}
    if any(status != "complete" for status in snapshot["canonical_status"].values()):
        raise ValueError("all canonical statuses must be complete for a frozen census")
    indexed = {row["case_id"]: row for row in completion["cases"]}
    for sid, canonical in snapshot["canonical_paths"].items():
        if rooted(run, indexed[sid]["adjudication"]) != canonical:
            raise ValueError(f"{sid}: freeze adjudication differs from census canonical path")
    assert_snapshot_unchanged(snapshot)
    return {"path": str(path), "sha256": completion_sha,
            "guard": "src/fragment_reuse/blind.py::require_observation_freeze",
            "extra_binding_checks": ["88/58", "cohort SHA256", "all 88 canonical SHA256 values", "canonical paths", "all adjudications complete"]}


def write_case_csv(path: Path, result: dict) -> None:
    fields = ["case_id", "task", "trial", "known_case", "canonical_sha256", "census_status",
              "provenance_bucket", "missing_factor_count", "exact", "related", "absent", "null",
              "primary_complete_historical_witness", "explicit_other_task_complete_historical_witness",
              "source_units", "source_units_field", "source_units_scope", "source_units_missing_reason",
              "transferred_fragments", "fragments_field", "fragments_scope", "fragments_missing_reason"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in result["cases"]:
            units = row["assembly_cardinality"]["source_units"]
            fragments = row["assembly_cardinality"]["transferred_fragments"]
            writer.writerow({
                "case_id": row["case_id"], "task": row["task"], "trial": row["trial"],
                "known_case": row["known_case"], "canonical_sha256": row["canonical"]["sha256"],
                "census_status": result["status"], "provenance_bucket": row["provenance_bucket"],
                "missing_factor_count": row["missing_factor_count"], **row["missing_factor_counts"],
                "primary_complete_historical_witness": row["historical_primary_complete_assertion_witness"],
                "explicit_other_task_complete_historical_witness": row["historical_other_task_complete_assertion_witness"],
                "source_units": units["value"], "source_units_field": units["source_field"],
                "source_units_scope": units["scope"], "source_units_missing_reason": units["missing_reason"],
                "transferred_fragments": fragments["value"], "fragments_field": fragments["source_field"],
                "fragments_scope": fragments["scope"], "fragments_missing_reason": fragments["missing_reason"],
            })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--cohort", default="cases.json", help="cohort path relative to --run, or absolute")
    parser.add_argument("--canonical-dir", default="observation/adjudicated", help="root canonical directory")
    parser.add_argument("--completion-freeze", help="existing observation/completion.json; mandatory for frozen output")
    parser.add_argument("--output", type=Path, help="write JSON here; default: stdout; never overwrites inputs or completion.json")
    parser.add_argument("--csv-output", type=Path, help="optional per-case CSV; blank cardinalities are unknown, never inferred zero")
    args = parser.parse_args(argv)
    run = args.run.resolve()
    cohort_path = rooted(run, args.cohort)
    canonical_dir = rooted(run, args.canonical_dir)
    try:
        result, snapshot = build_census(run, cohort_path, canonical_dir)
        result["script"] = {"path": str(Path(__file__).resolve()), "sha256": digest_bytes(Path(__file__).read_bytes())}
        if args.completion_freeze:
            result["completion_freeze"] = validate_freeze(run, rooted(run, args.completion_freeze), snapshot)
            result["status"] = "frozen"
        else:
            result["completion_freeze"] = None
            result["provisional_reason"] = "No explicit validated completion freeze was supplied; complete adjudication records alone do not freeze the census."
        assert_snapshot_unchanged(snapshot)
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        protected = {cohort_path, (run / "observation/completion.json").resolve(), Path(__file__).resolve(), *snapshot["canonical_paths"].values()}
        protected.update(snapshot.get("frozen_bound_paths", set()))
        outputs = [path.resolve() for path in (args.output, args.csv_output) if path is not None]
        protected_dirs = [canonical_dir, *(run / "observation" / name for name in ("reviewer_A", "reviewer_B", "frozen_reviews"))]
        if (len(outputs) != len(set(outputs)) or any(path in protected for path in outputs)
                or any(path.is_relative_to(directory) for path in outputs for directory in protected_dirs)):
            raise ValueError("refusing overlapping outputs or overwrite of inputs, script or completion.json")
        if args.output:
            output = args.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text)
        else:
            sys.stdout.write(text)
        if args.csv_output:
            write_case_csv(args.csv_output.resolve(), result)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"census error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
