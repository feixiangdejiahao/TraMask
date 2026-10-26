"""Execute frozen direct-method candidates without a counterfactual gate.

Every registered cell/slot remains in generation artifacts. This runner selects
only structurally executable submitted edits, applies exact versioned tests,
and retains three clean P/original and P/augmented runs before oracle review.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_pilot.submission_replay import ENV
from tramask_rerun.reserved import load_cases
from tramask_rerun.runtime import execute_variant
from tramask_rerun.study import RUN, now, write_new
from tramask_rerun.validation_material import load_validation_material, plan_validation


def prepare(case, cell, slot):
    out = cell / "candidate_execution" / f"rank_{slot['rank']:02d}"
    if (out / "plan.json").exists():
        return out
    if out.exists():
        raise FileExistsError("Partial candidate preparation retained")
    planning = read(cell / "stage_01/planning.json")
    name = "qualified_validation_inventory_v02.json" if case["id"] in {"HF003", "HF005"} else "qualified_validation_inventory.json"
    directory = RUN / "runs" / case["id"]
    material = load_validation_material(receipt(cell / "stage_01/public_input.json"), receipt(directory / name),
        planning["selected_test_id"], checkpoint_proof_receipt=case["checkpoint"]["summary"],
        terminal_export_receipts=[receipt(directory / "terminal_sources/result.json")])
    staged = plan_validation(material, slot["candidate"])
    bound = [receipt(cell / "stage_02/candidate_slots.json"), receipt(cell / "stage_02/canonical_candidates.json"),
             receipt(cell / "stage_01/planning.json"), receipt(directory / name),
             receipt(ROOT / "src/tramask_rerun/validation_material.py"),
             receipt(ROOT / "src/tramask_rerun/runtime.py"), receipt(Path(__file__))]
    write_new(out / "plan.json", {"created_at": now(), "case": case, "staged": staged,
        "bound_artifacts": bound, "repeats": 3, "subject_test_run_cap_this_candidate": 6,
        "counterfactual_gate": False, "scientific_label": None,
        "interpretation": "Exact frozen direct candidate, independently on original P and augmented P. Three clean repeats establish executable stability before oracle review. Repeated execution of the same candidate is not additional search; all costs count toward the registered method/repeat cap. P is not presumed correct."})
    return out


def execute(out):
    plan = read(out / "plan.json")
    for bound in plan["bound_artifacts"]:
        if receipt(bound["path"]) != bound:
            raise ValueError("Frozen candidate execution binding changed")
    if (out / "summary.json").exists():
        return read(out / "summary.json")
    case = plan["case"]
    records = []
    for repeat in range(1, plan["repeats"] + 1):
        for name, arm in plan["staged"]["arms"].items():
            dest = out / f"repeat_{repeat:02d}" / name
            if dest.exists():
                raise FileExistsError("Partial candidate execution retained without retry")
            builds = [step["command"] if step["working_directory"] == arm["working_directory"]
                      else "cd " + shlex.quote(step["working_directory"]) + " && " + step["command"]
                      for step in arm["build_steps"]]
            binary_paths = [x["expected_binary_path"] for x in arm["build_steps"]]
            result = execute_variant(case["checkpoint"], dest, arm["command"], case["test_timeout_seconds"],
                files=arm["files"], observation_paths=binary_paths, build_commands=builds,
                env=ENV, workdir=arm["working_directory"], resources=case["resources"],
                generated_runtime=bool(builds), production_paths=[])
            execution = result.get("execution") or {}
            records.append({"repeat": repeat, "arm": name, "result": receipt(dest / "result.json"),
                "status": result["status"], "returncode": execution.get("returncode"), "timed_out": execution.get("timed_out"),
                "builds": len(result.get("builds", [])), "elapsed_test_seconds": execution.get("elapsed_seconds")})
    summary = {"case_id": case["id"], "completed_at": now(), "plan": receipt(out / "plan.json"),
        "runs": records, "subject_test_runs": sum(x["returncode"] is not None for x in records),
        "status": "executed_pending_independent_oracle_and_outcome_review", "scientific_label": None}
    write_new(out / "summary.json", summary)
    return summary


if __name__ == "__main__":
    cases = {c["id"]: c for c in load_cases()}
    outputs = []
    for path in sorted((RUN / "runs").glob("H*/track_b/M[12]/repeat_*/stage_02/candidate_slots.json")):
        cell = path.parent.parent
        cid = cell.parent.parent.parent.name
        for slot in read(path)["slots"]:
            if slot["status"] == "proposed" and slot["structural_valid"]:
                outputs.append(prepare(cases[cid], cell, slot))
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(execute, out): out for out in outputs}
        for future in as_completed(pending):
            try:
                result = future.result()
                print(json.dumps({"output": str(pending[future]), "status": result["status"], "test_runs": result["subject_test_runs"]}), flush=True)
            except Exception as error:
                print(json.dumps({"output": str(pending[future]), "status": "error", "error_type": type(error).__name__, "error": str(error)}), flush=True)
