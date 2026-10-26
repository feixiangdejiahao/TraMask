"""Explicit phases of the preregistered TraMask replay pilot."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from tramask_pilot.corpus import RUN, initialize, input_directory, read, receipt, write


def acquire(c):
    import httpx
    dest = input_directory(c)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("instruction.md", "task.toml", "model.patch", "trajectory.json"):
        target = dest / name
        if target.exists():
            continue
        if c["source"]:
            shutil.copyfile(Path(c["source"]) / name, target)
        elif name in {"instruction.md", "task.toml"}:
            shutil.copyfile(Path(c["task_directory"]) / name, target)
        else:
            suffix = "agent/trajectory.json" if name == "trajectory.json" else "artifacts/model.patch"
            url = f"https://d3ujjcmjq6o8v6.cloudfront.net/v1.1/trial-artifacts/{c['trial']}/{suffix}"
            with httpx.Client(timeout=90, follow_redirects=False) as client:
                response = client.get(url)
                response.raise_for_status()
            target.write_bytes(response.content)
    write(dest / "provenance.json", {"case": c, "files": [receipt(dest / n) for n in ("instruction.md", "task.toml", "model.patch", "trajectory.json")]})
    return {"id": c["id"], "status": "acquired"}


def repair_context(c):
    from tramask_pilot.context_repair import recover_final_context
    return recover_final_context(c, out=c.get("replay_run", "replay_context_repair01"))


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("phase", choices=["initialize", "acquire", "locate", "replay", "repair-context", "hypothesize", "pair"])
    p.add_argument("--case", action="append")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--replay-attempt", help="New replay directory; repair-context defaults to replay_context_repair01")
    p.add_argument("--hypothesis-attempt", default="target_hypothesis")
    args = p.parse_args()
    args.replay_attempt = args.replay_attempt or ("replay_context_repair01" if args.phase == "repair-context" else "replay")
    selection = initialize()
    all_cases = selection["calibration"] + selection["failed_order"] + selection["successful_order"]
    if args.phase == "initialize":
        print(json.dumps({k: len(v) if isinstance(v, list) else v for k, v in selection.items() if k != "selection_rule"})); return
    if not args.case:
        p.error("Specify --case explicitly; this prevents accidental full-corpus runs")
    cases = [c for c in all_cases if c["id"] in args.case]
    if len(cases) != len(set(args.case)):
        p.error("Unknown case ID")
    if any(not name.replace("_", "").isalnum() for name in (args.replay_attempt, args.hypothesis_attempt)):
        p.error("Attempt names must be simple directory names")
    cases = [{**c, "replay_run": args.replay_attempt, "hypothesis_run": args.hypothesis_attempt} for c in cases]
    if args.phase == "acquire":
        fn = acquire
    elif args.phase == "repair-context":
        fn = repair_context
    else:
        from tramask_pilot import experiment
        fn = getattr(experiment, args.phase)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fn, c): c for c in cases}
        for f in as_completed(futures):
            c = futures[f]
            try:
                print(json.dumps(f.result(), ensure_ascii=False), flush=True)
            except Exception as e:
                error = {"id": c["id"], "phase": args.phase, "status": "error", "type": type(e).__name__, "message": str(e)}
                error_path = RUN / "errors" / f"{args.phase}_{c['id']}.json"
                if args.phase == "repair-context":
                    error_path = RUN / "errors" / f"{args.phase}_{c['id']}_{args.replay_attempt}.json"
                    if error_path.exists():
                        error_path = error_path.with_name(error_path.stem + "_" + uuid.uuid4().hex[:12] + ".json")
                write(error_path, error)
                print(json.dumps(error), flush=True)


if __name__ == "__main__":
    main()
