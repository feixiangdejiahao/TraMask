"""Prepare scalar-predicate hypotheses, then independently review and test.

The sealed table-search harness supplies ordering, receipts and execution.
Each function receives a private globals namespace. No shared module is edited.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import sql_predicate_clamp as relation
from relation_search import sql_predicate_clamp_review as review
from relation_search import csi_repair_transport
from relational_gap.provider import dispatch
from scripts import run_table_column_rotation_search as harness
from scripts.run_contract_repair_search import execute, write
from scripts.resume_test_prefix_probe import try_emit

VERSION = 'controlled-sql-predicate-clamp-search.v1'


def one_run(candidate, source, corpus, directory, protocol):
    artifact, refusal = try_emit(candidate, source, directory/'native', protocol)
    transport = (csi_repair_transport.verify(corpus, candidate, artifact) if artifact else
                 dict(status='not_emitted', reason=refusal))
    native = (execute(candidate, source, corpus, directory/'native', protocol)
              if transport['status'] == 'matched' else None)
    outcome = dict(transport=transport, native=native, emission_refusal=refusal)
    write(directory/'outcome.json', outcome)
    return outcome


def _engine():
    namespace = dict(vars(harness))
    overrides = dict(__name__=__name__, __file__=__file__, VERSION=VERSION,
                     relation=relation, review=review, dispatch=dispatch, one_run=one_run)
    namespace.update(overrides)
    for name, function in vars(harness).items():
        if name not in overrides and isinstance(function, FunctionType) and function.__module__ == harness.__name__:
            copied = FunctionType(function.__code__, namespace, name, function.__defaults__, function.__closure__)
            copied.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = copied
    return namespace


def collect(args, *, freeze):
    return _engine()['collect'](args, freeze=freeze)


def review_all(args):
    return _engine()['review_all'](args)


def run(args):
    return _engine()['run'](args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['census', 'prepare', 'review', 'run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--deadline-utc')
    args = parser.parse_args()
    if args.stage == 'prepare' and not args.deadline_utc:
        parser.error('--deadline-utc is required for prepare')
    if args.stage in {'prepare', 'census'} and (args.source_cohort is None or args.output is None):
        parser.error('--source-cohort and --output are required for source preparation')
    if args.stage in {'review', 'run'} and args.input is None:
        parser.error('--input is required for review or run')
    result = (run(args) if args.stage == 'run' else review_all(args) if args.stage == 'review'
              else collect(args, freeze=args.stage == 'prepare'))
    print(json.dumps(result))
