"""Dispatch only the explicitly frozen P1 material-completion cases."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read
from tramask_rerun.reference_completion import complete
from tramask_rerun.reserved import load_cases
from tramask_rerun.study import RUN

if __name__ == "__main__":
    allowed = read(RUN / "amendments/002_counterfactual_material_completion.json")["eligible_cases"]
    cases = [case for case in load_cases() if case["id"] in allowed]
    if len(cases) != len(allowed):
        raise ValueError("Unknown registered material-completion case")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(complete, case): case["id"] for case in cases}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as error:
                result = {"case_id": futures[future], "status": "error", "error_type": type(error).__name__, "error": str(error)}
            print(json.dumps(result, ensure_ascii=False), flush=True)
