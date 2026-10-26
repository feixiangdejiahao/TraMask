"""Aggregate explicitly adjudicated claims; never infer a judgment from a keyword."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts.run_augmentation_contrast_pilot import RUN, CASES, ARMS, check, read
from scripts.review_augmentation_contrast_pilot import inventory
from augmentation.pipeline import write_json


def summarize(allow_incomplete=False):
    protocol = check()
    arms = ARMS + ["F_plan_only"]
    review = read(RUN / "evaluation/semantic_review.json")
    rows = inventory()
    results = [read(p) for p in sorted(RUN.glob("runs/*/*/*/result.json"))]
    unreviewed = [r["key"] for r in rows if r["decision"] == "gap" and r["key"] not in review["assignments"]]
    if not allow_incomplete and (len(results) != 96 or unreviewed):
        raise ValueError({"completed": len(results), "unreviewed": unreviewed})
    by_key = {r["key"]: r for r in rows}
    for key, group in review["assignments"].items():
        if key not in by_key or by_key[key]["decision"] != "gap":
            raise ValueError("assignment_without_affirmative_claim: " + key)
        if group not in review["groups"]:
            raise ValueError("missing_semantic_group: " + group)
    details = []
    for row in rows:
        item = dict(row)
        group = review["assignments"].get(row["key"])
        if group:
            item.update(semantic_group=group, adjudication=review["groups"][group])
        details.append(item)
    scores = []
    for result in results:
        prefix = f"{result['case']}/{result['arm']}/{result['repeat']}/"
        claims = [r for r in details if r["key"].startswith(prefix)]
        accepted = [r for r in claims if r.get("adjudication", {}).get("verdict") == "accepted"]
        exact = sorted({t for r in accepted for t in r["adjudication"]["exact_references"]})
        expanded = sorted({t for r in accepted for t in r["adjudication"]["same_defect_references"]})
        count = Counter(r.get("adjudication", {}).get("verdict", "unreviewed") for r in claims if r["decision"] == "gap")
        scores.append({"case": result["case"], "arm": result["arm"], "repeat": result["repeat"],
                       "correct_task": bool(accepted), "exact_references": exact,
                       "same_defect_references": expanded, "affirmative_claims": dict(count),
                       "accepted_keys": [r["key"] for r in accepted],
                       "accepted_groups": sorted({r["semantic_group"] for r in accepted}),
                       "model_decisions": dict(Counter(r["decision"] for r in claims)),
                       "technical_unknown_stages": result["technical_unknown_stages"]})
    aggregates = []
    for arm in arms:
        for repeat in [1, 2]:
            selected = [s for s in scores if s["arm"] == arm and s["repeat"] == repeat]
            exact = sorted({t for s in selected for t in s["exact_references"]})
            expanded = sorted({t for s in selected for t in s["same_defect_references"]})
            aggregates.append({"arm": arm, "repeat": repeat, "completed": len(selected),
                "correct_tasks": [s["case"] for s in selected if s["correct_task"]],
                "exact_reference_hits": exact,
                "exact_reference_misses": sorted(set(protocol["fixed_reference_ids"]) - set(exact)),
                "same_defect_reference_hits": expanded,
                "same_defect_reference_misses": sorted(set(protocol["fixed_reference_ids"]) - set(expanded)),
                "affirmative_claims": dict(sum((Counter(s["affirmative_claims"]) for s in selected), Counter()))})
    manifests = [(p, read(p)) for p in sorted(RUN.glob("runs/*/*/*/stage*/*/manifest.json"))]
    cost = {}
    for arm in arms:
        chosen = [(p, m) for p, m in manifests if p.parts[-5] == arm]
        shared = [(p, m) for p, m in manifests if p.parts[-5] == "E_semantic" and p.parts[-3] == "stage1"] if arm == "F_plan_only" else []
        count_cost = lambda pairs: {"calls": sum(m.get("external_model_calls", 0) for _, m in pairs),
            "tokens": sum((m.get("usage") or {}).get("total_tokens", 0) for _, m in pairs),
            "prompt_tokens": sum((m.get("usage") or {}).get("prompt_tokens", 0) for _, m in pairs),
            "completion_tokens": sum((m.get("usage") or {}).get("completion_tokens", 0) for _, m in pairs),
            "reasoning_tokens": sum((m.get("usage") or {}).get("completion_tokens_details", {}).get("reasoning_tokens", 0) for _, m in pairs),
            "provider_seconds_sum": sum(m.get("seconds", 0) for _, m in pairs)}
        cost[arm] = {"actual": count_cost(chosen), "logical_including_shared_plan": count_cost(chosen + shared)}
    raw_audit = []
    for path, manifest in manifests:
        request = read(path.with_name("request.json"))
        content = json.loads(request["messages"][1]["content"])
        case = path.parts[-6]
        bundle = read(RUN / "inputs" / case / "bundle.json")
        same = content["public_evidence"] == bundle
        if not same:
            raise ValueError("raw_material_mismatch: " + str(path))
        forbidden = [s for s in ["source_pairs/", "gold.patch", "benchmark_test.patch", "fixed_references.json"] if s in request["messages"][1]["content"]]
        if forbidden:
            raise ValueError("evaluation_path_in_request: " + str(path))
        raw_audit.append({"request": str(path.with_name("request.json").relative_to(ROOT)), "same_raw_bundle": same,
                          "evaluation_path_strings_found": forbidden})
    paired = []
    for case in CASES:
        for repeat in [1, 2]:
            base = RUN / "runs" / case
            ep = base / "E_semantic" / f"repeat{repeat}" / "stage2/primary/request.json"
            fp = base / "F_plan_only" / f"repeat{repeat}" / "stage2/primary/request.json"
            if not ep.exists() or not fp.exists():
                continue
            er, fr = read(ep), read(fp)
            ec, fc = json.loads(er["messages"][1]["content"]), json.loads(fr["messages"][1]["content"])
            feedback = ec.pop("program_feedback")
            empty = fc.pop("program_feedback")
            equal_payload = ec == fc
            er["messages"][1]["content"] = "<paired_payload>"
            fr["messages"][1]["content"] = "<paired_payload>"
            if not equal_payload or er != fr or empty != []:
                raise ValueError(f"paired_ablation_mismatch: {case}/{repeat}")
            es = next((s for s in scores if s["case"] == case and s["repeat"] == repeat and s["arm"] == "E_semantic"), None)
            fs = next((s for s in scores if s["case"] == case and s["repeat"] == repeat and s["arm"] == "F_plan_only"), None)
            paired.append({"case": case, "repeat": repeat, "only_program_feedback_differs": True,
                           "program_feedback_records": len(feedback), "E": es, "F": fs})
    ablation = read(RUN / "program_feedback_ablation_protocol.json")
    ablation_hash = hashlib.sha256((ROOT / "scripts/run_augmentation_contrast_ablation.py").read_bytes()).hexdigest()
    if ablation_hash != ablation["code_sha256"]:
        raise ValueError("ablation_code_changed")
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "completed_runs": len(results), "planned_runs": 96,
        "scope": "Detection only; static Codex adjudication, not independent human review or dynamic test execution.",
        "cases": CASES, "reference_denominator_per_repeat": 8, "case_denominator_per_repeat": 8,
        "unreviewed_affirmatives": unreviewed, "aggregates": aggregates, "scores": scores,
        "paired_E_F": paired, "cost": cost,
        "actual_unique_calls": sum(m.get("external_model_calls", 0) for _, m in manifests),
        "actual_total_tokens": sum((m.get("usage") or {}).get("total_tokens", 0) for _, m in manifests),
        "call_statuses": dict(Counter(m["status"] for _, m in manifests)),
        "response_models": dict(Counter(m.get("response_model", "unknown") for _, m in manifests)),
        "technical_recovery_calls": sum(p.parent.name == "technical_recovery" for p, _ in manifests),
        "audit": {"frozen_code_and_bundles_unchanged": True, "paired_ablation_code_unchanged": True,
                  "requests_checked": len(raw_audit), "paired_requests_checked": len(paired)},
        "rejection_reasons": dict(Counter(r["adjudication"]["reason_class"] for r in details if r.get("adjudication", {}).get("verdict") == "rejected"))}
    write_json(RUN / "evaluation/adjudicated_claims.json", details)
    write_json(RUN / "evaluation/input_audit.json", raw_audit)
    write_json(RUN / "evaluation/summary.json", summary)
    print(json.dumps({"completed": len(results), "unreviewed": unreviewed, "calls": summary["actual_unique_calls"], "tokens": summary["actual_total_tokens"]}))
    for a in aggregates:
        print(a["arm"], a["repeat"], "done", a["completed"], "correct", len(a["correct_tasks"]),
              "fixed", len(a["exact_reference_hits"]), "same_defect", len(a["same_defect_reference_hits"]), a["affirmative_claims"])
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-incomplete", action="store_true")
    summarize(parser.parse_args().allow_incomplete)
