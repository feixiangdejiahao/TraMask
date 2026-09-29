"""Independent, offline ledger for the 17-trial relation-search round.

No generator/provider imports. Semantic judgments are cited human review;
execution status is re-read from named test reports, never inferred from exit 1.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from evaluate_relational_gap import digest, freeze_file, load_runs, reviewed, verify_file

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "results/relation_search_20260928/evaluation"
OLD = ROOT / "results/relational_gap_20260928"
CENSUS = ROOT / "evaluation_assets/relational_gap_v1/target_census.json"
CASES = [f"P{i}" for i in range(1, 8)] + [f"N{i:02}" for i in range(1, 11)]
DIMENSIONS = ("scenario_hit", "correct_oracle", "target_failure_match")
ORIGINS = {"new_search", "manual", "baseline_retained", "historical_replay"}


def read(path):
    return json.loads(Path(path).read_text())


def write_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def initialize(args):
    census = read(CENSUS)
    registry = read(OLD / "case_registry.json")
    baseline = read(OLD / "batch7_evaluation.json")
    if [c["case"] for c in census["cases"]] != CASES:
        raise ValueError("The denominator must contain exactly the frozen 17 trials")
    required = [CENSUS, OLD / "case_registry.json", OLD / "batch7_evaluation.json",
                OLD / "batch7_reviews_audited.json", OLD / "batch7_resumed_pipeline/runs.json",
                OLD / "batch7_execution_audit.json", ROOT / "scripts/run_relational_gap_case.py",
                ROOT / "scripts/execute_relational_gap_v7.py",
                ROOT / "scripts/evaluate_relational_gap.py", Path(__file__),
                ROOT / "vendor/replay/container_replay.py"]
    environment = {"checked_at": datetime.now(timezone.utc).isoformat(),
                   "python": subprocess.check_output([str(ROOT / ".venv/bin/python"), "--version"], text=True).strip(),
                   "docker_inspect": "not_requested"}
    image_ids = {}
    if args.inspect_images:
        images = sorted({row["image"] for row in registry})
        process = subprocess.run(["docker", "image", "inspect", *images], capture_output=True, text=True)
        environment["docker_inspect"] = "available" if process.returncode == 0 else "unavailable"
        environment["docker_error"] = process.stderr.strip()
        if process.returncode == 0:
            image_ids = {tag: image["Id"] for image in json.loads(process.stdout)
                         for tag in image.get("RepoTags", [])}
    old_cases = {row["case"]: row for row in baseline["cases"]}
    rows = []
    for target in census["cases"]:
        case = target["case"]
        record = next(row for row in registry if row["id"] == case)
        manifests = sorted((OLD / "batch7_emitted" / case).glob("group_*/manifest.json"))
        commands = [{"manifest": freeze_file(path), "phases": read(path)["phases"]}
                    for path in manifests]
        rows.append({"case": case, "trial": target["trial"], "task": target["task"],
                     "language": record["language"], "source_validation": target["source_tests"],
                     "target_gap": target["required_relation"],
                     "required_observation": target["required_observation"],
                     "evaluation_evidence": target["evidence"],
                     "special_axis": {"N05": "oracle adequacy", "N06": "historical replay after later edits"}.get(case),
                     "repository_exists": Path(record["repository"]).is_dir(),
                     "candidate_patch": freeze_file(Path(record["candidate_patch"])),
                     "image": record["image"], "recorded_image_id": record["image_id"],
                     "current_image_id": image_ids.get(record["image"]),
                     "current_image_matches": image_ids.get(record["image"]) == record["image_id"] if image_ids else None,
                     "base_commit": record["base_commit"],
                     "existing_execution_scope": "full_repository_targeted_tests",
                     "runner": "scripts/run_relational_gap_case.py", "old_execution_groups": commands,
                     "baseline": old_cases[case], "new_round_status": "pending_delivery"})
    document = {"role": "evaluator_only_do_not_send_to_generator_or_provider", "denominator": 17,
                "scope": "17 development trials, 14 unique tasks; not a blind test set",
                "environment": environment, "baseline": {
                    "tag": "relational-gap-20260928-best",
                    "tag_commit": git("rev-parse", "relational-gap-20260928-best^{commit}"),
                    "head_at_initialization": git("rev-parse", "HEAD"),
                    "target_gap_detected": baseline["counts"]["target_gap_detected"],
                    "detected_cases": [row["case"] for row in baseline["cases"] if row["target_gap_detected"]],
                    "frozen_files": [freeze_file(path) for path in required],
                    "boundary": "Hashes preserve cited evidence; this is not a transitive build freeze."},
                "cases": rows}
    write_new(args.output / "ledger.json", document)
    write_new(args.output / "deliveries.json", [])
    write_new(args.output / "reviews.json", [])
    return {"ledger": str(args.output / "ledger.json"), "denominator": 17,
            "baseline": document["baseline"]["detected_cases"], "environment": environment}


def evaluate(args):
    ledger = read(args.ledger)
    if ledger["denominator"] != 17 or [row["case"] for row in ledger["cases"]] != CASES:
        raise ValueError("Do not shrink the 17-trial denominator")
    for record in ledger["baseline"]["frozen_files"]:
        verify_file(record)
    deliveries, reviews = read(args.deliveries), read(args.reviews)
    reviewed_by_id = {(row["case"], row["id"]): row for row in reviews}
    if len(reviewed_by_id) != len(reviews):
        raise ValueError("Duplicate semantic review")
    rows, seen, cache, frozen = [], set(), {}, []
    for delivery in deliveries:
        key = delivery["case"], delivery["id"]
        if key in seen or key[0] not in CASES:
            raise ValueError("Duplicate delivery or trial outside frozen 17")
        seen.add(key)
        if delivery["origin"] not in ORIGINS:
            raise ValueError("Unknown delivery origin")
        if delivery["execution_scope"] not in {"full_repository", "component"}:
            raise ValueError("Execution scope must be explicit")
        if not delivery.get("test_files"):
            raise ValueError("A delivery requires actual test source files")
        for evidence in delivery["test_files"]:
            verify_file(evidence)
            frozen.append(evidence)
        run_file = Path(delivery["runs_json"])
        if str(run_file) not in cache:
            cache[str(run_file)], files = load_runs(run_file)
            frozen.extend(files)
        runs = [r for r in cache[str(run_file)] if (r["case"], r["candidate_id"]) == key]
        generated = [r for r in runs if r["role"] == "generated"]
        controls = [r for r in runs if r["role"] == "control"]
        source_pass = bool(controls) and all(r["passed"] for r in controls)
        observed = bool(generated) and all(bool(r["tests"]) and not r["errors"] for r in generated)
        failed = observed and any(r["failed"] for r in generated)
        semantic = {name: reviewed(reviewed_by_id.get(key, {}).get(name, {"verdict": "unknown"}))
                    for name in DIMENSIONS}
        for field in reviewed_by_id.get(key, {}).values():
            if isinstance(field, dict):
                frozen.extend(field.get("evidence", []))
        full = delivery["execution_scope"] == "full_repository"
        provenance = False
        if full and delivery.get("execution_manifest"):
            evidence = delivery["execution_manifest"]
            verify_file(evidence)
            frozen.append(evidence)
            execution = read(evidence["path"])
            target = next(row for row in ledger["cases"] if row["case"] == key[0])
            provenance = (execution.get("case") == key[0]
                          and execution.get("request", {}).get("program") == "candidate"
                          and execution.get("candidate_patch_sha256") == target["candidate_patch"]["sha256"]
                          and execution.get("image") == target["image"]
                          and execution.get("verifier_or_reference_mounted") is False)
            mounted = {item["sha256"] for item in execution.get("mounts", [])}
            provenance = provenance and all(item["sha256"] in mounted for item in delivery["test_files"])
        correct = failed and all(semantic.values()) and full and provenance
        rows.append({"case": key[0], "id": key[1], "origin": delivery["origin"],
                     "execution_scope": delivery["execution_scope"], "candidate_provenance_verified": provenance,
                     "source_control_pass": source_pass, "named_test_observed": observed,
                     "named_test_failure": failed, **semantic,
                     "correct_test_delivered": correct,
                     "controlled_target_detection": correct and source_pass,
                     "confirmed_false_alarm": failed and semantic["correct_oracle"] is False,
                     "unknown_failure": failed and any(value is None for value in semantic.values()),
                     "run_errors": sorted({error for run in runs for error in run["errors"]})})
    if set(reviewed_by_id) - seen:
        raise ValueError("Review refers to a missing delivery")
    cases = []
    for case in CASES:
        selected = [row for row in rows if row["case"] == case]
        cases.append({"case": case, "delivered_tests": len(selected),
                      "correct_test_delivered": any(row["correct_test_delivered"] for row in selected),
                      "controlled_target_detection": any(row["controlled_target_detection"] for row in selected),
                      "new_search_detection": any(row["controlled_target_detection"] and row["origin"] == "new_search" for row in selected),
                      "baseline_retained": any(row["correct_test_delivered"] and row["origin"] == "baseline_retained" for row in selected),
                      "origins": sorted({row["origin"] for row in selected})})
    return {"role": "independent_relation_search_evaluation", "denominator": 17,
            "counts": {name: sum(row[name] for row in cases) for name in
                       ("correct_test_delivered", "controlled_target_detection", "new_search_detection", "baseline_retained")},
            "old_baseline": ledger["baseline"]["detected_cases"],
            "all_17_correct_tests_delivered": all(row["correct_test_delivered"] for row in cases),
            "cases": cases, "deliveries": rows,
            "inputs": [freeze_file(p) for p in (args.ledger, args.deliveries, args.reviews)],
            "evidence_files": list({item["path"]: item for item in frozen}.values()),
            "limits": "Cited manual semantic review remains necessary. Unknown is not correct; failures alone are not bugs. Full repository denotes actual project execution, not the entire test suite. Historical replay/manual/baseline delivery does not become new-search success."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("init", "evaluate"))
    parser.add_argument("--ledger", type=Path, default=ROUND / "ledger.json")
    parser.add_argument("--deliveries", type=Path, default=ROUND / "deliveries.json")
    parser.add_argument("--reviews", type=Path, default=ROUND / "reviews.json")
    parser.add_argument("--inspect-images", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.output = args.output or (ROUND if args.stage == "init" else ROUND / "evaluation.json")
    if args.stage == "init":
        print(json.dumps(initialize(args), ensure_ascii=False))
    else:
        result = evaluate(args)
        write_new(args.output, result)
        print(json.dumps({"denominator": 17, "counts": result["counts"]}))


if __name__ == "__main__":
    main()
