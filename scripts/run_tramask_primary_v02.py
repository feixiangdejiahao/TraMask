"""Explicit phases of the revised evidence-checklist study."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tramask_pilot.corpus import read
from tramask_rerun.study import RUN, export_paths, import_original_inputs, write_new


def export_case(case, run):
    from tramask_rerun.runtime import export_checkpoint_files
    out = run / "runs" / case["id"] / "terminal_sources"
    result_path = out / "result.json"
    if result_path.exists():
        return {"case_id": case["id"], "status": "already_exported"}
    result = export_checkpoint_files(case["checkpoint"], out, export_paths(case["id"], run),
                                     resources=case["resources"])
    # The runtime owns result.json. Keep the orchestration receipt separate.
    write_new(run / "runs" / case["id"] / "source_export_receipt.json", {
        "case_id": case["id"], "checkpoint": case["checkpoint"], "export_directory": str(out),
        "status": result["status"], "requested_paths": export_paths(case["id"], run)})
    return {"case_id": case["id"], "status": result["status"],
            "present": sum(row.get("status") == "present" for row in result.get("files", [])),
            "missing": [row["path"] for row in result.get("files", []) if row.get("status") == "missing"]}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("phase", choices=("import-original", "sample-reserved", "acquire-reserved", "replay-reserved", "export", "baseline", "baseline-capsule", "target"))
    parser.add_argument("--run", type=Path, default=RUN)
    parser.add_argument("--case", action="append")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.phase == "import-original":
        print(json.dumps({"imported": len(import_original_inputs(args.run))})); return
    from tramask_rerun.reserved import load_cases
    if args.phase == "sample-reserved":
        from tramask_rerun.reserved import sample
        selected = sample(args.run)
        print(json.dumps({"status": selected["status"], "counts": selected["counts"]})); return
    cases = load_cases(args.run)
    if not args.case:
        parser.error("Select explicit --case IDs; no accidental corpus-wide execution")
    selected = [case for case in cases if case["id"] in args.case]
    if len(selected) != len(set(args.case)):
        parser.error("Unknown case ID")
    if args.phase in {"acquire-reserved", "replay-reserved"}:
        from tramask_rerun.reserved import acquire, replay
        fn = acquire if args.phase == "acquire-reserved" else replay
    elif args.phase == "target":
        from tramask_rerun.generation_primary_v02 import target
        fn = target
    elif args.phase in {"baseline", "baseline-capsule"}:
        from tramask_rerun.workflow_primary_v02 import baseline
        fn = lambda case, run: baseline(case, run, capsule=args.phase == "baseline-capsule")
    else:
        fn = export_case
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fn, case, args.run): case["id"] for case in selected}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as error:
                result = {"case_id": futures[future], "status": "error",
                          "error_type": type(error).__name__, "error": str(error)}
            if args.phase in {"baseline", "baseline-capsule"} and "runs" in result:
                result = {"case_id": result["case_id"], "status": result["status"],
                          "runs": [{k: row.get(k) for k in ("repeat", "status", "returncode", "timed_out", "elapsed_seconds")} for row in result["runs"]],
                          "missing_selected_test_paths": result["missing_selected_test_paths"]}
            elif args.phase == "target":
                result = {k: result.get(k) for k in ("case_id", "status", "provider_status", "physical_model_calls", "reason", "error")}
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
