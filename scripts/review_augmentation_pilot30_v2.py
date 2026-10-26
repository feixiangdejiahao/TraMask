"""Offline evidence collection for the frozen v2 pilot; no provider calls."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts.run_augmentation_pilot30_v2 import OLD, RUN, read, receipt, runtime_case
from augmentation.pipeline import write_json
from combination_testing.runner import run_artifact, compare_pair

OUT = RUN / "evaluation"


def inventory():
    cases = read(RUN / "cases.json")
    rows = []
    for case in cases:
        directory = RUN / "cases" / case["id"] / "agent"
        for path in sorted(directory.glob("*/result.json")):
            result = read(path)
            if result["status"] != "generated_test_unverified" or not result["proposals"]:
                continue
            proposal = result["proposals"][-1]
            assessment = Path(proposal["assessment"])
            record = read(assessment)
            execution_dir = assessment.parent / "execution"
            execution_path = execution_dir / "result.json"
            result_path = execution_dir / "augmented/result.json"
            run = read(result_path) if result_path.exists() else None
            rows.append({"id": case["id"] + "/" + result["candidate_id"], "case": case["id"],
                         "candidate": result["candidate_id"], "assessment": receipt(assessment),
                         "reason": record["reason"], "distinction": record["distinction"], "tests": record["tests"],
                         "candidate_run": receipt(result_path) if run else None,
                         "execution": receipt(execution_path) if execution_path.exists() else None,
                         "artifact": str(execution_dir / "artifact") if (execution_dir / "artifact/manifest.json").exists() else None,
                         "run_status": run["status"] if run else "not_executed",
                         "run_tests": run.get("tests", []) if run else [],
                         "run_errors": run.get("errors", []) if run else [],
                         "proposals_attempted": len(result["proposals"]), "round": proposal["round"]})
    write_json(OUT / "claims.json", rows)
    return rows


def pair_one(row):
    case = next(c for c in read(RUN / "cases.json") if c["id"] == row["case"])
    directory = OUT / "pairs" / row["case"] / row["candidate"]
    output = directory / "comparison.json"
    if output.exists():
        return read(output)
    if not row["candidate_run"] or not row["artifact"]:
        raise ValueError("No frozen executable test")
    original = read(row["candidate_run"]["path"])
    runtime, _ = runtime_case(case)
    gold_path = OLD / "gold_comparison_v1/cases" / case["id"] / "gold.patch"
    reference = run_artifact(Path(row["artifact"]), "reference", directory / "reference",
                             reference_patch=gold_path, registry=[runtime])
    pair = compare_pair(original, reference)
    pair.update(id=row["id"], assessment=row["assessment"], gold=receipt(gold_path))
    write_json(output, pair)
    return pair


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("stage", choices=("inventory", "show", "pair"))
    parser.add_argument("--case", action="append")
    parser.add_argument("--claim", action="append")
    parser.add_argument("--code", action="store_true")
    args = parser.parse_args()
    rows = inventory()
    selected = [r for r in rows if (not args.case or r["case"] in args.case) and (not args.claim or r["id"] in args.claim)]
    if args.stage == "inventory":
        print(json.dumps({"claims": len(rows), "tasks": len({r["case"] for r in rows}),
                          "execution": dict(Counter(r["run_status"] for r in rows))}))
    elif args.stage == "show":
        for row in selected:
            print(row["id"], row["run_status"])
            print(row["reason"])
            print(row["distinction"])
            if args.code:
                for test in row["tests"]:
                    print(test["path"], test["mode"])
                    print(test["code"])
            print(json.dumps(row["run_tests"], ensure_ascii=False)[:7000])
    else:
        if not args.claim:
            raise ValueError("Explicitly select portable claims after semantic inspection")
        with ThreadPoolExecutor(max_workers=4) as pool:
            for future in as_completed([pool.submit(pair_one, row) for row in selected]):
                print(json.dumps(future.result(), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
