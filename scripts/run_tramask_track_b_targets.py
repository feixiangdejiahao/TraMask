"""Execute the eight frozen model-proposed two-flip target plans verbatim."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import receipt
from tramask_rerun.reserved import load_cases
from tramask_rerun.study import RUN, now, write_new
from tramask_rerun.track_b_targets import CELLS, prepare_registered_cell, write_preparation, execute_preparation


if __name__ == "__main__":
    cases = {c["id"]: c for c in load_cases()}
    outputs = []
    for cid, method, repeat in CELLS:
        cell = RUN / "runs" / cid / "track_b" / method / f"repeat_{repeat:02d}"
        policy = None
        if cid == "HS003":
            p = cell / "target_runner_policy_v01.json"
            write_new(p, {"kind": "go_cache_bypass", "approved_for_execution": True,
                "shared_across_all_arms": True,
                "qualification_receipt": receipt(RUN / "runs/HS003/original_pair_controls_v02/plan.json")})
            policy = receipt(p)
        prepared = prepare_registered_cell(cases[cid], method, repeat, RUN, runner_policy_receipt=policy)
        bound = write_preparation(prepared, cell / "target_preparation_v01.json")
        outputs.append((bound, cell / "target_execution"))
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(execute_preparation, bound, out): out for bound, out in outputs}
        for future in as_completed(pending):
            try:
                result = future.result()
                print(json.dumps({"output": str(pending[future]), "status": result["status"],
                    "subject_runs": result["subject_command_executions"]}), flush=True)
            except Exception as error:
                print(json.dumps({"output": str(pending[future]), "status": "error", "error_type": type(error).__name__, "error": str(error)}), flush=True)
