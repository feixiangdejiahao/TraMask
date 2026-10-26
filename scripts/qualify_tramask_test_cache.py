"""Explicitly freeze, execute, or summarize Go cache qualification."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tramask_rerun.cache_qualification import freeze_protocol, qualify_case, summarize


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "summarize"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.phase != "summarize" and not args.case:
        parser.error("Explicit case IDs are required")
    if args.workers < 1 or args.workers > 2:
        parser.error("Use one or two case workers")
    if args.phase == "freeze":
        protocol = freeze_protocol(args.run, args.case)
        print(json.dumps({"status": "frozen", "case_ids": protocol["case_ids"]})); return
    if args.phase == "summarize":
        print(json.dumps(summarize(args.run), ensure_ascii=False)); return
    failed = False
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(qualify_case, case_id, args.run): case_id for case_id in sorted(set(args.case))}
        for future in as_completed(pending):
            try:
                result = future.result()
                print(json.dumps({key: result[key] for key in ("case_id", "status", "fresh_subject_test_executions",
                    "three_clean_uncached_executions", "runner_outcomes_stable", "outcomes_match_original_cached_reports")}), flush=True)
            except Exception as error:
                failed = True
                print(json.dumps({"case_id": pending[future], "status": "error", "type": type(error).__name__, "error": str(error)}), flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
