#!/usr/bin/env python3
"""Offline checkpoint reuse/replay and explicit plan execution without verdict inference."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from context_recovery_pilot1_runtime import DEFAULT_CHECKPOINTS, DEFAULT_RUN, execute_plan, replay_screen, validate_screen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    replay = commands.add_parser("replay", help="Record a cached checkpoint or create a fresh chronological replay")
    replay.add_argument("--screen-id", required=True)
    replay.add_argument("--run", type=Path, default=DEFAULT_RUN)
    replay.add_argument("--checkpoint-index", type=Path, default=DEFAULT_CHECKPOINTS)
    replay.add_argument("--attempt", default="replay_attempt_001",
                        help="Explicit fresh directory name, for example replay_attempt_002; never overwrites a prior attempt")
    validate = commands.add_parser("validate", help="Independently validate a submission checkpoint in a fresh clone")
    validate.add_argument("--screen-id", required=True)
    validate.add_argument("--run", type=Path, default=DEFAULT_RUN)
    execute = commands.add_parser("execute", help="Execute one plan in a fresh isolated Docker container")
    execute.add_argument("--plan", required=True, type=Path)
    execute.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "replay":
        result = replay_screen(args.screen_id, run=args.run, checkpoint_index=args.checkpoint_index, attempt=args.attempt)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.action == "validate":
        result = validate_screen(args.screen_id, run=args.run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 2
    path = args.plan.resolve(strict=True)
    result = execute_plan(json.loads(path.read_bytes()), args.out, base_directory=path.parent)
    print(json.dumps({key: result.get(key) for key in ("status", "target_executed", "failed_step", "error_type")}, ensure_ascii=False))
    # A target's nonzero rc remains data. Only runner/preparation errors fail the CLI.
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
