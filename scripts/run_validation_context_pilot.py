"""Run the frozen six-task validation-context pilot with original-patch feedback."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]
from augmentation import validation_context_pilot as method
from augmentation.pipeline import write_json
from augmentation.provider import dispatch, MODEL
from augmentation.trajectory_contrast import trajectory_index, excerpt

OLD = ROOT/"experiments/relation_distinction/results/trajectory_contrast8_20261010_v2"
RAW = ROOT/"experiments/relation_distinction/results/contrast_pilot8_20261009_v2"
ORIGINAL = ROOT/"experiments/relation_distinction/results/pilot30_20261007_v1"
RUN = ROOT/"experiments/validation_context/results/pilot6_20261016_v1"
CASES = ["T11", "T13", "T17", "T23", "T24", "T28"]
ARMS = ["A_source", "B_history", "C_validation", "D_no_feedback"]


def read(path):
    return json.loads(Path(path).read_text())


def hashes():
    return {str(p.relative_to(ROOT)): method.digest(p) for p in
            [Path(__file__), Path(method.__file__), ROOT/"src/augmentation/provider.py", ROOT/"src/augmentation/trajectory_contrast.py",
             ROOT/"combination_testing/runner.py", ROOT/"generic_composition/runner.py"]}


def prepare():
    RUN.mkdir(parents=True, exist_ok=False)
    cases = [c for c in read(OLD/"cases.json") if c["id"] in CASES]
    for c in cases:
        c["base_commit"] = read(ORIGINAL/"cases"/c["id"]/"repository_provenance.json")["base_commit"]
    write_json(RUN/"cases.json", cases)
    for case in cases:
        cid = case["id"]
        original = read(RAW/"inputs"/cid/"bundle.json")
        history, events = trajectory_index(case, original)
        raw_steps = {str(s.get("step_id")): s for s in read(case["trajectory"]).get("steps", [])}
        for event in events:
            step = raw_steps.get(str(event["step"]), {})
            event["agent_note"] = str(step.get("message", ""))+"\n"+str(step.get("reasoning_content", ""))
        base = {k: original[k] for k in ("public_requirement", "changed_paths", "source", "validation_tests")}
        for test in base["validation_tests"]:
            for key in ("origin", "written_path", "step_id", "execution"):
                test.pop(key, None)
        base["source_file_index"] = method.file_index(case["repository"])
        base["limits"] = "Current source excerpts and original validation bodies; some bodies were recovered from trajectory. Excerpts are not exhaustive. No proof that any listed test ran on the final patch. Query full source or history when needed."
        base["test_environment"] = {"language": case["language"], "generated_name_marker": "CCPilot", "execution": "Fresh network-isolated original-patch container; repository framework and dependencies."}
        directory = RUN/"inputs"/cid
        write_json(directory/"base.json", base)
        write_json(directory/"history.json", history)
        write_json(directory/"events.json", events)
        write_json(directory/"source_receipts.json", {p: method.digest(Path(case["repository"])/p) for p in base["source_file_index"]})
    protocol = {
        "created_at": datetime.now(timezone.utc).isoformat(), "model": MODEL, "cases": CASES, "arms": ARMS, "repeats": 2,
        "objective": "Identify whether original validation's context restrictions are a useful search target, whether development history provides independent evidence, and whether original-patch runtime feedback helps realize a target.",
        "selection": "Six already studied development tasks: four with known repair-relevant combination targets and two with prior selection/false-positive opportunities. T11/T23 are not assumed bug-free. No held-out generalization claim.",
        "software_engineering_hypothesis": "A repository patch is validated under concrete choices of inputs, state, entry points and observations. Agent history may explain these restrictions. Reusing validation while changing a requirement-relevant context may reveal errors missed by separate checks.",
        "arms_definition": {
            "A_source": "Open investigator, final source and same original test bodies; source/test/AST shared-call queries; no development events.",
            "B_history": "Same open investigator, plus automatically indexed development history and original history queries.",
            "C_validation": "Same evidence/tools/call budget as B, but explicitly uses original validation's context and history to propose a transferable test target; no mandatory source-pair or full semantic model.",
            "D_no_feedback": "Shares the exact C inspection, retrieval and draft test. Final model review receives no execution output. Isolates runtime feedback at the repair step."
        },
        "logical_calls_per_run": 3, "unique_planned_calls": 120, "planned_final_outcomes": 48,
        "stage1": "Up to two hypotheses and six source/test/AST/history queries.",
        "stage2": "Choose one target, report a decision, and generate up to two files/three named tests. Execute on the original patch.",
        "stage3": "One full revision with actual original-patch execution feedback, or identical-budget self-review in D. Execute final tests; evaluator separately checks their conditions and oracle.",
        "max_tokens_per_call": 65536, "temperature": 0, "thinking": "enabled", "reasoning_effort": "high",
        "budget_limit": "Equal request/call caps, not guaranteed equal actual tokens or runtime. Report actual usage. Shared C/D calls counted once physically and in both logical budgets.",
        "technical_recovery": "At most one identical-input retry for a completed invalid/incomplete response. Ambiguous inflight calls are not silently resent. All attempts remain recorded.",
        "fixed_reference_ids": ["T13-R1", "T17-R1", "T24-R1", "T24-G2", "T28-R1"],
        "evaluation": "Review all final affirmative targets against original/gold semantics, issue requirements and original tests. Separate repair-relevant targets, other valid gaps, selection/oracle/feedback problems, rejected claims and unknowns. Report task success and fixed-target hits/misses separately. Test generation additionally needs the proposed conditions and correct observation. Dynamic original-fail/gold-pass requires portable independently justified tests; private-helper cases may receive separate static judgments.",
        "information_boundaries": "Public original patch/issue/trajectory only during generation. No manual target materials, gold source, benchmark failure tests or evaluator feedback are sent to the provider.",
        "causal_limits": "B/C compare a focused information-use policy with an open policy, not a learned independent program-analysis algorithm. C/D isolates raw runtime feedback, not yet condition-specific instrumentation. Before/after draft success alone is not causal evidence.",
        "provider_authorization": "User's standing authorization to send source and experiment data to the .env provider; continue the previously requested DeepSeek-v4-flash model.",
        "code_sha256": hashes(),
        "input_sha256": {str(p.relative_to(RUN)): method.digest(p) for p in sorted((RUN/"inputs").glob("*/*.json"))}
    }
    write_json(RUN/"protocol.json", protocol)
    print(json.dumps({"prepared": CASES, "unique_planned_calls": 120, "outcomes": 48}), flush=True)


def check():
    p = read(RUN/"protocol.json")
    if p["code_sha256"] != hashes():
        raise RuntimeError("frozen_code_changed")
    for path, digest in p["input_sha256"].items():
        if method.digest(RUN/path) != digest:
            raise RuntimeError("frozen_input_changed:"+path)
    return p


def model_call(directory, system, material, *, inspect=False):
    directory = Path(directory)
    if (directory/"parsed.json").exists():
        return read(directory/"parsed.json")
    request = {"id": str(directory.relative_to(RUN)), "system": method.COMMON+system,
               "prompt": json.dumps(material, ensure_ascii=False), "max_tokens": 65536}
    for attempt in range(2):
        output = directory/("primary" if attempt == 0 else "technical_recovery")
        if (output/"manifest.json").exists():
            log = read(output/"manifest.json")
            if log["status"] in {"prepared", "dispatching"}:
                raise RuntimeError("ambiguous_inflight:"+str(output))
        else:
            log = dispatch(request, output, root=ROOT, model=MODEL)
        try:
            if log["status"] != "complete":
                raise ValueError("provider_did_not_finish")
            result = method.validate_response(read(output/"completion.txt"), inspect=inspect)
            write_json(directory/"parsed.json", result)
            print(json.dumps({"stage": request["id"], "decision": result.get("decision"), "attempt": attempt+1,
                              "tokens": (log.get("usage") or {}).get("total_tokens")}), flush=True)
            return result
        except (ValueError, KeyError, OSError, TypeError) as exc:
            write_json(directory/f"parse_error_{attempt}.json", {"type": type(exc).__name__, "error": str(exc)[:500]})
    result = {"decision": "unknown", "target": {}, "tests": [], "hypotheses": [], "queries": [], "technical_unknown": True}
    write_json(directory/"parsed.json", result)
    return result


def run_one(case, arm, repeat):
    cid = case["id"]
    directory = RUN/"runs"/cid/arm/f"repeat{repeat}"
    if (directory/"result.json").exists():
        return read(directory/"result.json")
    base = read(RUN/"inputs"/cid/"base.json")
    public = dict(base)
    if arm != "A_source":
        public["development_history"] = read(RUN/"inputs"/cid/"history.json")
    framing = method.FOCUSED if arm == "C_validation" else method.OPEN
    stage1 = model_call(directory/"stage1", framing+method.INSPECT, {"public_evidence": public}, inspect=True)
    answers = method.serve_queries(case, base, read(RUN/"inputs"/cid/"events.json"), stage1.get("queries", []), history_allowed=arm != "A_source")
    write_json(directory/"retrieved.json", answers)
    material = {"public_evidence": public, "investigation": stage1, "retrieved_evidence": answers}
    stage2 = model_call(directory/"stage2", framing+method.BUILD, material)
    feedback = method.execute_response(case, stage2, directory/"draft_execution")
    common = {**material, "draft": stage2}
    targets = [(arm, {**common, "original_patch_execution": feedback})]
    if arm == "C_validation":
        targets.append(("D_no_feedback", {**common, "original_patch_execution": "Withheld in this control. Perform self-review."}))
    for final_arm, final_material in targets:
        out = RUN/"runs"/cid/final_arm/f"repeat{repeat}"
        if (out/"result.json").exists():
            continue
        final = model_call(out/"stage3", framing+method.BUILD+method.REVISE, final_material)
        execution = method.execute_response(case, final, out/"final_execution")
        result = {"case": cid, "arm": final_arm, "repeat": repeat, "decision": final.get("decision"),
                  "final": final, "execution_status": execution["status"], "technical_unknown": bool(final.get("technical_unknown")),
                  "shared_prefix": str(directory.relative_to(RUN)) if final_arm == "D_no_feedback" else None}
        write_json(out/"result.json", result)
        print(json.dumps({"finished": f"{cid}/{final_arm}/{repeat}", "decision": final.get("decision"), "execution": execution["status"]}), flush=True)
    return read(directory/"result.json")


def status():
    logs = [read(p) for p in RUN.glob("runs/**/manifest.json") if "model" in read(p)]
    print(json.dumps({"finished": len(list(RUN.glob("runs/*/*/*/result.json"))), "planned": 48,
                      "calls": sum(l.get("external_model_calls", 0) for l in logs),
                      "inflight": sum(l["status"] == "dispatching" for l in logs),
                      "tokens": sum((l.get("usage") or {}).get("total_tokens", 0) for l in logs),
                      "response_models": sorted({str(l.get("response_model")) for l in logs if l.get("response_model")})}), flush=True)


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("action", choices=["prepare", "run", "status"])
    p.add_argument("--case", action="append")
    p.add_argument("--arm", action="append", choices=ARMS[:3])
    p.add_argument("--repeat", type=int, action="append")
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    if a.action == "prepare":
        prepare(); return
    check()
    if a.action == "status":
        status(); return
    cases = [c for c in read(RUN/"cases.json") if not a.case or c["id"] in a.case]
    jobs = [(c, arm, repeat) for repeat in a.repeat or [1,2] for c in cases for arm in a.arm or ARMS[:3]]
    errors = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = {pool.submit(run_one, *job): (job[0]["id"], *job[1:]) for job in jobs}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as exc:
                errors.append(futures[f]); print(json.dumps({"failed": futures[f], "error_type": type(exc).__name__, "message": str(exc)[:250]}), flush=True)
    status()
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
