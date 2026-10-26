"""Frozen five-arm, two-repeat detection pilot. No test generation or execution."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from augmentation import contrast_pilot as method
from augmentation.pipeline import write_json
from augmentation.provider import dispatch, MODEL
from scripts.verify_augmentation_v3 import sections, candidates

OLD = ROOT / "experiments/relation_distinction/results/pilot30_v3_detection_20261009_v1"
RUN = ROOT / "experiments/relation_distinction/results/contrast_pilot8_20261009_v2"
CASES = ["T10", "T11", "T13", "T17", "T20", "T23", "T24", "T28"]
ARMS = ["A_direct", "B_split", "C_open", "D_static", "E_semantic"]


def read(path):
    return json.loads(Path(path).read_text())


def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(method.__file__), Path(__file__), ROOT / "src/augmentation/provider.py"]}


def initialize():
    RUN.mkdir(parents=True, exist_ok=False)
    cases = [c for c in read(OLD / "cases.json") if c["id"] in CASES]
    write_json(RUN / "cases.json", cases)
    for case in cases:
        directory = RUN / "inputs" / case["id"]
        previous = OLD / "cases" / case["id"]
        prepared = sections(previous / "prepared.json", {"tests"})
        ranking = read(previous / "extraction.json")["ranking"]
        ids = {r["candidate_id"] for r in ranking[:8]}
        selected = [c for c in candidates(previous / "prepared.json") if c["id"] in ids]
        bundle, sources, analysis = method.build_bundle(case, prepared, selected)
        write_json(directory / "bundle.json", bundle)
        write_json(directory / "analysis.json", analysis)
        write_json(directory / "source_snapshot.json", [{"path": s.path, "code": s.code, "language": s.language} for s in sources])
        print(json.dumps({"case": case["id"], "bytes": len(json.dumps(bundle)), "tests": len(bundle["validation_tests"]),
                          "expressions": len(analysis["expressions"]), "static_selected": len(analysis["automatic"])}), flush=True)
    write_json(RUN / "protocol.json", {
        "created_at": datetime.now(timezone.utc).isoformat(), "model": MODEL, "cases": CASES, "arms": ARMS,
        "selection": "Six previously diagnosed cases plus two previously false-positive cases. Development diagnostic, not held-out.",
        "repeats": 2, "calls_per_run": 3, "max_tokens_per_call": 65536,
        "technical_recovery": "One identical-input retry at max_tokens=65536 for non-complete or invalid-JSON output; all arms/stages, no semantic retry.",
        "technical_preflight": "contrast_pilot8_20261009_v1 was stopped for output truncation and dropped modified source blocks. Preserved separately; not an algorithm comparison. Main uses all modified-line windows and a uniformly larger output budget.",
        "claim_cap": 2, "temperature": 0, "thinking": "enabled", "reasoning_effort": "high",
        "raw_materials": "Identical bundle per case in every arm and stage; no adaptive source retrieval, generated tests, execution, gold or reference labels.",
        "A_direct": "Old top-eight annotations; judge directly twice, then common final review.",
        "B_split": "Same old annotations; propose scenarios, refine, then common final review.",
        "C_open": "Neutral public evidence; propose scenarios, refine, then common final review.",
        "D_static": "Same as C plus automatic local Boolean influence contrasts.",
        "E_semantic": "LLM first maps public requirements to source observations; program resolves locations and computes local contrasts; LLM proposes scenarios, then common final review.",
        "primary_comparisons": ["A/B: discovery before classification", "B/C: effect of old candidate guidance", "C/D: automatic program contrast guidance", "C/E and D/E: semantic guidance inside analysis"],
        "evaluation": "Static Codex review of every final affirmative claim against original/gold source, public requirement, original validation and reference failure. Not independent human or dynamic verification.",
        "fixed_reference_ids": ["T10-R1", "T13-R1", "T17-R1", "T20-G1", "T20-G2", "T24-R1", "T24-G2", "T28-R1"],
        "same_defect_shorter_witness": "Report separately: must retain same erroneous influence/dependency and public requirement. T28 immediate invalidation-state witness is eligible for same-defect, not exact old mount scenario.",
        "false_positive_controls": "T11 and T23 are previous false-positive opportunities, not proven bug-free tasks. No task-level false-positive rate.",
        "false_negative": "Each fixed reference target not detected under its specified scenario; separately report same-defect shorter witness.",
        "repeat_interpretation": "Two fresh calls at temperature zero can vary at provider. No best-of aggregation as primary metric.",
        "hypothesis": "Original validation can correlate conditions and hide independent influences on contract-relevant observations. Test explicit influence contrasts and semantic guidance, not a larger task-specific mutation catalog.",
        "code_sha256": hashes(),
        "bundle_sha256": {c["id"]: hashlib.sha256((RUN / "inputs" / c["id"] / "bundle.json").read_bytes()).hexdigest() for c in cases},
        "program_limits": "Local 2-6 operand pure Boolean truth abstraction; literal consistency checks; lexical occurrence/slice links not alias, path, heap, temporal or input binding proofs. No claim of novel MC/DC.",
    })


def check():
    protocol = read(RUN / "protocol.json")
    if hashes() != protocol["code_sha256"]:
        raise RuntimeError("frozen_implementation_changed")
    for case, expected in protocol["bundle_sha256"].items():
        if hashlib.sha256((RUN / "inputs" / case / "bundle.json").read_bytes()).hexdigest() != expected:
            raise RuntimeError("frozen_input_changed")
    return protocol


def model_call(directory, request, required):
    records = []
    for attempt in range(2):
        target = directory / ("primary" if attempt == 0 else "technical_recovery")
        if (target / "manifest.json").exists():
            record = read(target / "manifest.json")
            if record["status"] in {"prepared", "dispatching"}:
                raise RuntimeError("ambiguous_inflight_call: " + str(target))
        else:
            req = {**request, "max_tokens": 65536}
            record = dispatch(req, target, root=ROOT, model=MODEL)
        records.append(record)
        try:
            value = read(target / "completion.txt")
            valid = isinstance(value, dict) and isinstance(value.get(required), list)
            if required == "focuses":
                valid = valid and len(value[required]) <= 4
            else:
                valid = valid and len(value[required]) <= 2
            if record["status"] == "complete" and valid:
                write_json(directory / "parsed.json", value)
                return value, records
        except (OSError, ValueError, TypeError):
            pass
    result = {required: [], "technical_unknown": True}
    write_json(directory / "parsed.json", result)
    return result, records


def run_one(case, arm, repeat):
    directory = RUN / "runs" / case / arm / f"repeat{repeat}"
    if (directory / "result.json").exists():
        return read(directory / "result.json")
    bundle = read(RUN / "inputs" / case / "bundle.json")
    analysis = read(RUN / "inputs" / case / "analysis.json")
    annotation = analysis["legacy"] if arm in {"A_direct", "B_split"} else analysis["automatic"] if arm == "D_static" else []
    first_kind = "focuses" if arm == "E_semantic" else "reviews" if arm == "A_direct" else "scenarios"
    stage1 = method.PLAN_FORMAT if arm == "E_semantic" else method.FINAL_FORMAT if arm == "A_direct" else method.SCENARIO_FORMAT
    if arm == "A_direct":
        stage1 = stage1.replace("Independently review the proposed scenarios against the supplied raw evidence.", "Directly decide whether the supplied candidates reveal a combination gap.")
        stage1 = stage1.replace("You may refine a proposed scenario but do not introduce a new unrelated one at this stage.", "You may correct the supplied candidate or report another supported combination.")
    common = {"public_evidence": bundle, "analysis_annotation": annotation}
    records = []
    previous, logs = model_call(directory / "stage1", {"id": f"{case}/{arm}/{repeat}/1", "system": method.COMMON + stage1,
                              "prompt": json.dumps(common, ensure_ascii=True)}, first_kind)
    records.extend(logs)
    print(json.dumps({"case": case, "arm": arm, "repeat": repeat, "stage": 1, "calls": len(logs)}), flush=True)
    if arm == "E_semantic":
        sources = [method.Source(**s) for s in read(RUN / "inputs" / case / "source_snapshot.json")]
        grounded = method.guided_analysis(previous, analysis["expressions"], sources, bundle)
        write_json(directory / "program_feedback.json", grounded)
        middle = {"public_evidence": bundle, "semantic_analysis_plan": previous, "program_feedback": grounded}
    else:
        middle = {**common, "previous_analysis": previous}
    system2 = method.COMMON + (method.FINAL_FORMAT if arm == "A_direct" else method.SCENARIO_FORMAT)
    system2 += "\nRe-examine the inputs and operations. Keep only your two most promising concrete scenarios; you may revise your earlier choices.\n"
    second_kind = "reviews" if arm == "A_direct" else "scenarios"
    proposed, logs = model_call(directory / "stage2", {"id": f"{case}/{arm}/{repeat}/2", "system": system2,
                              "prompt": json.dumps(middle, ensure_ascii=True)}, second_kind)
    records.extend(logs)
    print(json.dumps({"case": case, "arm": arm, "repeat": repeat, "stage": 2, "calls": len(logs)}), flush=True)
    final, logs = model_call(directory / "stage3", {"id": f"{case}/{arm}/{repeat}/3", "system": method.COMMON + method.FINAL_FORMAT,
                              "prompt": json.dumps({"public_evidence": bundle, "proposed_scenarios": proposed}, ensure_ascii=True)}, "reviews")
    records.extend(logs)
    tokens = sum((r.get("usage") or {}).get("total_tokens", 0) for r in records)
    result = {"case": case, "arm": arm, "repeat": repeat, "final": final,
              "calls": sum(r.get("external_model_calls", 0) for r in records), "tokens": tokens,
              "technical_unknown_stages": sum(bool(r.get("technical_unknown")) for r in [previous, proposed, final]),
              "response_models": sorted({r.get("response_model", "unknown") for r in records}),
              "raw_material_sha256": hashlib.sha256((RUN / "inputs" / case / "bundle.json").read_bytes()).hexdigest()}
    write_json(directory / "result.json", result)
    print(json.dumps({"finished": f"{case}/{arm}/{repeat}", "calls": result["calls"], "tokens": tokens,
                      "decisions": [r.get("decision") for r in final.get("reviews", [])]}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "run", "status"])
    parser.add_argument("--case", action="append")
    parser.add_argument("--arm", action="append")
    parser.add_argument("--repeat", type=int, action="append")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.stage == "prepare":
        initialize()
        return
    check()
    if args.stage == "status":
        results = [read(p) for p in RUN.glob("runs/*/*/*/result.json")]
        manifests = [read(p) for p in RUN.glob("runs/*/*/*/stage*/*/manifest.json")]
        print(json.dumps({"completed": len(results), "planned": len(CASES) * len(ARMS) * 2,
                          "calls": sum(r.get("external_model_calls", 0) for r in manifests),
                          "tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in manifests),
                          "inflight": sum(r["status"] == "dispatching" for r in manifests)}))
        return
    work = [(case, arm, repeat) for repeat in args.repeat or [1, 2] for arm in args.arm or ARMS for case in args.case or CASES]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(run_one, *job): job for job in work}
        for future in as_completed(pending):
            job = pending[future]
            try:
                future.result()
            except Exception as error:
                print(json.dumps({"failed": job, "error_type": type(error).__name__, "message": str(error)[:400]}), flush=True)


if __name__ == "__main__":
    main()
