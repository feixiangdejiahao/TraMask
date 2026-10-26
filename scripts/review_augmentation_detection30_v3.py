"""Offline inventory for manual semantic review; never calls the provider."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT)]
from augmentation.pipeline import write_json
from augmentation.ranking import focus
from scripts.verify_augmentation_v3 import candidates

RUN=ROOT/"experiments/relation_distinction/results/pilot30_v3_detection_20261009_v1"


def inventory():
    rows=[]
    for path in sorted(RUN.glob("cases/*/detector/*/result.json")):
        result=json.loads(path.read_text())
        rows.append({"id":path.parts[-4]+"/"+result["candidate_id"],"case":path.parts[-4],
                     "candidate":result["candidate_id"],"decision":result["decision"],
                     "assessment":result.get("assessment"),"result":str(path),"rounds":result["rounds"],"stop_reason":result["stop_reason"]})
    write_json(RUN/"evaluation/inventory.json",rows)
    return rows


def pack(case):
    directory=RUN/"cases"/case
    chosen={r["candidate_id"] for r in json.loads((directory/"extraction.json").read_text())["ranking"]}
    rows=[]
    for c in candidates(directory/"prepared.json"):
        behavior=c.get("behavior",{})
        rows.append({"id":c["id"],"selected":c["id"] in chosen,"family":c["family"],
                     "conditions":[{k:d[k] for k in ("kind","expression","span","domain")} for d in behavior.get("conditions",[])],
                     "focus":[{"id":n["id"],"code":n["code"],"span":n["span"],"changed":n["changed"]} for n in focus(c)],
                     "functions":c["function_ids"],"resources":c.get("resource_paths",[]),
                     "default_transfer":behavior.get("default_transfer"),
                     "relations":dict(Counter(e["kind"] for e in c["relations"])),
                     "tests":len(c["test_ids"]),"scope_rows":len(c.get("test_scope",{}).get("rows",[])),
                     "known_conditions":sum(v.get("known",False) for r in c.get("test_scope",{}).get("rows",[]) for v in r["conditions"].values())})
    write_json(RUN/"evaluation/extraction"/(case+".json"),rows)
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=["inventory","show","pack"])
    parser.add_argument("--case",action="append")
    parser.add_argument("--decision",action="append")
    args=parser.parse_args()
    if args.stage=="pack":
        for case in args.case or []:
            print(json.dumps({"case":case,"candidates":len(pack(case))}))
        return
    rows=inventory()
    if args.stage=="inventory":
        print(json.dumps({"completed_candidates":len(rows),"decisions":dict(Counter(r["decision"] for r in rows)),
                          "completed_tasks":len(list(RUN.glob('cases/*/detection.json')))},ensure_ascii=False))
    else:
        for r in rows:
            if args.case and r["case"] not in args.case or args.decision and r["decision"] not in args.decision:
                continue
            print(json.dumps(r,ensure_ascii=False))


if __name__=="__main__":
    main()
