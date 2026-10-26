"""Execute frozen technical bindings for investigator measurement variants."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.study import RUN
from tramask_rerun.paired import execute_qualified_pair


def execute(case_id):
    directory = RUN / "runs" / case_id / "measurement_execution_v01"
    inputs = read(directory / "inputs.json")
    for bound in inputs["bound_artifacts"]:
        if receipt(bound["path"]) != bound:
            raise ValueError("Frozen measurement artifact changed")
    result = execute_qualified_pair(inputs["case"], inputs["source_files"], inputs["hypothesis"], directory / "execution",
        source_origins=inputs["source_origins"], test_paths=inputs["test_paths"],
        review=read(directory / "execution_review.json"), build_commands=inputs["build_commands"],
        generated_runtime=inputs["generated_runtime"], observation_paths=inputs["observation_paths"], repeats=3)
    return {"case_id": case_id, "status": "paired_measurement_completed_pending_scientific_review",
            "summary": receipt(directory / "execution/summary.json")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", required=True)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(execute, cid): cid for cid in args.case}
        for f in as_completed(futures):
            try:
                result = f.result()
            except Exception as error:
                result = {"case_id": futures[f], "status": "error", "error_type": type(error).__name__, "error": str(error)}
            print(json.dumps(result), flush=True)
