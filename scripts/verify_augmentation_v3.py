"""Replay saved queries and source selection with no model or benchmark runs.

This is a regression audit of an already examined development set, not an
independent detection evaluation. Reference patches and benchmark failures are
not inputs to ranking, presentation or test-condition analysis.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from augmentation.agent import _execution_view
from augmentation.distinctions import behavioral_distinction, check_generated_conditions, resolve_target
from augmentation.pipeline import prepare, write_json
from augmentation.presentation import inspect, evidence_payload
from augmentation.ranking import rank_candidates


def sections(path, names):
    """Skip large relation/candidate arrays in the frozen indented snapshots."""
    result, active, buffer = {}, None, []
    with path.open() as stream:
        for line in stream:
            if active is None:
                if line.startswith('  "'):
                    key = line.split('"', 2)[1]
                    if key in names:
                        active = key
                        buffer = [line[line.index(":") + 1:]]
                        if not line.rstrip().endswith(("{", "[")):
                            result[key] = json.loads(buffer[0].rstrip().removesuffix(","))
                            active, buffer = None, []
                continue
            buffer.append(line)
            if line.rstrip() in {"  },", "  }", "  ],", "  ]"}:
                result[active] = json.loads("".join(buffer).rstrip().removesuffix(","))
                active, buffer = None, []
                if names <= result.keys():
                    return result
    return result


def candidates(path):
    active, buffer = False, []
    with path.open() as stream:
        for line in stream:
            if not active:
                active = line.rstrip() == '  "candidates": ['
                continue
            if line.rstrip() == "  ],":
                return
            if line.startswith("    {"):
                buffer = [line]
            elif buffer:
                buffer.append(line)
            if buffer and line.rstrip() in {"    },", "    }"}:
                yield json.loads("".join(buffer).rstrip().removesuffix(","))
                buffer = []


def receipt(path):
    return {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=ROOT / "experiments/relation_distinction/results/pilot30_v2_20261008_v1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fresh-case", action="append", default=[], help="Also re-extract this public subject with the current algorithm")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {"version":"augmentation-v3-regression.v1", "external_model_calls":0, "subject_test_runs":0,
               "reference_information_used_by_algorithm":False,
               "meaning":"Development-set replay of mechanics and source evidence, not gap-detection accuracy or resolution-rate improvement.",
               "implementation_sha256": {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in sorted((ROOT/"src/augmentation").glob("*.py"))}}
    grouped = {}
    for row in json.loads((args.run/"diagnosis_v1/test_queries.json").read_text()):
        grouped.setdefault(row["case"], []).append(row)
    query_results = []
    for case, queries in sorted(grouped.items()):
        print(json.dumps({"case":case,"stage":"replay_test_queries"}),flush=True)
        prepared = sections(args.run/"cases"/case/"prepared.json", {"tests", "source_receipts"})
        for query in queries:
            result = inspect(prepared, {"test_ids":[]}, query["query"])
            path = query["requested_path"].removeprefix("./").rstrip("/")
            wrong = [t["id"] for t in result["tests"] if not any(p and (p == path or p.startswith(path + "/"))
                     for p in (t["span"]["path"],t.get("written_path")))]
            assert not wrong
            query_results.append({"case":case, "query":query["query"], "status":result["status"],
                                  "matched_definitions":result["total_tests"], "returned":len(result["tests"]),
                                  "old_contains_requested_path":query["contains_requested_path"], "wrong_path_results":len(wrong)})
    write_json(args.output/"query_replay.json",query_results)
    summary["test_queries"]={"replayed":len(query_results), "status":dict(Counter(r["status"] for r in query_results)),
                             "wrong_path_results":sum(r["wrong_path_results"] for r in query_results)}
    print(json.dumps({"case":"T10","stage":"selection_and_presentation"}),flush=True)
    path=args.run/"cases/T10/prepared.json"
    pool=list(candidates(path))
    prepared=sections(path,{"issue","tests","source_files","source_receipts","repository","analysis"})
    prepared["candidates"]=pool
    selected,ranking=rank_candidates(pool,prepared["issue"],limit=8)
    write_json(args.output/"T10_selection.json",ranking)
    reference_example=json.loads((args.run/"diagnosis_v1/selection_example.json").read_text())["candidate"]
    candidate=next(c for c in pool if c["id"]==reference_example)
    payload=evidence_payload(prepared,candidate)
    write_json(args.output/"T10_behavior.json",payload)
    summary["T10_selection"]={"candidate":reference_example,"old_selected":False,
                              "new_selected":reference_example in {c["id"] for c in selected},
                              "rank":next((r["rank"] for r in ranking if r["candidate_id"]==reference_example),None),
                              "selected":len(selected), "available":len(pool),
                              "input_characters":len(json.dumps(payload,ensure_ascii=False)),
                              "source_excerpts":len(payload["source_excerpts"]),"test_code_records":len(payload["related_tests"])}
    directory=args.run/"cases/T21/agent/joint_0090c635589afbc206d2/round3/execution"
    full=json.loads((directory/"augmented/result.json").read_text())
    view=_execution_view({"augmented":{**full,"tests":full["tests"][:30]}},directory)
    write_json(args.output/"T21_execution_feedback.json",view)
    summary["T21_feedback"]={"first_status":view["augmented"]["tests"][0]["status"],
                             "total_results":view["augmented"]["test_results_total"],
                             "missing_fixture_visible":"world is not defined" in json.dumps(view)}
    directory=args.run/"cases/T14/agent/candidate_341e3036fd084d25e0a6/round3/execution"
    view=_execution_view(json.loads((directory/"result.json").read_text()),directory)
    write_json(args.output/"T14_execution_feedback.json",view)
    summary["T14_feedback"]={"missing_import_visible":"undefined: time" in json.dumps(view)}
    summary["saved_inputs"]=[receipt(args.run/"diagnosis_v1/test_queries.json"), receipt(args.run/"diagnosis_v1/selection_example.json")]
    manifest=json.loads((args.run/"cases.json").read_text())
    summary["fresh_extraction"]=[]
    for case in manifest:
        if case["id"] not in args.fresh_case:
            continue
        print(json.dumps({"case":case["id"],"stage":"fresh_source_extraction"}),flush=True)
        started=time.monotonic()
        prepared=prepare(case["repository"],Path(case["candidate_patch"]).read_text(),Path(case["issue"]).read_text(),
                         json.loads(Path(case["trajectory"]).read_text()),max_regions=80)
        selected,ranking=rank_candidates(prepared["candidates"],prepared["issue"],limit=8)
        defaults=[c for c in prepared["candidates"] if c["family"]=="default_propagation"]
        write_json(args.output/(case["id"]+"_default_behavior.json"),
                   [{"id":c["id"],"behavior":behavioral_distinction(c)} for c in defaults])
        write_json(args.output/(case["id"]+"_fresh_selection.json"),ranking)
        row={"case":case["id"],"seconds":time.monotonic()-started,"counts":prepared["counts"],
             "default_candidates":len(defaults),"reference_information_used":False,
             "source_default_transfers":sum(bool(c["behavior"].get("default_transfer")) for c in defaults),
             "inputs":[receipt(Path(case[key])) for key in ("candidate_patch","issue","trajectory")]}
        if case["id"]=="T24":
            # Regression target previously examined in the diagnosis. This ID
            # is used only to audit retention, never by extraction or ranking.
            cid="joint_2fe1cb0bd70ea99dc878"
            candidate=next((c for c in prepared["candidates"] if c["id"]==cid),None)
            row["omitted_mode_candidate_retained"]=candidate is not None
            row["omitted_mode_candidate_selected"]=cid in {c["id"] for c in selected}
            if candidate:
                response=json.loads((args.run/"cases/T24/agent"/cid/"round3/assessment.json").read_text())
                target=resolve_target(candidate)
                checked=check_generated_conditions(prepared,candidate,response,target)
                write_json(args.output/"T24_saved_test_condition_check.json",{"target":target,**checked})
                row["saved_test_condition_status"]=checked["status"]
        summary["fresh_extraction"].append(row)
    summary["verification_script"]=receipt(Path(__file__).resolve())
    write_json(args.output/"summary.json",summary)
    print(json.dumps({k:v for k,v in summary.items() if k!="implementation_sha256"},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
