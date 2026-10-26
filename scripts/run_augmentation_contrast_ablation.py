"""Paired removal of program feedback after the exact same early LLM plan."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts.run_augmentation_contrast_pilot import RUN, CASES, check, read, model_call
from augmentation import contrast_pilot as method
from augmentation.pipeline import write_json


def one(case, repeat):
    directory = RUN / "runs" / case / "F_plan_only" / f"repeat{repeat}"
    if (directory / "result.json").exists():
        return
    plan_path = RUN / "runs" / case / "E_semantic" / f"repeat{repeat}" / "stage1/parsed.json"
    while True:
        try:
            plan = read(plan_path)
            break
        except (OSError, ValueError):
            time.sleep(10)
    bundle = read(RUN / "inputs" / case / "bundle.json")
    write_json(directory / "shared_plan.json", {"source": str(plan_path.relative_to(ROOT)),
               "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(), "plan": plan})
    middle = {"public_evidence": bundle, "semantic_analysis_plan": plan, "program_feedback": []}
    system = method.COMMON + method.SCENARIO_FORMAT
    system += "\nRe-examine the inputs and operations. Keep only your two most promising concrete scenarios; you may revise your earlier choices.\n"
    proposed, first = model_call(directory / "stage2", {"id": f"{case}/F_plan_only/{repeat}/2", "system": system,
                                 "prompt": json.dumps(middle, ensure_ascii=True)}, "scenarios")
    print(json.dumps({"case": case, "arm": "F_plan_only", "repeat": repeat, "stage": 2}), flush=True)
    final, second = model_call(directory / "stage3", {"id": f"{case}/F_plan_only/{repeat}/3", "system": method.COMMON + method.FINAL_FORMAT,
                                 "prompt": json.dumps({"public_evidence": bundle, "proposed_scenarios": proposed}, ensure_ascii=True)}, "reviews")
    records = first + second
    result = {"case": case, "arm": "F_plan_only", "repeat": repeat, "final": final,
              "calls": sum(r.get("external_model_calls", 0) for r in records),
              "tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in records),
              "technical_unknown_stages": sum(bool(r.get("technical_unknown")) for r in [plan, proposed, final]),
              "response_models": sorted({r.get("response_model", "unknown") for r in records}),
              "shared_first_stage": str(plan_path.relative_to(ROOT)),
              "raw_material_sha256": hashlib.sha256((RUN / "inputs" / case / "bundle.json").read_bytes()).hexdigest()}
    write_json(directory / "result.json", result)
    print(json.dumps({"finished": f"{case}/F_plan_only/{repeat}", "calls": result["calls"], "tokens": result["tokens"],
                      "decisions": [r.get("decision") for r in final.get("reviews", [])]}), flush=True)


def main():
    check()
    protocol = RUN / "program_feedback_ablation_protocol.json"
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not protocol.exists():
        available = list(RUN.glob("runs/*/E_semantic/*/stage1/parsed.json"))
        if available:
            raise RuntimeError("ablation_must_be_registered_before_any_E_plan_arrives")
        write_json(protocol, {"registered_at": datetime.now(timezone.utc).isoformat(), "arm": "F_plan_only",
                   "paired_with": "E_semantic", "cases": CASES, "repeats": 2,
                   "purpose": "Separate early semantic planning from the incremental effect of program feedback.",
                   "design": "Reuse each exact E stage-1 plan. Stage-2 prompt differs only in program_feedback=[]; same raw materials/system/budgets. Common final review. No access to E hypotheses or final decisions.",
                   "cost": "2 fresh stages per case/repeat; E shared plan charged once in total costs, also report logical cost including it for per-arm comparisons.",
                   "max_tokens": 65536, "technical_recovery": "same as main protocol", "code_sha256": code_hash,
                   "reference_access": False, "E_plans_available_at_registration": 0})
    elif read(protocol)["code_sha256"] != code_hash:
        raise RuntimeError("ablation_code_changed")
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(one, case, repeat): (case, repeat) for repeat in [1, 2] for case in CASES}
        for future in as_completed(pending):
            try:
                future.result()
            except Exception as error:
                print(json.dumps({"failed": pending[future], "error_type": type(error).__name__, "message": str(error)[:300]}), flush=True)


if __name__ == "__main__":
    main()
