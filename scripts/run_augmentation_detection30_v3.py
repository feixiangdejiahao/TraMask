"""Fresh extraction and detection-only pilot on the original 30 trajectories."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT)]
from augmentation.pipeline import prepare,write_json
from augmentation.detection import run_detection
from augmentation.ranking import rank_candidates

PREVIOUS=ROOT/"experiments/relation_distinction/results/pilot30_v2_20261008_v1"
ORIGINAL=ROOT/"experiments/relation_distinction/results/pilot30_20261007_v1"
RUN=ROOT/"experiments/relation_distinction/results/pilot30_v3_detection_20261009_v1"


def read(path):
    return json.loads(Path(path).read_text())


def receipt(path):
    path=Path(path).resolve()
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    return {"path":str(path),"sha256":digest.hexdigest()}


def implementation():
    paths=sorted((ROOT/"src/augmentation").glob("*.py"))
    paths.extend([Path(__file__).resolve(),ROOT/"scripts/recover_augmentation_pilot30_v2_functions.py"])
    paths.extend(sorted((ROOT/"anchor_retrieval").glob("*.py")))
    paths.extend(sorted((ROOT/"relational_gap").glob("*.py")))
    return {str(p.relative_to(ROOT)):receipt(p)["sha256"] for p in paths}


def initialize():
    RUN.mkdir(parents=True,exist_ok=False)
    cases=read(PREVIOUS/"cases.json")
    assert len(cases)==30
    write_json(RUN/"cases.json",cases)
    protocol={"version":"pilot30-v3-detection-only.v1","created_at":datetime.now(timezone.utc).isoformat(),
              "cases":[c["id"] for c in cases],"model":"deepseek-v4-flash",
              "extraction":{"max_regions":400,"max_depth":6,"max_order":3,"analysis_mode":"joint"},
              "detector":{"max_candidates":8,"max_rounds":3,"token_budget":1000000,"max_output_tokens":16384},
              "selection":"Current v3 ranking: source conditions/effects, requirement relevance, changed-existing interaction and evidence diversity.",
              "test_generation":False,"test_execution":False,"reference_inputs_in_detection":False,
              "evaluation":{"unit":"Report distinct tasks, deduplicated concrete gap claims and fixed reference targets separately.",
                            "correct_detection":"Concrete combination missing from original validation; requirement supports the observation; static original-patch behavior fails while gold behavior satisfies it.",
                            "false_positive":"A gap claim contradicted by source/requirement/reference semantics, already-effective validation, or a non-combination issue.",
                            "unresolved":"Insufficient evidence is reported separately; it is neither a confirmed positive nor a confirmed false positive.",
                            "false_negative":"A frozen valid target has no matching correct final detection, including budget or technical omissions.",
                            "extraction":"Review whether retained/selected program evidence expresses target conditions and the behavior they jointly affect. Relevant function names alone count only as partial retrieval.",
                            "primary_reference_targets":23,"prior_confirmed_discovery":"T08-N1, reported separately and in an expanded 24-target set.",
                            "comparison_limit":"Previous v2 mixed detection with test generation and execution. This is a diagnostic comparison, not a controlled attribution of gains to one change.",
                            "no_resolution_rate_measurement":True},
              "reference_labels":receipt(ORIGINAL/"benchmark_reverse_v4/combined_targets.json"),
              "previous_review":receipt(PREVIOUS/"summary.json"),
              "implementation_sha256":implementation(),
              "input_receipts":{c["id"]:[receipt(c[k]) for k in ("candidate_patch","issue","trajectory")] for c in cases},
              "extraction_recoveries":"Reuse the previous source-only missing-function reconstruction and exact reachability cache; record every reconstruction. Normalize raw/text receipt differences before queries; no source changes."}
    write_json(RUN/"protocol.json",protocol)
    for path in protocol["implementation_sha256"]:
        destination=RUN/"implementation_snapshot"/path
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/path,destination)
    print(json.dumps({"run":str(RUN),"stage":"initialized","cases":30}),flush=True)


def check_protocol():
    protocol=read(RUN/"protocol.json")
    if protocol["implementation_sha256"]!=implementation():
        raise ValueError("Implementation changed after freeze")
    return protocol


def prepare_case(case,protocol):
    directory=RUN/"cases"/case["id"]
    done=directory/"extraction.json"
    if done.exists():
        return read(done)
    directory.mkdir(parents=True,exist_ok=True)
    for expected in protocol["input_receipts"][case["id"]]:
        if receipt(expected["path"])!=expected:
            raise ValueError("Public input changed")
    # These operational recoveries are identical in meaning to the prior run.
    from scripts.recover_augmentation_pilot30_v2_functions import restore_function_records,cached_reachable
    from augmentation import pipeline,program,search
    original_build=pipeline.build_program
    recovered=[]
    def recovered_build(*args,**kwargs):
        result=original_build(*args,**kwargs)
        recovered.extend(restore_function_records(result))
        return result
    pipeline.build_program=recovered_build
    pipeline.reachable=program.reachable=search.reachable=cached_reachable
    started=time.monotonic()
    try:
        prepared=prepare(case["repository"],Path(case["candidate_patch"]).read_text(),Path(case["issue"]).read_text(),
                         read(case["trajectory"]),**protocol["extraction"])
    finally:
        pipeline.build_program=original_build
    normalized=[]
    for path,expected in prepared["source_receipts"].items():
        source=Path(case["repository"])/path
        raw=receipt(source)["sha256"]
        if raw!=expected:
            if hashlib.sha256(source.read_text().encode()).hexdigest()!=expected:
                raise ValueError("Source text changed during extraction")
            normalized.append({"path":path,"text_sha256":expected,"raw_sha256":raw})
            prepared["source_receipts"][path]=raw
    # Save via streaming JSON to avoid another multi-GB string allocation.
    with (directory/"prepared.json").open("w") as stream:
        json.dump(prepared,stream,ensure_ascii=True,indent=2)
        stream.write("\n")
    selected,ranking=rank_candidates(prepared["candidates"],prepared["issue"],limit=protocol["detector"]["max_candidates"])
    summary={"case":case["id"],"status":"complete","seconds":time.monotonic()-started,"counts":prepared["counts"],
             "search":prepared["analysis"]["joint_search"],"families":dict(Counter(c["family"] for c in prepared["candidates"])),
             "ranking":ranking,"reconstructed_functions":recovered,"normalized_source_receipts":normalized,
             "selected":[{"id":c["id"],"family":c["family"],"condition_dimensions":c.get("behavior",{}).get("condition_dimensions"),
                          "source_paths":c["source_paths"],"test_ids":c["test_ids"]} for c in selected],
             "prepared":receipt(directory/"prepared.json")}
    write_json(directory/"extraction.json",summary)
    return summary


def detect_case(case,protocol):
    directory=RUN/"cases"/case["id"]
    done=directory/"detection.json"
    if done.exists():
        return read(done)
    prepared=read(directory/"prepared.json")
    expected=read(directory/"extraction.json")["prepared"]
    if receipt(directory/"prepared.json")!=expected:
        raise ValueError("Prepared snapshot changed")
    started=time.monotonic()
    result=run_detection(prepared,directory/"detector",provider_root=ROOT,**protocol["detector"])
    summary={"case":case["id"],"status":"complete","seconds":time.monotonic()-started,
             "external_model_calls":result["external_model_calls"],"charged_tokens":result["charged_tokens"],
             "decisions":dict(Counter(r["decision"] for r in result["results"])),
             "stop_reasons":dict(Counter(r["stop_reason"] for r in result["results"])),
             "results":receipt(directory/"detector/results.json"),"test_generation_calls":0,"test_execution_calls":0}
    write_json(done,summary)
    return summary


def record_failure(case,stage,exc):
    row={"case":case["id"],"stage":stage,"error_type":type(exc).__name__,"error":str(exc),"traceback":traceback.format_exc()}
    write_json(RUN/"cases"/case["id"]/(stage+"_failure.json"),row)
    print(json.dumps({k:row[k] for k in ("case","stage","error_type","error")}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=["init","prepare","detect","all"])
    parser.add_argument("--case",action="append")
    parser.add_argument("--prepare-workers",type=int,default=4)
    parser.add_argument("--detect-workers",type=int,default=8)
    args=parser.parse_args()
    if args.stage=="init":
        initialize();return
    protocol=check_protocol()
    cases=[c for c in read(RUN/"cases.json") if not args.case or c["id"] in args.case]
    detection_futures={}
    with ThreadPoolExecutor(max_workers=args.detect_workers) as detections:
        if args.stage in {"all","prepare"}:
            with ProcessPoolExecutor(max_workers=args.prepare_workers) as preparations:
                pending={preparations.submit(prepare_case,c,protocol):c for c in cases}
                for future in as_completed(pending):
                    case=pending[future]
                    try:
                        row=future.result()
                        print(json.dumps({"case":case["id"],"stage":"extraction_complete","seconds":round(row["seconds"],2),"candidates":row["counts"]["candidates"]}),flush=True)
                        if args.stage=="all":
                            detection_futures[detections.submit(detect_case,case,protocol)]=case
                    except Exception as exc:
                        record_failure(case,"extraction",exc)
        else:
            detection_futures={detections.submit(detect_case,c,protocol):c for c in cases}
        for future in as_completed(detection_futures):
            case=detection_futures[future]
            try:
                print(json.dumps({**future.result(),"stage":"detection_complete"}),flush=True)
            except Exception as exc:
                record_failure(case,"detection",exc)


if __name__=="__main__":
    main()
