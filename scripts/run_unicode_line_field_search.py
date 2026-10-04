"""Prepare source string refinements, review whole tests, then run admitted tests.

This private adapter reuses the sealed R12 review/native harness. It never
changes that module's globals. Construction uses original repository inputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import unicode_line_field as relation
from relation_search import unicode_line_field_review as review
from relation_search import csi_repair_transport
from relational_gap.provider import dispatch
from scripts import run_table_column_rotation_search as harness
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import execute, frozen, write
from scripts.resume_test_prefix_probe import try_emit

VERSION = 'controlled-unicode-line-field-search.v1'


def one_run(candidate, source, corpus, directory, protocol):
    artifact, refusal = try_emit(candidate, source, directory/'native', protocol)
    transport = (csi_repair_transport.verify(corpus, candidate, artifact) if artifact else
                 dict(status='not_emitted', reason=refusal))
    native = (execute(candidate, source, corpus, directory/'native', protocol)
              if transport['status'] == 'matched' else None)
    outcome = dict(transport=transport, native=native, emission_refusal=refusal)
    write(directory/'outcome.json', outcome)
    return outcome


def _verify_protocol(protocol):
    if protocol.get('version') != VERSION or protocol.get('policy') != relation.POLICY:
        raise ValueError('Unsupported Unicode field protocol')
    names = [case['case'] for case in protocol['cases']]
    if names != sorted(set(names)) or len(names) != protocol['trial_denominator']:
        raise ValueError('Protocol cohort order or denominator differs')
    if protocol['max_candidates_per_trial'] != 16:
        raise ValueError('Unexpected per-trial candidate budget')
    for case in protocol['cases']:
        entries = case['candidates']
        if len(entries) > 16 or [e['rank'] for e in entries] != list(range(1, len(entries)+1)):
            raise ValueError('Candidate ranks are not a complete source prefix')
        if [e['order'] for e in entries] != sorted(e['order'] for e in entries):
            raise ValueError('Frozen candidate order differs')
    if protocol['semantic_policy']['method'] != review.VERSION:
        raise ValueError('Wrong complete-test reviewer')


def _engine():
    namespace = dict(vars(harness))
    overrides = dict(__name__=__name__, __file__=__file__, VERSION=VERSION,
                     relation=relation, review=review, dispatch=dispatch,
                     one_run=one_run, _verify_protocol=_verify_protocol)
    namespace.update(overrides)
    for name, function in vars(harness).items():
        if name not in overrides and isinstance(function, FunctionType) and function.__module__ == harness.__name__:
            bound = FunctionType(function.__code__, namespace, name, function.__defaults__, function.__closure__)
            bound.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = bound
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
    required = ('source_cohort', 'output') if args.stage in {'census', 'prepare'} else ('input',)
    if args.stage == 'prepare':
        required += ('deadline_utc',)
    if any(getattr(args, key) is None for key in required):
        parser.error('Missing arguments: '+', '.join('--'+key.replace('_', '-') for key in required))
    result = (review_all(args) if args.stage == 'review' else run(args) if args.stage == 'run'
              else collect(args, freeze=args.stage == 'prepare'))
    print(json.dumps(result))
