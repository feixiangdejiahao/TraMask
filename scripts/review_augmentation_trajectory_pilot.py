"""Offline inventory and explicitly adjudicated summary. Never calls a model."""
from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT)]
from augmentation.pipeline import write_json
from scripts.run_augmentation_trajectory_pilot import RUN,OLD,ARMS,CASES,read,check


def inventory():
    rows=[]
    for path in sorted(RUN.glob("runs/*/*/*/result.json")):
        result=read(path)
        for i,claim in enumerate(result["final"].get("reviews",[])):
            rows.append({"key":f"{result['case']}/{result['arm']}/{result['repeat']}/{i+1}",
                         "case":result["case"],"arm":result["arm"],"repeat":result["repeat"],
                         "decision":claim.get("decision"),"claim":claim,
                         "result_path":str(path.relative_to(ROOT))})
    write_json(RUN/"evaluation/final_inventory.json",rows)
    return rows


def extraction_inventory():
    rows=[]
    for path in sorted(RUN.glob("shared_plans/*/*/stage1/parsed.json")):
        plan=read(path)
        feedback_path=path.parent.parent/"computed_feedback.json"
        if not feedback_path.exists():continue
        feedback=read(feedback_path)
        for i,model in enumerate(plan.get("models",[])):
            rows.append({"key":f"{path.parts[-4]}/{path.parts[-3]}/{i+1}","case":path.parts[-4],"repeat":int(path.parts[-3].removeprefix('repeat')),
                         "model":model,"program":feedback[i] if i<len(feedback) else {},"source":str(path.relative_to(ROOT))})
    write_json(RUN/"evaluation/extraction_inventory.json",rows)
    return rows


