"""Post-freeze independent evaluation comparators for general augmentations.

These local alternatives are never exposed to direct generation. They address
the newly added observation/assertion, and do not imply that P is correct or
that a strict context-only masking witness exists.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_pilot.submission_replay import ENV
from tramask_rerun.reserved import load_cases
from tramask_rerun.runtime import execute_variant
from tramask_rerun.study import RUN, now, write_new
from tramask_rerun.validation_material import load_validation_material, plan_validation

COMPARATORS = {
    "HF003": {
        "path": "app/packages/quill/src/modules/toolbar.ts",
        "old": "  private updateImageInputAccept(toolbar: Toolbar | null) {\n    if (this.imageInput && toolbar) {",
        "new": "  private updateImageInputAccept(toolbar: Toolbar | null) {\n    if (this.imageInput && toolbar && false) {",
        "contract": "Shared editor-specific hidden image input must track the active editor. Disable only refreshing its accept attribute; initial creation, editor activation and user stimulus remain intact.",
    },
    "HF005": {
        "path": "app/src/formatter/ExpressionFormatter.ts",
        "old": "  private isOnelinePipeClause(node: ClauseNode): boolean {\n    return this.dialectCfg.onelinePipeClauses[node.nameKw.text];\n  }",
        "new": "  private isOnelinePipeClause(node: ClauseNode): boolean {\n    return node.nameKw.text !== 'AS' && this.dialectCfg.onelinePipeClauses[node.nameKw.text];\n  }",
        "contract": "Issue explicitly requires AS content on the same line. Disable only AS membership in the one-line pipe-clause policy, preserving parser, input and other clauses.",
    },
}


def prepare(case, rep):
    cid = case["id"]
    cell = RUN / "runs" / cid / "track_b/M2" / f"repeat_{rep:02d}"
    out = cell / "candidate_execution/rank_01/evaluator_comparator_v01"
    if out.exists():
        raise FileExistsError("Existing independent comparator retained")
    slot = read(cell / "stage_02/candidate_slots.json")["slots"][0]
    if slot["status"] != "proposed":
        raise ValueError("Exact frozen submitted candidate required")
    planning = read(cell / "stage_01/planning.json")
    directory = RUN / "runs" / cid
    material = load_validation_material(receipt(cell / "stage_01/public_input.json"),
        receipt(directory / "qualified_validation_inventory_v02.json"), planning["selected_test_id"],
        checkpoint_proof_receipt=case["checkpoint"]["summary"],
        terminal_export_receipts=[receipt(directory / "terminal_sources/result.json")])
    proposed = COMPARATORS[cid]
    qpath = out / "fixed_evaluator_Q.json"
    write_new(qpath, {"created_at": now(), "role": "post-output independent evaluation comparator",
        "edits": [{k: proposed[k] for k in ("path", "old", "new")}],
        "contract_to_review_independently": proposed["contract"],
        "issue": receipt(RUN / "inputs" / cid / "instruction.md"),
        "candidate_frozen_before_construction": receipt(cell / "stage_02/canonical_candidates.json"),
        "P_results": receipt(cell / "candidate_execution/rank_01/summary.json"),
        "not_given_to_generator": True, "Q_may_be_correct_or_incorrect_until_review": True,
        "researcher_exposure": "Root constructed this targeted comparator after all candidate outputs and P executions froze, having seen reference work. This is post-freeze evaluation, not blind gold construction or an independent method replicate.",
        "old_unrelated_test_failures": "Retain all original suite failures. Evaluate the newly added test/assertion separately; never infer a new missed P defect from an old failure."})
    staged = plan_validation(material, slot["candidate"], fixed_q_receipt=receipt(qpath),
        frozen_output_receipt=receipt(cell / "stage_02/canonical_candidates.json"))
    write_new(out / "plan.json", {"case": case, "staged": staged, "created_at": now(), "repeats": 3,
        "independent_evaluation_cost_not_generation": True,
        "implementation": [receipt(Path(__file__)), receipt(ROOT / "src/tramask_rerun/validation_material.py"), receipt(ROOT / "src/tramask_rerun/runtime.py")]})
    return out


def execute(out):
    plan = read(out / "plan.json")
    for bound in plan["implementation"]:
        if receipt(bound["path"]) != bound:
            raise ValueError("Comparator execution implementation changed")
    case = plan["case"]
    records = []
    for repeat in [1, 2, 3]:
        for name in ["q_original", "q_candidate"]:
            arm = plan["staged"]["arms"][name]
            if arm["build_steps"]:
                raise ValueError("This explicit TS comparison expects source-transform runners")
            dest = out / f"repeat_{repeat:02d}" / name
            if dest.exists():
                raise FileExistsError("Partial comparator attempt retained")
            result = execute_variant(case["checkpoint"], dest, arm["command"], case["test_timeout_seconds"],
                files=arm["files"], env=ENV, workdir=arm["working_directory"], resources=case["resources"])
            e = result.get("execution") or {}
            records.append({"repeat": repeat, "arm": name, "result": receipt(dest / "result.json"),
                "status": result["status"], "returncode": e.get("returncode"), "timed_out": e.get("timed_out")})
    summary = {"case_id": case["id"], "created_at": now(), "runs": records,
        "status": "executed_pending_independent_semantic_review", "scientific_label": None}
    write_new(out / "summary.json", summary)
    return summary


if __name__ == "__main__":
    cases = {c["id"]: c for c in load_cases()}
    outputs = [prepare(cases[cid], rep) for cid in COMPARATORS for rep in [1, 2]]
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = {pool.submit(execute, out): out for out in outputs}
        for future in as_completed(pending):
            try:
                r = future.result()
                print(json.dumps({"output": str(pending[future]), "status": r["status"], "runs": len(r["runs"])}), flush=True)
            except Exception as error:
                print(json.dumps({"output": str(pending[future]), "error_type": type(error).__name__, "error": str(error)}), flush=True)
