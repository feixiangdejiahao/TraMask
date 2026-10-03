"""Apply a frozen source-only codec guard to every fixed first-stage alert."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import codec_boundary_guard as guard
from relation_search.checkpoint import read
from scripts import replay_uniform_second_gate as baseline
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import frozen, verify, write

VERSION = 'codec-guarded-exact-semantic-replay.v2'


def prepare(args):
    verify(read(args.source/'seal.json'))
    source = read(args.source/'prepared.json')
    if source['version'] != baseline.VERSION:
        raise ValueError('Require the exact first-alert semantic replay protocol')
    args.output.mkdir(parents=True, exist_ok=False)
    admission._preload_local_imports(guard)
    algorithm = admission._loaded_sources()
    entries = []
    for item in source['items']:
        verify(item['first_request'])
        request = read(item['first_request']['path'])
        payload = json.loads(request['prompt'])
        result = guard.analyze(payload)
        path = args.output/'checks'/item['case']/'guard.json'
        write(path, result)
        entries.append(dict(case=item['case'], candidate_id=item['candidate_id'],
                            request=item['first_request'], guard=frozen(path)))
    write(args.output/'semantic/prepared.json', source)
    write(args.output/'semantic/seal.json', frozen(args.output/'semantic/prepared.json'))
    admission.verify_seal(algorithm)
    if set(admission._loaded_sources()) - set(algorithm):
        raise ValueError('Unsealed local source imported')
    protocol = dict(version=VERSION, cases=source['cases'], items=entries,
        source=frozen(args.source/'prepared.json'), semantic=frozen(args.output/'semantic/prepared.json'),
        algorithm=algorithm, policy=guard.POLICY, authorities=guard.AUTHORITIES,
        selection='Every fixed first-stage output receives the same guard. A withheld candidate is never replaced.',
        preparation_reads='Source protocol and original complete requests only; no output summary, label, native result or model rationale.',
        fresh_provider_calls=0, new_native_executions=0, retrospective=True, labels_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output/'prepared.json', protocol)
    write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(trials=len(source['cases']), checked=len(entries), prepared=frozen(args.output/'prepared.json'))


def run(args):
    root = args.input
    verify(read(root/'seal.json'))
    p = read(root/'prepared.json')
    admission.verify_seal(p['algorithm'])
    verify(p['source'])
    verify(p['semantic'])
    if (root/'summary.json').exists():
        return read(root/'summary.json')
    # A chain copies only our prepared protocol. Restore its exact frozen inner
    # replay protocol in the new execution root before running the component.
    write(root/'semantic/prepared.json', read(p['semantic']['path']))
    write(root/'semantic/seal.json', frozen(root/'semantic/prepared.json'))
    if not (root/'semantic/summary.json').exists():
        baseline.run(SimpleNamespace(input=root/'semantic'))
    old = read(root/'semantic/summary.json')
    guards = {}
    for entry in p['items']:
        verify(entry['request'])
        verify(entry['guard'])
        guards[entry['case'], entry['candidate_id']] = read(entry['guard']['path'])
    decisions = []
    for row in old['decisions']:
        check = guards[row['case'], row['candidate_id']]
        if check['allow_prior_gate']:
            result = dict(row, codec_guard=check)
        else:
            result = dict(row, codec_guard=check, prior_decision=row['decision'],
                decision=dict(status='unknown_codec_or_input_boundary', alarm_eligible=False,
                              reason=check['status'], withheld_not_invalid=True))
        decisions.append(result)
        write(root/'cases'/row['case']/'decision.json', result)
    summary = {key: old[key] for key in ['denominator', 'compatible_cached_reviews',
        'compatible_cached_review_tokens', 'first_stage_calls', 'first_stage_tokens',
        'entire_second_gate_experiment_cost']}
    summary.update(version=VERSION, decisions=decisions,
        alerts=[row for row in decisions if row['decision'].get('alarm_eligible')],
        source_summary=frozen(root/'semantic/summary.json'), new_native_executions=0,
        fresh_provider_calls=0, retrospective=True, independent_audit_complete=False,
        completed_utc=datetime.now(timezone.utc).isoformat())
    admission.verify_seal(p['algorithm'])
    write(root/'summary.json', summary)
    return dict(denominator=summary['denominator'], alerts=len(summary['alerts']),
                guarded_candidates=sum(not check['allow_prior_gate'] for check in guards.values()),
                fresh_provider_calls=0, new_native_executions=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
