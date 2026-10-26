"""Dispatch explicit registered Track B cells without implicit model retries."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_rerun.reserved import load_cases
from tramask_rerun.track_b import generate

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--stage", type=int, choices=[1, 2], default=1)
    parser.add_argument("--method", action="append", choices=["M1", "M2", "M3", "M4"])
    args = parser.parse_args()
    methods = args.method or (["M1", "M2", "M3", "M4"] if args.stage == 1 else ["M1", "M2"])
    cases = [c for c in load_cases() if c["id"] in args.case]
    if len(cases) != len(set(args.case)):
        raise ValueError("Unknown case")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(generate, c, m, rep, args.stage): (c["id"], m, rep) for c in cases for rep in [1, 2] for m in methods}
        for future in as_completed(futures):
            try:
                result = future.result()
                result = {k: result.get(k) for k in ("case_id", "method", "repeat", "stage", "status", "physical_model_calls", "error")}
            except Exception as error:
                result = {"cell": futures[future], "status": "error", "error_type": type(error).__name__, "error": str(error)}
            print(json.dumps(result), flush=True)
