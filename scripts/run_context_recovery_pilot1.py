#!/usr/bin/env python3
"""Offline checkpoint reuse/replay and explicit plan execution without verdict inference."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from context_recovery_pilot1_runtime import DEFAULT_CHECKPOINTS, DEFAULT_RUN, execute_plan, qualify_saved_replay, replay_screen, validate_screen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    replay = commands.add_parser("replay", help="Record a cached checkpoint or create a fresh chronological replay")
    replay.add_argument("--screen-id", required=True)
    replay.add_argument("--run", type=Path, default=DEFAULT_RUN)
    replay.add_argument("--checkpoint-index", type=Path, default=DEFAULT_CHECKPOINTS)
    replay.add_argument("--collect-validation-tests", action="store_true",
                        help="Collect EviWeave Step A source versions and execution associations during replay")
    replay.add_argument("--fresh", action="store_true", help="Replay chronologically instead of using checkpoint cache")
    replay.add_argument("--attempt", default="replay_attempt_001",
                        help="Explicit fresh directory name, for example replay_attempt_002; never overwrites a prior attempt")
    validate = commands.add_parser("validate", help="Independently validate a submission checkpoint in a fresh clone")
    validate.add_argument("--screen-id", required=True)
    validate.add_argument("--run", type=Path, default=DEFAULT_RUN)
    qualify = commands.add_parser("qualify-saved", help="Freshly qualify a completed saved replay in a new attempt")
    qualify.add_argument("--screen-id", required=True)
    qualify.add_argument("--run", type=Path, default=DEFAULT_RUN)
    qualify.add_argument("--replay-attempt", default="replay_attempt_001")
    qualify.add_argument("--qualification-attempt", default="checkpoint_qualification_attempt_001")
    execute = commands.add_parser("execute", help="Execute one plan in a fresh isolated Docker container")
    execute.add_argument("--plan", required=True, type=Path)
    execute.add_argument("--out", required=True, type=Path)
    direct = commands.add_parser("replay-tests", help="Replay explicit raw inputs and collect Step A in the same run")
    direct.add_argument("--case-id", required=True)
    direct.add_argument("--input-directory", required=True, type=Path)
    direct.add_argument("--out", required=True, type=Path)
    direct.add_argument("--base-commit", help="Full revision, required if task.toml records an abbreviation")
    args = parser.parse_args()
    if args.action == "replay-tests":
        from eviweave.collection import collect_tests
        from eviweave.replay import load_case
        case = load_case(args.case_id, args.input_directory, args.base_commit)
        result = collect_tests(case, args.input_directory, args.out)
        print(json.dumps({k: result.get(k) for k in ('status', 'state_validation_passed', 'step_a', 'error')},
                         ensure_ascii=False, indent=2))
        return 0 if result.get('state_validation_passed') is True else 2
    if args.action == "replay":
        result = replay_screen(args.screen_id, run=args.run, checkpoint_index=args.checkpoint_index, attempt=args.attempt,
                               collect_validation_tests=args.collect_validation_tests, fresh=args.fresh)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.action == "validate":
        result = validate_screen(args.screen_id, run=args.run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 2
    if args.action == "qualify-saved":
        result = qualify_saved_replay(args.screen_id, run=args.run, replay_attempt=args.replay_attempt,
                                     qualification_attempt=args.qualification_attempt)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 2
    path = args.plan.resolve(strict=True)
    result = execute_plan(json.loads(path.read_bytes()), args.out, base_directory=path.parent)
    print(json.dumps({key: result.get(key) for key in ("status", "target_executed", "failed_step", "error_type")}, ensure_ascii=False))
    # A target's nonzero rc remains data. Only runner/preparation errors fail the CLI.
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
