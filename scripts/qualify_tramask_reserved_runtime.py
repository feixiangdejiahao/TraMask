"""Explicit runner qualification for observed cache/worker failures only."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_pilot.submission_replay import ENV
from tramask_rerun.cache_qualification import cache_bypass_command
from tramask_rerun.reserved import load_cases
from tramask_rerun.runtime import execute_variant
from tramask_rerun.study import RUN, now, write_new

if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--case", choices=["HF007", "HS005"], required=True)
    args = parser.parse_args()
    case = next(c for c in load_cases() if c["id"] == args.case)
    directory = RUN / "runs" / case["id"]
    selected = read(directory / "selection.json")
    original = selected["command"]
    if args.case == "HF007":
        expected = "BABEL_ENV=test npx jest test/jest/atomic- 2>&1 | tail -8"
        if original != expected:
            raise ValueError("Unreviewed Jest command")
        command = "BABEL_ENV=test npx jest test/jest/atomic- --maxWorkers=2 2>&1"
        explanation = "Original runs terminate in Jest worker-spawn failure before any retained collection. Bind the worker pool to the task's two-CPU resource allocation and retain complete output. No file, test selector, test input, assertions or internal atomic/concurrent scenario changes. This is an explicitly separate runner stratum; original failures remain retained."
    else:
        command = cache_bypass_command(original)
        explanation = "Original three reports are cached. Disable Go test cache only, retaining complete original command and existing GOFLAGS."
    out = directory / "runner_qualification_v01"
    if out.exists():
        raise FileExistsError("Existing qualification retained")
    monitored = sorted(set(selected["test_paths"] + selected["source_paths"]))
    exports = {f["path"]: f for f in read(directory / "terminal_sources/result.json")["files"]}
    if any(exports.get(p, {}).get("status") != "present" for p in monitored):
        raise ValueError("Every monitored original file must be present")
    write_new(out / "plan.json", {"created_at": now(), "case_id": args.case,
        "checkpoint": case["checkpoint"], "selection": receipt(directory / "selection.json"),
        "original_baseline": receipt(directory / "baseline/summary.json"),
        "original_command": original, "effective_command": command,
        "rationale": explanation, "file_changes": [], "implementation": receipt(Path(__file__))})
    runs = []
    for repeat in [1, 2, 3]:
        dest = out / f"repeat_{repeat:02d}"
        result = execute_variant(case["checkpoint"], dest, command, case["test_timeout_seconds"],
            files={}, observation_paths=monitored, env=ENV,
            workdir=selected["working_directory"], resources=case["resources"])
        actual = {f["path"]: f.get("sha256") for f in result.get("observations", [])}
        runs.append({"repeat": repeat, "result": receipt(dest / "result.json"),
            "source_and_test_hashes_equal": all(actual.get(p) == exports[p]["sha256"] for p in monitored)})
    write_new(out / "summary.json", {"created_at": now(), "case_id": args.case,
        "status": "executed_pending_collection_and_stability_qualification", "runs": runs,
        "scientific_label": None, "plan": receipt(out / "plan.json")})
    print(json.dumps({"case_id": args.case, "executions": len(runs)}))
