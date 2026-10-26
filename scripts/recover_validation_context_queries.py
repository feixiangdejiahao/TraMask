"""Repeat only stages affected by the uniformly repaired directory search."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT)]
from augmentation import context_query_recovery as recovery
from augmentation import validation_context_pilot as method
from augmentation.pipeline import write_json
from scripts import run_validation_context_pilot as original

RUN=original.RUN
OUT=RUN/"query_recovery"
read=original.read


def prepare():
    original.check()
    plans=list(RUN.glob("runs/*/*/*/stage1/parsed.json"))
    if len(plans)!=36:
        raise RuntimeError(f"Wait for all 36 original investigations; found {len(plans)}")
    if (OUT/"protocol.json").exists():
        raise RuntimeError("Recovery protocol already frozen")
    OUT.mkdir(parents=True,exist_ok=True)
    cases={c["id"]:c for c in read(RUN/"cases.json")}
    affected=[]
    for path in sorted(plans):
        cid,arm,rep=path.parts[-5:-2]
        base=read(RUN/"inputs"/cid/"base.json")
        plan=read(path)
        dirs=[q for q in plan.get("queries",[]) if recovery.directory_members(cases[cid],base,q) is not None]
        if dirs:
            affected.append({"case":cid,"arm":arm,"repeat":int(rep[6:]),"queries":dirs,
                             "stage1_sha256":method.digest(path),"path":str(path.relative_to(RUN))})
    protocol={"created_at":datetime.now(timezone.utc).isoformat(),"status":"Uniform technical-query recovery; original results remain primary frozen artifacts.",
              "change":"Search paths that are valid repository directories search the same frozen public file index under that prefix. All other query behavior, literal matching and 40-match cap remain unchanged.",
              "selection":"Every original run with such a directory query, independent of observed detection or test outcome. Reuse exact original stage1 plan; rerun stages2 and3, plus shared C/D final comparison. Unaffected runs remain unchanged.",
              "semantic_prompts_unchanged":True,"target_labels_used":False,"gold_used_online":False,
              "affected":affected,"code_sha256":{str(p.relative_to(ROOT)):method.digest(p) for p in [Path(__file__),Path(recovery.__file__)]}}
    write_json(OUT/"protocol.json",protocol)
    print(json.dumps({"affected":len(affected),"keys":[f"{x['case']}/{x['arm']}/{x['repeat']}" for x in affected]}),flush=True)


def one(entry):
    cid,arm,repeat=entry["case"],entry["arm"],entry["repeat"]
    case=next(c for c in read(RUN/"cases.json") if c["id"]==cid)
    directory=OUT/"runs"/cid/arm/f"repeat{repeat}"
    if (directory/"result.json").exists():return read(directory/"result.json")
    p=RUN/entry["path"]
    if method.digest(p)!=entry["stage1_sha256"]:raise RuntimeError("original_plan_changed")
    plan=read(p);base=read(RUN/"inputs"/cid/"base.json");public=dict(base)
    if arm!="A_source":public["development_history"]=read(RUN/"inputs"/cid/"history.json")
    framing=method.FOCUSED if arm=="C_validation" else method.OPEN
    answers=recovery.serve_queries(case,base,read(RUN/"inputs"/cid/"events.json"),plan.get("queries",[]),history_allowed=arm!="A_source")
    write_json(directory/"stage1/parsed.json",plan)
    write_json(directory/"retrieved.json",answers)
    material={"public_evidence":public,"investigation":plan,"retrieved_evidence":answers}
    draft=original.model_call(directory/"stage2",framing+method.BUILD,material)
    feedback=method.execute_response(case,draft,directory/"draft_execution")
    common={**material,"draft":draft}
    targets=[(arm,{**common,"original_patch_execution":feedback})]
    if arm=="C_validation":targets.append(("D_no_feedback",{**common,"original_patch_execution":"Withheld in this control. Perform self-review."}))
    for final_arm,payload in targets:
        out=OUT/"runs"/cid/final_arm/f"repeat{repeat}"
        if (out/"result.json").exists():continue
        final=original.model_call(out/"stage3",framing+method.BUILD+method.REVISE,payload)
        execution=method.execute_response(case,final,out/"final_execution")
        result={"case":cid,"arm":final_arm,"repeat":repeat,"decision":final.get("decision"),"final":final,
                "execution_status":execution["status"],"technical_unknown":bool(final.get("technical_unknown")),
                "shared_prefix":str(directory.relative_to(RUN)) if final_arm=="D_no_feedback" else None,
                "original_plan":entry["path"],"recovery":"directory_source_search"}
        write_json(out/"result.json",result)
        print(json.dumps({"recovery_finished":f"{cid}/{final_arm}/{repeat}","decision":final.get("decision"),"execution":execution["status"]}),flush=True)


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument("action",choices=["prepare","run"]);p.add_argument("--workers",type=int,default=4);a=p.parse_args()
    if a.action=="prepare":prepare();return
    original.check();protocol=read(OUT/"protocol.json")
    for path,h in protocol["code_sha256"].items():
        if method.digest(ROOT/path)!=h:raise RuntimeError("recovery_code_changed")
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(one,x) for x in protocol["affected"]]):f.result()


if __name__=="__main__":main()
