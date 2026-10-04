"""Compare low reasoning with the sealed high-reasoning declaration planner.

Only the planning request's reasoning effort changes. Generation, source
selection, whole-entry budgets, fallback, admission and execution stay intact.
The previous high-reasoning responses are never inputs to this driver.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import FunctionType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_planned_contract_gap_generation_search as original

PLANNING_VERSION = 'controlled-low-reasoning-declaration-planning.v1'
VERSION = 'controlled-low-planned-contract-gap-generation.v1'
PLANNING_POLICY = dict(original.PLANNING_POLICY, reasoning_effort='low')


def planning_prepare(corpus, inherited, **kwargs):
    prepared = original.planning.prepare(corpus, inherited, **kwargs)
    request = prepared.get('request')
    if request is not None:
        request['reasoning_effort'] = 'low'
        request['id'] = request['query_sha256'] = original.planning.core._identity(request)
    return prepared


def engine():
    planner = SimpleNamespace(**vars(original.planning))
    planner.prepare = planning_prepare
    # This entrypoint implements the sole request change; the original planner
    # remains in the separately verified loaded source closure.
    planner.__file__ = __file__
    namespace = dict(vars(original), __name__=__name__, __file__=__file__,
        VERSION=VERSION, PLANNING_VERSION=PLANNING_VERSION,
        PLANNING_POLICY=PLANNING_POLICY, planning=planner)
    for name, function in vars(original).items():
        if isinstance(function, FunctionType) and function.__module__ == original.__name__:
            copied = FunctionType(function.__code__, namespace, name,
                function.__defaults__, function.__closure__)
            copied.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = copied
    return namespace


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'plan', 'prepare-generation',
        'generate', 'review', 'run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--deadline-utc')
    args = parser.parse_args()
    if args.stage == 'prepare' and not all((args.source_cohort, args.output, args.deadline_utc)):
        parser.error('prepare requires --source-cohort, --output and --deadline-utc')
    if args.stage != 'prepare' and args.input is None:
        parser.error('--input is required')
    if args.stage == 'prepare-generation' and args.output is None:
        parser.error('prepare-generation requires --output')
    functions = engine()
    name = {'prepare-generation': 'prepare_generation', 'review': 'review_all'}.get(args.stage, args.stage)
    result = functions[name](args)
    print(json.dumps({k:v for k,v in result.items() if k != 'results'}))
