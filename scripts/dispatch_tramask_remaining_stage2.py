"""Serial registered-order dispatch, preserving every ineligible/budget cell."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.reserved import load_cases
from tramask_rerun.study import RUN, now, write_new
from tramask_rerun.track_b_v02 import generate as initial
from tramask_rerun.track_b_v03 import generate as later
from tramask_rerun.track_b_v04 import generate as final_two

if __name__ == "__main__":
    out = RUN / "track_b_stage2_dispatch_v01"
    if out.exists():
        raise FileExistsError("Existing serial queue attempt is retained")
    write_new(out / "plan.json", {"created_at": now(),
        "queue": receipt(RUN / "remaining_model_dispatch_queue_v01.json"),
        "order": "registered case, physical repeat 1 then2, M1-M4",
        "concurrency": 1, "global_token_cap": 10000000,
        "zero_call_budget_denials_not_retried": True,
        "implementation": receipt(Path(__file__))})
    records = []
    for case in load_cases():
        if case["partition"] != "reserved":
            continue
        generate = final_two if case["id"] in {"HF002", "HS002"} else initial if case["id"] in {"HF004", "HF006", "HF007", "HF010", "HF011"} else later
        for rep in [1, 2]:
            for method in ["M1", "M2", "M3", "M4"]:
                root = RUN / "runs" / case["id"] / "track_b" / method / f"repeat_{rep:02d}"
                first = read(root / "stage_01/result.json")
                row = {"case_id": case["id"], "method": method, "repeat": rep, "stage1": receipt(root / "stage_01/result.json")}
                permitted = first["status"] == "planning_qualified_for_next_generation" and method in {"M1", "M2"}
                if method in {"M3", "M4"} and (root / "target_execution/qualification.json").exists():
                    permitted = read(root / "target_execution/qualification.json").get("qualified_for_stage2") is True
                if (root / "stage_02/result.json").exists():
                    row.update(status="existing_completed_stage2_retained", result=receipt(root / "stage_02/result.json"))
                elif not permitted:
                    row.update(status="stage2_prerequisite_not_met", stage1_status=first["status"])
                else:
                    try:
                        result = generate(case, method, rep, 2)
                        row.update(status=result["status"], provider_status=result.get("provider_status"),
                            physical_model_calls=result.get("physical_model_calls", 0), result=receipt(root / "stage_02/result.json"))
                    except Exception as error:
                        row.update(status="dispatch_error_retained", error_type=type(error).__name__, error=str(error))
                records.append(row)
                write_new(out / f"{case['id']}_{method}_{rep}.json", row)
                print(json.dumps({k: row.get(k) for k in ("case_id", "method", "repeat", "status", "provider_status", "physical_model_calls")}), flush=True)
    write_new(out / "summary.json", {"completed_at": now(), "records": records,
        "interpretation": "Budget-denied cells are unavailable observations, not model failures; pending two-flip prerequisites remain separate."})
