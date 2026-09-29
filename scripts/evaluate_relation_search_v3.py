"""Offline evaluator for the renewed 17-trial experiment.

This module never imports generation/provider code.  It reuses the independent
native-execution and manifest checks; historical answers remain baseline evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import evaluate_relation_search_continuation as continuation
from evaluate_relation_search import CASES, read, write_new
from evaluate_relational_gap import freeze_file, verify_file

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "results/relation_search_20260929/evaluation"
OUT = ROOT / "results/relation_search_20260929_v3/evaluation"
BASELINE = "579841c9f1bb77e1af51176daca219ef08e9a532"


def initialize(args):
    old = read(OLD / "ledger.json")
    warm_path = OLD / "uniform_warm_v2/checkpoint_12.json"
    fresh_path = OLD / "uniform_fresh_v1/checkpoint_11.json"
    warm, fresh = read(warm_path), read(fresh_path)
    assert [row["case"] for row in old["cases"]] == CASES
    assert old["denominator"] == warm["denominator"] == fresh["denominator"] == 17
    witnesses = warm["fresh_evaluation"]["deliveries"]
    cases = []
    for row in old["cases"]:
        for field in ("candidate_patch", "source_corpus"):
            verify_file(row[field])
        cases.append({**row, "inherited_witnesses": [
            {"id": item["id"], "origin": "historical_replay"}
            for item in witnesses
            if item["case"] == row["case"] and item["controlled_target_detection"]
        ]})
    required = [
        warm_path, fresh_path,
        OLD / "uniform_warm_v2/checkpoint_12_reviews.json",
        OLD / "semantic_reassessments_v1.json",
        ROOT / "evaluation_assets/relational_gap_v1/target_census.json",
        ROOT / "scripts/evaluate_relation_search.py",
        ROOT / "scripts/evaluate_relational_gap.py",
        ROOT / "scripts/evaluate_relation_search_continuation.py",
        Path(__file__),
    ]
    frozen = [freeze_file(path) for path in required]
    ledger = {
        "round": "relation_search_20260929_v3",
        "role": "evaluator_only_do_not_send_to_generator_or_provider",
        "denominator": 17,
        "start_utc": "2026-09-29T11:35:35Z",
        "deadline_utc": "2026-09-29T16:35:35Z",
        "baseline_commit": BASELINE,
        "scope": "17 development trials / 14 tasks; complete original trajectory is permitted input, evaluation truth is not.",
        "baseline": {
            "frozen_files": frozen,
            "detected_cases": [row["case"] for row in cases if row["inherited_witnesses"]],
            "prior_complete_fresh_detected": fresh["counts"]["fixed_configuration_fresh_model_correct"],
            "prior_complete_warm_detected": warm["counts"]["fixed_configuration_warm_replay_correct"],
            "comparability": "Prior warm/fresh have different selections, configurations and historical semantic computation; not a cache-only ablation.",
        },
        "cases": cases,
        "completion_requirements": [
            "All 17 same-corpus cases are completed under one frozen configuration.",
            "Each case has an automatic generated combination with complete valid oracle and supported premises.",
            "Candidate patch/image/source snapshot and generated named runtime are linked by verified hashes.",
            "All associated source controls pass; generated test fails for the target relation rather than infrastructure.",
            "Semantic revisions used in the first-inference arm come from this arm's recorded requests, not the historical answer library.",
            "Historical N06 is reported as rediscovery; N08 unsupported old prefix cannot qualify.",
            "All admitted semantic modifications survive emission unchanged; partial tests are not complete oracle correctness.",
        ],
        "limits": "This phase evaluates combination detection/test synthesis, not patch repair or hidden-test issue resolution. Unknown failures are not false positives or validated witnesses.",
    }
    write_new(args.ledger, ledger)
    write_new(args.deliveries, [])
    write_new(args.reviews, [])
    write_new(args.output_root / "semantic_reassessments_v1.json", read(OLD / "semantic_reassessments_v1.json"))
    return {"denominator": 17, "inherited": sum(bool(row["inherited_witnesses"]) for row in cases),
            "new_first_inference_verified": 0, "ledger": str(args.ledger)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("init", "audit"))
    parser.add_argument("--output-root", type=Path, default=OUT)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--deliveries", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for name in ("ledger", "deliveries", "reviews"):
        if getattr(args, name) is None:
            setattr(args, name, args.output_root / f"{name}.json")
    if args.output is None:
        args.output = args.output_root / "evaluation.json"
    continuation.OUT = args.output_root.resolve()
    result = initialize(args) if args.stage == "init" else continuation.audit(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
