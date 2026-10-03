"""Run one frozen documentation-first policy with an exact cached fallback.

The documentation branch executes its fixed source-generated programs afresh.
The fallback replays the complete pre-existing detector's first-alert cohort.
Neither branch reads evaluator labels or chooses a replacement after audit.
The result is a retrospective hybrid, never a fresh end-to-end model run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import read
from scripts import run_documented_default_search as defaults
from scripts import replay_uniform_second_gate as semantic
from scripts.run_contract_repair_search import frozen, verify, write

VERSION = 'documentation-first-exact-semantic-fallback.v1'


def prepare(args):
    for source in [args.defaults, args.fallback]:
        verify(read(source / 'seal.json'))
    documentary = read(args.defaults / 'prepared.json')
    fallback = read(args.fallback / 'prepared.json')
    if documentary['version'] != defaults.VERSION or fallback['version'] != semantic.VERSION:
        raise ValueError('Unexpected component protocol')
    if sorted(row['case'] for row in documentary['cases']) != sorted(fallback['cases']):
        raise ValueError('Both branches must retain the same trial denominator')
    args.output.mkdir(parents=True, exist_ok=False)
    for name, protocol in [('documentation', documentary), ('semantic', fallback)]:
        path = args.output / name / 'prepared.json'
        write(path, protocol)
        write(path.parent / 'seal.json', frozen(path))
    p = dict(version=VERSION,
        algorithm=[frozen(Path(__file__)), frozen(Path(defaults.__file__)), frozen(Path(semantic.__file__))],
        documentary_source=frozen(args.defaults / 'prepared.json'),
        semantic_source=frozen(args.fallback / 'prepared.json'),
        documentary_prepared=frozen(args.output / 'documentation/prepared.json'),
        semantic_prepared=frozen(args.output / 'semantic/prepared.json'),
        cases=sorted(fallback['cases']),
        decision='For each trial, use its repeated documentation-relation failure if emitted. Otherwise use its exact-payload second-gate decision. Never inspect truth or replace a rejected first semantic alert.',
        branch_selection='Same precedence for every trial. No known-positive IDs, task rules, ranking labels or output summaries are read during preparation.',
        documentary_execution='Fresh native source controls and generated tests; no round28 outcome reuse.',
        semantic_execution='Retrospective replay of fixed first-stage outputs and exact cached high-reasoning requests.',
        labels_used=False, external_model_calls=0, retrospective=True,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output / 'prepared.json', p)
    write(args.output / 'seal.json', frozen(args.output / 'prepared.json'))
    return dict(trials=len(p['cases']), prepared=frozen(args.output / 'prepared.json'))


def run(args):
    root = args.input
    verify(read(root / 'seal.json'))
    p = read(root / 'prepared.json')
    for row in p['algorithm']:
        verify(row)
    for key in ['documentary_source', 'semantic_source', 'documentary_prepared', 'semantic_prepared']:
        verify(p[key])
    for name, runner in [('documentation', defaults), ('semantic', semantic)]:
        if not (root / name / 'summary.json').exists():
            runner.run(SimpleNamespace(input=root / name))
    documentary = read(root / 'documentation/summary.json')
    fallback = read(root / 'semantic/summary.json')
    docs = {row['case']: row for row in documentary['results']}
    semantics = {row['case']: row for row in fallback['decisions']}
    outputs, decisions = [], []
    for case in p['cases']:
        if docs[case]['alert']:
            row = dict(case=case, branch='documented_default', alert=docs[case]['alert'])
        elif semantics.get(case, {}).get('decision', {}).get('alarm_eligible'):
            row = dict(case=case, branch='exact_semantic_fallback', alert=semantics[case])
        else:
            row = dict(case=case, branch='abstain', alert=None)
        decisions.append(row)
        if row['alert']:
            outputs.append(row)
    result = dict(version=VERSION, denominator=len(p['cases']), decisions=decisions, alerts=outputs,
        documentary_summary=frozen(root / 'documentation/summary.json'),
        semantic_summary=frozen(root / 'semantic/summary.json'),
        fresh_native_executions=documentary['native_executions'], fresh_provider_calls=0,
        semantic_historical_cost={key: fallback[key] for key in
            ['first_stage_calls', 'first_stage_tokens', 'entire_second_gate_experiment_cost',
             'compatible_cached_reviews', 'compatible_cached_review_tokens']},
        retrospective=True, independent_audit_complete=False,
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root / 'summary.json', result)
    return dict(alerts=len(outputs), denominator=result['denominator'],
                fresh_native_executions=result['fresh_native_executions'], fresh_provider_calls=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--defaults', type=Path)
    parser.add_argument('--fallback', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
