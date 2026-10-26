"""One explicit HF001 replay using its observed compound submission boundary."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.study import RUN, write_new
from tramask_rerun.reserved import load_cases
from tramask_rerun.replay_v02 import replay_case, inspect_image_availability


if __name__ == "__main__":
    policy = read(RUN / "amendments/003_observed_submission_boundary.json")
    for bound in policy["implementation"]:
        if receipt(bound["path"]) != bound:
            raise ValueError("Boundary replay implementation differs from frozen amendment")
    case = next(c for c in load_cases() if c["id"] == "HF001")
    if not inspect_image_availability(case["image"])["available"]:
        raise ValueError("Expected previously acquired public task image")
    result = replay_case(case, RUN / "inputs/HF001", RUN / "runs/HF001/submission_replay_v02")
    if result.get("state_validation_passed"):
        write_new(RUN / "runs/HF001/active_submission_state.json", result["study_checkpoint"])
    print(json.dumps({k: result.get(k) for k in ("id", "status", "actions_executed", "state_validation_passed", "risks")}), flush=True)
