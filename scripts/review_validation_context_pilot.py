"""Offline inventories, reviewed gold runs and summaries for the context pilot.

This file is never imported by the online generator. Semantic verdicts must be
written explicitly in evaluation/review.json; execution alone does not label bugs.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]
from augmentation.pipeline import write_json
from combination_testing.runner import run_artifact, compare_pair, freeze_artifact, load_artifact
from scripts.run_validation_context_pilot import RUN, ORIGINAL, CASES, ARMS, read, check
from augmentation import validation_context_pilot as method

RECOVERED = False
EVAL = RUN/"evaluation"


def inventory():
    rows = []
    for path in sorted(RUN.glob("runs/*/*/*/result.json")):
        if RECOVERED:
            replacement = RUN/"query_recovery"/path.relative_to(RUN)
            if replacement.exists():
                path = replacement
        result = read(path)
        key = f"{result['case']}/{result['arm']}/{result['repeat']}"
        directory = path.parent
        prefix = RUN/result["shared_prefix"] if result.get("shared_prefix") else directory
        draft = read(prefix/"stage2/parsed.json")
        draft_execution = read(prefix/"draft_execution/feedback.json")
        final_execution = read(directory/"final_execution/feedback.json")
        rows.append({"key": key, "case": result["case"], "arm": result["arm"], "repeat": result["repeat"],
                     "result_path": str(path.relative_to(ROOT)), "decision": result["decision"],
                     "final": result["final"], "draft": draft,
                     "investigation": read(prefix/"stage1/parsed.json"), "retrieved": read(prefix/"retrieved.json"),
                     "draft_execution": draft_execution, "final_execution": final_execution})
    write_json(EVAL/"inventory.json", rows)
    return rows


def gold_one(row, stage):
    directory = (ROOT/row["result_path"]).parent/f"{stage}_execution"
    feedback=read(directory/"feedback.json")
    if feedback.get("error")=="Separate artifacts are required for separate JS packages":
        return gold_separate_packages(row,directory)
    # The reference etree implementation puts its public diff API behind the
    # documented `diff` build tag. Align the command on BOTH versions, retaining
    # every model-generated source byte and the original unaligned run logs.
    if row["case"] == "T11":
        source = directory/"artifact"
        if not (source/"manifest.json").exists():
            return {"key": row["key"], "status": "candidate_not_executed"}
        manifest = load_artifact(source)
        aligned = directory/"aligned_diff_tag"
        artifact = aligned/"artifact"
        if not artifact.exists():
            files = {item["target"]: (source/item["source"]).read_text() for item in manifest["files"]}
            freeze_artifact(artifact, row["case"], files, manifest["command"].replace("go test ", "go test -tags diff ", 1),
                            manifest["report"]["format"], manifest["report"]["path"], timeout=240,
                            metadata={"evaluator_only_alignment": "Enable public diff API on both versions; model test bytes unchanged."})
        case = next(c for c in read(RUN/"cases.json") if c["id"] == row["case"])
        if not (aligned/"candidate/result.json").exists():
            run_artifact(artifact, "candidate", aligned/"candidate", registry=[case])
        directory = aligned
    result_path = directory/"comparison.json"
    if result_path.exists():
        return read(result_path)
    case = next(c for c in read(RUN/"cases.json") if c["id"] == row["case"])
    if not (directory/"candidate/result.json").exists():
        return {"key": row["key"], "status": "candidate_not_executed"}
    original = read(directory/"candidate/result.json")
    gold_path = directory/"gold/result.json"
    gold = read(gold_path) if gold_path.exists() else run_artifact(directory/"artifact", "reference", directory/"gold",
           reference_patch=ORIGINAL/"gold_comparison_v1/cases"/row["case"]/"gold.patch", registry=[case])
    result = compare_pair(original, gold)
    result.update(key=row["key"], stage=stage, evaluation_only=True)
    write_json(result_path, result)
    return result


def gold_separate_packages(row,directory):
    """Align only execution organization; retain every generated test byte."""
    path=directory/"comparison.json"
    if path.exists():return read(path)
    case=next(c for c in read(RUN/"cases.json") if c["id"]==row["case"])
    repository=Path(case["repository"])
    groups={}
    for test in row["final"]["tests"]:
        parent=(repository/test["path"]).parent
        while parent!=repository and not (parent/"package.json").is_file():
            parent=parent.parent
        groups.setdefault(str(parent.relative_to(repository)),[]).append(test)
    packages=[];counts=Counter()
    for i,(package,tests) in enumerate(sorted(groups.items())):
        out=directory/"separate_packages"/str(i)
        write_json(out/"receipt.json",{"package":package,"evaluator_only":True,
                   "change":"Split independent test files by their existing JS package. No model source changes or feedback.",
                   "original_tests":tests})
        if not (out/"candidate/result.json").exists():
            method.execute_response(case,{**row["final"],"tests":tests},out)
        if not (out/"candidate/result.json").exists():
            raise RuntimeError("separate_package_execution_failed:"+str(out))
        original=read(out/"candidate/result.json")
        golden=read(out/"gold/result.json") if (out/"gold/result.json").exists() else run_artifact(
            out/"artifact","reference",out/"gold",reference_patch=ORIGINAL/"gold_comparison_v1/cases"/row["case"]/"gold.patch",registry=[case])
        pair=compare_pair(original,golden)
        write_json(out/"comparison.json",pair)
        counts.update(pair["counts"])
        packages.append({"package":package,"comparison":str((out/"comparison.json").relative_to(RUN))})
    result={"key":row["key"],"stage":"final","evaluation_only":True,"alignment":"separate_js_packages",
            "counts":dict(counts),"packages":packages}
    write_json(path,result)
    return result


def gold(workers):
    rows = inventory()
    approvals = read(EVAL/"portability.json")["approved_final_keys"]
    selected = []
    for row in rows:
        done = (ROOT/row["result_path"]).parent/"final_execution"
        if row["case"] == "T11":
            done = done/"aligned_diff_tag"
        if row["key"] in approvals and not (done/"comparison.json").exists():
            selected.append(row)
    print(json.dumps({"new_offline_gold_pairs": len(selected)}), flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for f in as_completed([pool.submit(gold_one, r, "final") for r in selected]):
            result = f.result()
            print(json.dumps({k: result[k] for k in ("key", "status", "counts") if k in result}), flush=True)


def summarize():
    protocol = check()
    rows = inventory()
    review_path = EVAL/"review.json"
    review = read(review_path) if review_path.exists() else {"rows": {}}
    missing = []
    scores = []
    for row in rows:
        label = review["rows"].get(row["key"])
        if label is None:
            missing.append(row["key"])
            label = {}
        scores.append({"key": row["key"], "case": row["case"], "arm": row["arm"], "repeat": row["repeat"],
                       "decision": row["decision"], "review": label,
                       "execution": {"draft": row["draft_execution"]["status"], "final": row["final_execution"]["status"]}})
    aggregates = []
    for arm in ARMS:
        for repeat in [1, 2]:
            chosen = [s for s in scores if s["arm"] == arm and s["repeat"] == repeat]
            hits = sorted({x for s in chosen for x in s["review"].get("fixed_hits", [])})
            same = sorted({x for s in chosen for x in s["review"].get("same_defect_hits", [])})
            detected = [s["case"] for s in chosen if s["review"].get("detection") == "repair_relevant_gap"]
            generated = [s["case"] for s in chosen if s["review"].get("generation") == "correct_repair_relevant_test"]
            dynamic = [s["case"] for s in chosen if s["review"].get("generation") == "correct_repair_relevant_test" and s["review"].get("generation_evidence") == "dynamic_pair"]
            fp = [s["case"] for s in chosen if s["review"].get("false_positive") is True]
            unknown = [s["case"] for s in chosen if s["review"].get("detection") == "unknown"]
            aggregates.append({"arm": arm, "repeat": repeat, "completed": len(chosen), "correct_detection_tasks": detected,
                               "correct_generated_tasks": generated, "dynamic_pair_tasks": dynamic,
                               "false_positive_tasks": fp, "unknown_tasks": unknown,
                               "fixed_hits": hits, "fixed_misses": sorted(set(protocol["fixed_reference_ids"])-set(hits)),
                               "same_defect_hits": same})
    logs = [read(p) for p in RUN.glob("runs/**/manifest.json") if "model" in read(p)]
    recovery_logs = [read(p) for p in RUN.glob("query_recovery/runs/**/manifest.json") if "model" in read(p)] if RECOVERED else []
    pairs = []
    for cid in CASES:
        for repeat in [1, 2]:
            paths = [RUN/"runs"/cid/arm/f"repeat{repeat}"/"stage3/primary/request.json" for arm in ["C_validation", "D_no_feedback"]]
            if RECOVERED:
                paths = [(RUN/"query_recovery"/p.relative_to(RUN)) if (RUN/"query_recovery"/p.relative_to(RUN)).exists() else p for p in paths]
            if not all(p.exists() for p in paths):
                continue
            req = [read(p) for p in paths]
            body = [json.loads(r["messages"][1]["content"]) for r in req]
            for b in body:
                b.pop("original_patch_execution")
            equal = body[0] == body[1] and req[0]["messages"][0] == req[1]["messages"][0]
            equal = equal and {k:v for k,v in req[0].items() if k != "messages"} == {k:v for k,v in req[1].items() if k != "messages"}
            pairs.append({"case": cid, "repeat": repeat, "only_runtime_feedback_differs": equal})
    query_rows=[]
    request_checks=[]
    roots=[RUN/"runs"]+([RUN/"query_recovery/runs"] if RECOVERED else [])
    for root in roots:
        for path in sorted(root.glob("*/*/*/retrieved.json")):
            query_rows.extend({"run":str(path.parent.relative_to(RUN)),"kind":q["query"].get("kind"),
                               "error":q.get("error"),"query":q["query"]} for q in read(path))
        for path in sorted(root.glob("*/*/*/stage*/*/request.json")):
            cid,arm=path.relative_to(root).parts[:2]
            payload=json.loads(read(path)["messages"][1]["content"])
            expected=read(RUN/"inputs"/cid/"base.json")
            if arm!="A_source":
                expected["development_history"]=read(RUN/"inputs"/cid/"history.json")
            request_checks.append({"request":str(path.relative_to(RUN)),
                                   "public_input_matches_frozen_material":payload.get("public_evidence")==expected,
                                   "only_declared_material_keys":set(payload)<= {"public_evidence","investigation","retrieved_evidence","draft","original_patch_execution"},
                                   "no_gold_execution_feedback":not isinstance(payload.get("original_patch_execution"),dict) or payload["original_patch_execution"].get("gold_used") is False})
    source_mismatches=[]
    checked_sources=0
    from augmentation.validation_context_pilot import digest
    for case in read(RUN/"cases.json"):
        for path,h in read(RUN/"inputs"/case["id"]/"source_receipts.json").items():
            checked_sources+=1
            if digest(Path(case["repository"])/path)!=h:
                source_mismatches.append({"case":case["id"],"path":path})
    recorded_query_count=len(query_rows)
    if RECOVERED:
        replaced={q["run"].removeprefix("query_recovery/") for q in query_rows if q["run"].startswith("query_recovery/")}
        query_rows=[q for q in query_rows if q["run"].startswith("query_recovery/") or q["run"] not in replaced]
    audit={"query_kinds":dict(Counter(q["kind"] for q in query_rows)),
           "query_errors":dict(Counter(q["error"] for q in query_rows if q["error"])),
           "queries":query_rows,"query_scope":"Effective query results; recovered results replace their original query results only in the overlay.",
           "all_recorded_query_count":recorded_query_count,"request_checks":request_checks,
           "requests_checked":len(request_checks),"all_request_checks_pass":all(all(v for k,v in q.items() if k!="request") for q in request_checks),
           "source_files_checked":checked_sources,"source_mismatches":source_mismatches,
           "paired_input_audit":pairs}
    write_json(EVAL/"audit.json",audit)
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "completed": len(rows), "planned": 48,
               "dataset": "directory_query_recovery_overlay" if RECOVERED else "original_frozen_pilot",
               "reviewer": "Codex source/trajectory/test semantic review; not independent human blind annotation.",
               "unreviewed": missing, "aggregates": aggregates, "scores": scores,
               "physical_model_calls": sum(l.get("external_model_calls", 0) for l in logs),
               "actual_total_tokens": sum((l.get("usage") or {}).get("total_tokens", 0) for l in logs),
               "actual_prompt_tokens": sum((l.get("usage") or {}).get("prompt_tokens", 0) for l in logs),
               "actual_completion_tokens": sum((l.get("usage") or {}).get("completion_tokens", 0) for l in logs),
               "additional_recovery_calls": sum(l.get("external_model_calls", 0) for l in recovery_logs),
               "additional_recovery_tokens": sum((l.get("usage") or {}).get("total_tokens", 0) for l in recovery_logs),
               "call_statuses": dict(Counter(l["status"] for l in logs)),
               "response_models": dict(Counter(l.get("response_model", "unknown") for l in logs)),
               "paired_input_audit": pairs,
               "audit":{k:audit[k] for k in ("query_kinds","query_errors","requests_checked","all_request_checks_pass","source_files_checked","source_mismatches")},
               "limits": "Development tasks; two repeats are not independent tasks. No patch repair or resolution-rate evaluation. False positives are reviewed reports, not a population false-positive rate. Static and dynamically validated generation evidence remain separate."}
    write_json(EVAL/"summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("completed", "unreviewed", "aggregates", "physical_model_calls", "actual_total_tokens")}, ensure_ascii=False, indent=2))


def main():
    global RECOVERED, EVAL
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("action", choices=["inventory", "gold", "summary"])
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--recovered", action="store_true")
    a = p.parse_args()
    if a.recovered:
        RECOVERED = True
        EVAL = RUN/"query_recovery/evaluation"
    if a.action == "inventory":
        print(json.dumps({"rows": len(inventory())}))
    elif a.action == "gold":
        gold(a.workers)
    else:
        summarize()


if __name__ == "__main__":
    main()
