"""PYTHONPATH=src python -m eviweave.replay --help"""
import argparse
import json
from pathlib import Path

from . import load_case, replay_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--input-directory', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--base-commit')
    args = parser.parse_args()
    case = load_case(args.case_id, args.input_directory, args.base_commit)
    result = replay_case(case, args.input_directory, args.out)
    print(json.dumps({key: result[key] for key in ('status', 'actions_executed', 'state_validation_passed', 'checkpoint')}, indent=2))
    return 0 if result['state_validation_passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
