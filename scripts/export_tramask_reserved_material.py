"""Read-only source export for explicitly completed reserved checkpoints."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.study import RUN, patch_paths, now, write_new
from tramask_rerun.reserved import load_cases
from tramask_rerun.runtime import export_checkpoint_files


def export(case):
    directory = RUN / "runs" / case["id"]
    output = directory / "terminal_sources"
    if (output / "result.json").exists():
        return {"case_id": case["id"], "status": "already_exported"}
    selected = read(directory / "validation_inventory_v01/proposed_selection.json")
    inventory = read(directory / "validation_inventory_v01/inventory.json")
    paths = set(selected["test_paths"] + selected["source_paths"] + selected.get("supporting_export_paths", []))
    paths.update(inventory.get("all_authored_test_paths", []))
    paths.update(patch_paths((RUN / "inputs" / case["id"] / "model.patch").read_text()))
    for name in ("package.json", "pyproject.toml", "pytest.ini", "go.mod", "Cargo.toml", "Makefile", "tsconfig.json", "jest.config.js", "jest.config.ts", "vitest.config.ts"):
        paths.add("/app/" + name)
    plan = {"case_id": case["id"], "created_at": now(), "paths": sorted(paths),
            "checkpoint": case["checkpoint"], "selection_proposal": receipt(directory / "validation_inventory_v01/proposed_selection.json"),
            "inventory": receipt(directory / "validation_inventory_v01/inventory.json"),
            "scope": "Read-only export. Does not activate test selection or qualify inventory completeness."}
    write_new(directory / "reserved_export_plan.json", plan)
    result = export_checkpoint_files(case["checkpoint"], output, sorted(paths), resources=case["resources"])
    return {"case_id": case["id"], "status": result["status"], "present": sum(x["status"] == "present" for x in result["files"]),
            "missing": [x["path"] for x in result["files"] if x["status"] != "present"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", required=True)
    args = parser.parse_args()
    cases = [c for c in load_cases() if c["id"] in args.case and c.get("partition") == "reserved" and "checkpoint" in c]
    if len(cases) != len(set(args.case)):
        raise ValueError("Every explicit reserved case must have a validated checkpoint")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(export, c): c["id"] for c in cases}
        for f in as_completed(futures):
            try:
                result = f.result()
            except Exception as error:
                result = {"case_id": futures[f], "status": "error", "error_type": type(error).__name__, "error": str(error)}
            print(json.dumps(result), flush=True)
