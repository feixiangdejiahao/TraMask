"""Execute only explicitly prepared uninstrumented P/Q controls."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_rerun.original_pairs_reserved_v02 import execute

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", required=True)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(execute, cid): cid for cid in args.case}
        for f in as_completed(futures):
            try:
                result = f.result()
                result = {"case_id": result["case_id"], "status": result["status"], "runs": [{k: row.get(k) for k in ("repeat", "variant", "status", "returncode", "timed_out")} for row in result["runs"]]}
            except Exception as error:
                result = {"case_id": futures[f], "status": "error", "error_type": type(error).__name__, "error": str(error)}
            print(json.dumps(result), flush=True)
