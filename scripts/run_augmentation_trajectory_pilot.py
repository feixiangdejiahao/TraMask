"""Four-arm detection pilot: development history and test-bound contrasts."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from augmentation import trajectory_contrast as method
from augmentation.pipeline import write_json
from augmentation.provider import dispatch, MODEL

OLD = ROOT / "experiments/relation_distinction/results/contrast_pilot8_20261009_v2"
RUN = ROOT / "experiments/relation_distinction/results/trajectory_contrast8_20261010_v2"
ARMS = ["A_artifacts", "B_history", "C_plan", "D_computed"]
CASES = ["T10", "T11", "T13", "T17", "T20", "T23", "T24", "T28"]


def read(path):
    return json.loads(Path(path).read_text())


def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(method.__file__), Path(__file__), ROOT/"src/augmentation/provider.py", ROOT/"anchor_retrieval/syntax.py"]}


def initialize():
    RUN.mkdir(parents=True, exist_ok=False)
    cases = read(OLD / "cases.json")
    write_json(RUN / "cases.json", cases)
    for case in cases:
        base = read(OLD / "inputs" / case["id"] / "bundle.json")
        history, events = method.trajectory_index(case, base)
        facts = method.test_facts(base["validation_tests"], case["language"])
        base.pop("trajectory", None)
        base["input_limits"].pop("trajectory_char_cap", None)
        base["input_limits"]["history_policy"] = "Separate chronological event index with prioritized validation episodes."
        for test in base["validation_tests"]:
            for key in ("origin", "written_path", "step_id", "execution"):
                test.pop(key, None)
        base["literal_call_inventory"] = method.compact_facts(facts)
        base["literal_inventory_limits"] = "Only selected calls shown. Inline argument syntax; no proof of execution, aliases, embedded language semantics or expected behavior."
        directory = RUN / "inputs" / case["id"]
        for name, data in [("base.json",base),("history.json",history),("events.json",events),("facts.json",facts)]:
            write_json(directory / name, data)
        print(json.dumps({"prepared":case["id"],"base_bytes":len(json.dumps(base)),"history_bytes":len(json.dumps(history)),
                          "events":len(events),"episodes":len(history["episodes"]),"facts":len(facts),"visible_facts":len(base["literal_call_inventory"])}), flush=True)
    write_json(RUN / "protocol.json", {
        "created_at":datetime.now(timezone.utc).isoformat(),"model":MODEL,"cases":CASES,"arms":ARMS,"repeats":2,
        "scope":"Detection and extraction only. No generated tests, subject execution, or repair/resolution measurement.",
        "selection":"Same eight development cases as preceding contrast pilot, chosen before calls for mechanism comparison. Not held-out; no population claim.",
        "agent_specific_hypothesis":"The development history reveals context restrictions and feedback handling that final source/test excerpts alone do not establish. Model-chosen distinctions can guide finite program computation bound to actual test syntax.",
        "A_artifacts":"Issue, submitted source windows, same test code excerpts and literal call inventory; no event timeline or episode feedback. Test excerpts can originate from history, so this ablates event context, not all trajectory-derived artifacts.",
        "B_history":"Same artifacts plus program-retrieved chronological index, test/event associations and selected read/edit/execute episodes. Three model stages: discovery, refinement, review.",
        "C_plan":"History evidence; model proposes at most two finite behavioral models and source/history queries; then two scenario/review stages without computed feedback.",
        "D_computed":"Shares exact C stage-1 plan and source/history retrieval. Adds literal test bindings and bounded finite contrast computation. Same remaining prompts and budgets.",
        "primary_comparisons":["A/B: incremental development-event evidence","C/D: program computation given identical semantic plan and raw evidence","B/D: full method vs open history-informed discovery"],
        "logical_calls_per_run":3,"claim_cap":2,"max_tokens_per_call":65536,"temperature":0,"thinking":"enabled","reasoning_effort":"high",
        "technical_recovery":"One identical-input retry on incomplete/invalid JSON/top-level list length; no semantic retries. Prepared or ambiguous inflight records are not silently resent.",
        "technical_preflight":"v1 stopped after provider rejected planning prompts without literal JSON keyword. Added JSON to that instruction only, then restarted every arm uniformly. All preflight logs retained separately; exclude from formal results and report their known costs.",
        "source_query_policy":"At most four requests after stage 1, repository-relative public source windows and original history steps only. Identical retrieval for C/D. No model access to evaluation paths.",
        "program_semantics":"AST-derived inline positional argument values/presence/length within one test statement. Model semantic expressions and feasibility are hypotheses. Safe finite-expression interpreter enumerates up to 5 factors x 5 values; no eval or subject calls. Unknown bindings stay unknown; model-supplied validation values are not used as extracted facts.",
        "history_semantics":"All command events indexed chronologically. Detailed failure/test/edit/read episodes selected without recency preference. Lexical/temporal associations are retrieval cues, not proofs of execution or causation.",
        "fixed_reference_ids":read(OLD/"protocol.json")["fixed_reference_ids"],
        "evaluation":"Codex static review of all affirmative claims against public requirements, original/gold sources, original validation and recorded failures. Gold only in evaluation. Report fixed target hits/misses, same-defect witnesses, new valid targets, rejection reasons and unknowns separately.",
        "false_positive_controls":"T11/T23 are prior false-positive opportunities, not bug-free tasks. No task-level false-positive-rate denominator.",
        "repeat_policy":"Report both repeats, no best-of. Eight tasks repeated twice are not sixteen independent tasks.",
        "code_sha256":hashes(),
        "input_sha256":{str(p.relative_to(RUN)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((RUN/"inputs").glob("*/*.json"))},
    })


def check():
    protocol = read(RUN/"protocol.json")
    if protocol["code_sha256"] != hashes():
        raise RuntimeError("frozen_code_changed")
    for path, expected in protocol["input_sha256"].items():
        if hashlib.sha256((RUN/path).read_bytes()).hexdigest() != expected:
            raise RuntimeError("frozen_input_changed: "+path)
    return protocol


def model_call(directory, request, required):
    records = []
    for attempt in range(2):
        target = directory / ("primary" if attempt == 0 else "technical_recovery")
        if (target/"manifest.json").exists():
            record = read(target/"manifest.json")
            if record["status"] in {"prepared","dispatching"}:
                raise RuntimeError("ambiguous_inflight: "+str(target))
        else:
            record = dispatch({**request,"max_tokens":65536},target,root=ROOT,model=MODEL)
        records.append(record)
        try:
            result = read(target/"completion.txt")
            if record["status"] == "complete" and isinstance(result,dict) and isinstance(result.get(required),list) and len(result[required]) <= 2:
                write_json(directory/"parsed.json",result)
                return result,records
        except (ValueError,OSError,TypeError):
            pass
    result = {required:[],"technical_unknown":True}
    write_json(directory/"parsed.json",result)
    return result,records


def call(directory, key, system, material, required):
    result, records = model_call(directory,{"id":key,"system":method.COMMON+system,"prompt":json.dumps(material,ensure_ascii=True)},required)
    print(json.dumps({"stage_complete":key,"attempts":len(records),"technical_unknown":bool(result.get("technical_unknown"))}),flush=True)
    return result,records


def evidence(case, history=True):
    base = read(RUN/"inputs"/case/"base.json")
    if history:
        base["development_history"] = read(RUN/"inputs"/case/"history.json")
    return base


def finish(case, arm, repeat, public, stage1, initial_records, retrieval, feedback=None):
    directory=RUN/"runs"/case["id"]/arm/f"repeat{repeat}"
    if (directory/"result.json").exists(): return read(directory/"result.json")
    middle={"public_evidence":public,"first_stage":stage1,"retrieved_evidence":retrieval,"program_feedback":feedback or []}
    write_json(directory/"retrieved_evidence.json",retrieval)
    write_json(directory/"program_feedback.json",feedback or [])
    proposal, logs2 = call(directory/"stage2",f"{case['id']}/{arm}/{repeat}/2",method.SCENARIOS+
                          "\nUse the current evidence to propose at most two concrete targets. Preserve required conditions and distinguish source facts from abstraction hypotheses. Queries in this round are recorded but not served.\n",middle,"scenarios")
    final, logs3 = call(directory/"stage3",f"{case['id']}/{arm}/{repeat}/3",method.FINAL,
                       {"public_evidence":public,"retrieved_evidence":retrieval,"proposed_scenarios":proposal,"program_feedback":feedback or []},"reviews")
    records=initial_records+logs2+logs3
    result={"case":case["id"],"arm":arm,"repeat":repeat,"final":final,
            "logical_calls":sum(x.get("external_model_calls",0) for x in records),
            "logical_tokens":sum((x.get("usage") or {}).get("total_tokens",0) for x in records),
            "technical_unknown_stages":sum(bool(x.get("technical_unknown")) for x in [stage1,proposal,final]),
            "stage1_shared":arm in {"C_plan","D_computed"},
            "response_models":sorted({x.get("response_model","unknown") for x in records})}
    write_json(directory/"result.json",result)
    print(json.dumps({"finished":f"{case['id']}/{arm}/{repeat}","decisions":[x.get("decision") for x in final.get("reviews",[])]}),flush=True)
    return result


def run_direct(case,arm,repeat):
    directory=RUN/"runs"/case["id"]/arm/f"repeat{repeat}"
    if (directory/"result.json").exists(): return
    public=evidence(case["id"],history=arm!="A_artifacts")
    first,records=call(directory/"stage1",f"{case['id']}/{arm}/{repeat}/1",method.SCENARIOS,{"public_evidence":public},"scenarios")
    queries=first.get("queries",[])
    events=read(RUN/"inputs"/case["id"]/"events.json") if arm!="A_artifacts" else []
    retrieved=method.retrieve(case,queries if isinstance(queries,list) else [],events)
    return finish(case,arm,repeat,public,first,records,retrieved)


def run_pair(case,repeat):
    if all((RUN/"runs"/case["id"]/arm/f"repeat{repeat}"/"result.json").exists() for arm in ["C_plan","D_computed"]):return
    public=evidence(case["id"])
    directory=RUN/"shared_plans"/case["id"]/f"repeat{repeat}"
    first,records=call(directory/"stage1",f"{case['id']}/shared_plan/{repeat}/1",method.PLAN,{"public_evidence":public},"models")
    events=read(RUN/"inputs"/case["id"]/"events.json")
    facts=read(RUN/"inputs"/case["id"]/"facts.json")
    queries=first.get("queries",[])
    retrieved=method.retrieve(case,queries if isinstance(queries,list) else [],events)
    feedback=method.compute_contrasts(first,facts)
    write_json(directory/"computed_feedback.json",feedback)
    write_json(directory/"retrieved_evidence.json",retrieved)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(finish,case,arm,repeat,public,first,records,retrieved,feedback if arm=="D_computed" else []) for arm in ["C_plan","D_computed"]]
        for future in as_completed(futures):future.result()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=["prepare","run","status"])
    parser.add_argument("--case",action="append")
    parser.add_argument("--repeat",type=int,action="append")
    parser.add_argument("--workers",type=int,default=8)
    args=parser.parse_args()
    if args.stage=="prepare":initialize();return
    check()
    if args.stage=="status":
        results=list(RUN.glob("runs/*/*/*/result.json"))
        manifests=[read(p) for p in RUN.glob("**/manifest.json")]
        print(json.dumps({"completed":len(results),"planned":64,"unique_calls":sum(r.get("external_model_calls",0) for r in manifests),
                          "tokens":sum((r.get("usage") or {}).get("total_tokens",0) for r in manifests),
                          "inflight":sum(r["status"]=="dispatching" for r in manifests)}));return
    cases=[c for c in read(RUN/"cases.json") if not args.case or c["id"] in args.case]
    work=[(case,kind,repeat) for repeat in args.repeat or [1,2] for case in cases for kind in ["A_artifacts","B_history","pair"]]
    failed=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(run_pair,case,repeat) if kind=="pair" else pool.submit(run_direct,case,kind,repeat):(case["id"],kind,repeat) for case,kind,repeat in work}
        for future in as_completed(futures):
            try:future.result()
            except Exception as exc:
                failed.append(futures[future]);print(json.dumps({"failed":futures[future],"error_type":type(exc).__name__,"message":str(exc)[:300]}),flush=True)
    if failed:raise SystemExit(1)


if __name__=="__main__":main()