def summarize():
    protocol=check()
    rows=inventory();extraction=extraction_inventory()
    review_path=RUN/"evaluation/semantic_review.json"
    review=read(review_path) if review_path.exists() else {"groups":{},"assignments":{}}
    groups={**read(OLD/"evaluation/semantic_review.json")["groups"],**review.get("groups",{})}
    missing=[]
    for row in rows:
        if row["decision"]!="gap":continue
        assignment=review.get("assignments",{}).get(row["key"])
        if assignment is None:
            missing.append(row["key"]);continue
        if isinstance(assignment,str):assignment={"group":assignment}
        group=assignment["group"]
        if group not in groups:raise ValueError("unknown_review_group: "+group)
        row["semantic_group"]=group
        row["adjudication"]={**groups[group],**{k:v for k,v in assignment.items() if k!="group"}}
    results=[read(p) for p in RUN.glob("runs/*/*/*/result.json")]
    scores=[]
    for result in sorted(results,key=lambda r:(r["arm"],r["repeat"],r["case"])):
        claims=[r for r in rows if (r["case"],r["arm"],r["repeat"])==(result["case"],result["arm"],result["repeat"])]
        accepted=[r for r in claims if r.get("adjudication",{}).get("verdict")=="accepted"]
        exact=sorted({ref for r in accepted for ref in r["adjudication"].get("exact_references",[])})
        same=sorted({ref for r in accepted for ref in r["adjudication"].get("same_defect_references",[])})
        scores.append({"case":result["case"],"arm":result["arm"],"repeat":result["repeat"],
                       "correct_task":bool(accepted),"exact_references":exact,"same_defect_references":same,
                       "affirmatives":dict(Counter(r.get("adjudication",{}).get("verdict","unreviewed") for r in claims if r["decision"]=="gap")),
                       "accepted_keys":[r["key"] for r in accepted],"technical_unknown_stages":result["technical_unknown_stages"]})
    aggregates=[]
    for arm in ARMS:
        for repeat in [1,2]:
            selected=[r for r in scores if r["arm"]==arm and r["repeat"]==repeat]
            exact=sorted({ref for r in selected for ref in r["exact_references"]})
            same=sorted({ref for r in selected for ref in r["same_defect_references"]})
            counts=Counter()
            for r in selected:counts.update(r["affirmatives"])
            aggregates.append({"arm":arm,"repeat":repeat,"completed":len(selected),"correct_tasks":[r["case"] for r in selected if r["correct_task"]],
                               "exact_reference_hits":exact,"exact_reference_misses":sorted(set(protocol["fixed_reference_ids"])-set(exact)),
                               "same_defect_reference_hits":same,"same_defect_reference_misses":sorted(set(protocol["fixed_reference_ids"])-set(same)),"affirmative_claims":dict(counts)})
    manifests=[read(p) for p in RUN.glob("**/manifest.json")]
    pairs=[]
    for case in CASES:
        for repeat in [1,2]:
            paths=[RUN/"runs"/case/arm/f"repeat{repeat}"/"stage2/primary/request.json" for arm in ["C_plan","D_computed"]]
            if not all(p.exists() for p in paths):continue
            reqs=[read(p) for p in paths]
            prompts=[json.loads(r["messages"][1]["content"]) for r in reqs]
            feedback=prompts[1].pop("program_feedback")
            prompts[0].pop("program_feedback")
            envelopes=[{k:v for k,v in r.items() if k!="messages"} for r in reqs]
            equal=prompts[0]==prompts[1] and reqs[0]["messages"][0]==reqs[1]["messages"][0] and envelopes[0]==envelopes[1]
            pairs.append({"case":case,"repeat":repeat,"only_feedback_differs":equal,"computed_records":len(feedback)})
    summary={"created_at":datetime.now(timezone.utc).isoformat(),"completed":len(results),"planned":64,
             "scope":"Static Codex semantic review; no new test execution or resolution-rate measurement.","unreviewed_affirmatives":missing,
             "aggregates":aggregates,"scores":scores,"decision_counts":dict(Counter(r["decision"] for r in rows)),
             "affirmative_verdicts":dict(Counter(r.get("adjudication",{}).get("verdict","unreviewed") for r in rows if r["decision"]=="gap")),
             "rejection_reasons":dict(Counter(r["adjudication"]["reason_class"] for r in rows if r.get("adjudication",{}).get("verdict")=="rejected")),
             "actual_unique_calls":sum(r.get("external_model_calls",0) for r in manifests),
             "actual_total_tokens":sum((r.get("usage") or {}).get("total_tokens",0) for r in manifests),
             "call_statuses":dict(Counter(r["status"] for r in manifests)),"response_models":dict(Counter(r.get("response_model","unknown") for r in manifests)),
             "paired_input_audit":pairs,"extraction_models":len(extraction),
             "computed_models":sum(r["program"].get("status")=="computed_conditional_model" for r in extraction),
             "fully_literal_bound_models":sum(r["program"].get("complete_literal_bound_rows",0)>0 for r in extraction),
             "program_limits":protocol["program_semantics"]}
    extraction_review_path=RUN/"evaluation/extraction_review.json"
    extraction_review=read(extraction_review_path) if extraction_review_path.exists() else {"models":{}}
    model_reviews=extraction_review.get("models",{})
    summary["extraction_review"]={
        "unreviewed_models":[r["key"] for r in extraction if r["key"] not in model_reviews],
        "encodings":dict(Counter(model_reviews.get(r["key"],{}).get("encoding","unreviewed") for r in extraction)),
        "source_semantics":dict(Counter(model_reviews.get(r["key"],{}).get("source_semantics","unreviewed") for r in extraction)),
        "factor_counts":dict(Counter(len(r["model"].get("domains",{})) for r in extraction)),
        "binding_errors":dict(Counter(e["reason"] for r in extraction for e in r["program"].get("binding_errors",[]))),
        "rows_with_any_derived_fact":sum(bool(v.get("derived")) for r in extraction for v in r["program"].get("checked_rows",[])),
        "complete_rows":sum(r["program"].get("complete_literal_bound_rows",0) for r in extraction)}
    score_index={(r["case"],r["arm"],r["repeat"]):r for r in scores}
    comparisons=[]
    for left,right in [("A_artifacts","B_history"),("C_plan","D_computed"),("B_history","D_computed")]:
        outcomes=Counter();case_pairs=[]
        for case in CASES:
            for repeat in [1,2]:
                a=score_index.get((case,left,repeat));b=score_index.get((case,right,repeat))
                if a is None or b is None:continue
                outcome="both" if a["correct_task"] and b["correct_task"] else "left_only" if a["correct_task"] else "right_only" if b["correct_task"] else "neither"
                outcomes[outcome]+=1
                case_pairs.append({"case":case,"repeat":repeat,"outcome":outcome})
        comparisons.append({"left":left,"right":right,"outcomes":dict(outcomes),"pairs":case_pairs})
    summary["paired_outcomes"]=comparisons
    write_json(RUN/"evaluation/adjudicated_claims.json",rows)
    write_json(RUN/"evaluation/summary.json",summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("stage",choices=["inventory","show","models","summarize"])
    p.add_argument("--case");p.add_argument("--arm");p.add_argument("--repeat",type=int);p.add_argument("--decision",default="gap");p.add_argument("--compact",action="store_true");p.add_argument("--unreviewed",action="store_true")
    args=p.parse_args()
    if args.stage=="summarize":
        result=summarize()
        print(json.dumps({k:v for k,v in result.items() if k not in {"scores","paired_input_audit"}},ensure_ascii=False));return
    rows=extraction_inventory() if args.stage=="models" else inventory()
    if args.stage=="inventory":print(json.dumps({"records":len(rows),"decisions":dict(Counter(r["decision"] for r in rows))}));return
    review_path=RUN/("evaluation/extraction_review.json" if args.stage=="models" else "evaluation/semantic_review.json")
    reviewed=read(review_path).get("models" if args.stage=="models" else "assignments",{}) if review_path.exists() else {}
    for row in rows:
        if args.unreviewed and row["key"] in reviewed:continue
        if args.case and args.case!=row["case"]:continue
        if args.arm and args.arm!=row.get("arm"):continue
        if args.repeat and args.repeat!=row["repeat"]:continue
        if args.stage!="models" and args.decision!="all" and args.decision!=row["decision"]:continue
        if args.compact and args.stage=="models":
            model=row['model'];program=row['program']
            print(json.dumps({'key':row['key'],**{k:model.get(k) for k in ['relation','observation','domains','current_expr','required_expr','feasible_expr','validation_rows']},
                              'current_behavior':str(model.get('current_behavior',''))[:1100],
                              'program':{k:program.get(k) for k in ['status','binding_errors','complete_literal_bound_rows','checked_rows']}},ensure_ascii=False))
        elif args.compact and args.stage!="models":
            print(json.dumps({"key":row["key"],"decision":row["decision"],**{k:row["claim"].get(k) for k in ["combination","expected","predicted_current","reason","trajectory_basis"]}},ensure_ascii=False))
        else:print(json.dumps(row,ensure_ascii=False))


if __name__=="__main__":main()
