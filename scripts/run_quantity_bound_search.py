"""Prepare and run source-only quantity-bound hypotheses on a sealed cohort.

Discovery is a separate stage. --relations-dir contains one <case>.json IR per
trial. Missing records remain explicit misses. This runner never calls a model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import quantity_bound as relation
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import frozen, verify, write
from scripts.run_documented_default_search import one_run

VERSION = 'controlled-quantity-bound-search.v1'


def prepare(args):
    verify(read(args.source_cohort/'seal.json'))
    previous = read(args.source_cohort/'prepared.json')
    sources = {}
    for row in previous.get('items', previous.get('cases', [])):
        old = sources.setdefault(row['case'], row['source'])
        if old != row['source']:
            raise ValueError('one_source_per_trial_required')
    if not sources:
        raise ValueError('empty_source_cohort')
    args.output.mkdir(parents=True, exist_ok=False)
    admission._preload_local_imports(relation)
    algorithm = admission._loaded_sources()
    cases = []
    for case, path in sorted(sources.items()):
        source = Path(path)
        inputs = {name: frozen(source/name) for name in
                  ['corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md']}
        relation_file = args.relations_dir/(case+'.json')
        if relation_file.exists():
            inputs['relation_ir'] = frozen(relation_file)
            ir = read(relation_file)
        else:
            ir = dict(version=relation.IR_VERSION, relations=[])
        generated = relation.generate(read(source/'corpus.json'), read(source/'frontend.json'),
                                      (source/'issue.md').read_text(), ir, limit=args.limit)
        if not relation_file.exists():
            generated['status'] = 'relation_discovery_missing'
        candidates = generated.pop('candidates')
        directory = args.output/'cases'/case
        write(directory/'generation.json', generated)
        entries = []
        for rank, candidate in enumerate(candidates, 1):
            target = directory/f'candidate_{rank:04d}'/'program.json'
            write(target, candidate)
            entries.append(dict(rank=rank, program=frozen(target)))
        cases.append(dict(case=case, source=str(source.resolve()), inputs=inputs,
                          generation=frozen(directory/'generation.json'), candidates=entries,
                          status=generated['status']))
        print(json.dumps(dict(case=case, selected=len(entries), status=generated['status'],
                              rejected_relations=len(generated['rejected']))), flush=True)
    admission.verify_seal(algorithm)
    if set(admission._loaded_sources()) - set(algorithm):
        raise ValueError('unsealed_local_import')
    protocol = dict(version=VERSION, algorithm=algorithm, policy=relation.POLICY, cases=cases,
        source_cohort=frozen(args.source_cohort/'prepared.json'),
        source_cohort_use='Trial list and original source paths only; no candidates or outcomes.',
        trial_denominator=len(cases), max_candidates_per_trial=args.limit,
        max_native_executions=(args.limit+1)*len(cases), timeout=180,
        deadline_utc=args.deadline_utc, external_model_calls=0, evaluator_labels_used=False,
        ordering='sorted trials; source package/test order, supplied relation order, options configuration order',
        stop='first controlled failure and one repeat; no replacement after independent audit',
        alert='Repeated failure is a contract hypothesis pending independent full-test audit.',
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output/'prepared.json', protocol)
    write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(trials=len(cases), selected=sum(len(row['candidates']) for row in cases), prepared=frozen(args.output/'prepared.json'))


def run(args):
    root = args.input
    verify(read(root/'seal.json'))
    protocol = read(root/'prepared.json')
    admission.verify_seal(protocol['algorithm'])
    if (root/'summary.json').exists():
        return read(root/'summary.json')
    deadline = datetime.fromisoformat(protocol['deadline_utc'].replace('Z', '+00:00'))
    def enough_time():
        used = len(list((root/'cases').glob('*/candidate_*/**/native_outcome.json')))
        return used < protocol['max_native_executions'] and (deadline-datetime.now(timezone.utc)).total_seconds() > protocol['timeout']+30
    results = []
    for case in protocol['cases']:
        directory = root/'cases'/case['case']
        for item in [*case['inputs'].values(), case['generation']]:
            verify(item)
        if (directory/'result.json').exists():
            results.append(read(directory/'result.json'))
            continue
        source = Path(case['source']); corpus = read(source/'corpus.json')
        result = dict(case=case['case'], attempts=[], alert=None, stop_reason=case['status'])
        for entry in case['candidates']:
            verify(entry['program'])
            if not enough_time():
                result['stop_reason'] = 'execution_budget'; break
            target = directory/f"candidate_{entry['rank']:04d}"
            candidate = read(entry['program']['path'])
            initial = one_run(candidate, source, corpus, target/'initial', protocol)
            attempt = dict(rank=entry['rank'], program=entry['program'], initial=initial)
            result['attempts'].append(attempt)
            native = initial.get('native')
            if native is None:
                result['stop_reason'] = 'emission_or_transport_unavailable'; continue
            if native['controls']['status'] != 'all_source_controls_passed':
                result['stop_reason'] = 'source_control_unavailable_or_failed'; break
            if native['controlled_failure']:
                result['stop_reason'] = 'first_failure_unconfirmed'
                if enough_time():
                    repeat = one_run(candidate, source, corpus, target/'confirmation', protocol)
                    attempt['confirmation'] = repeat
                    if (repeat.get('native') or {}).get('controlled_failure'):
                        result['alert'] = dict(program=entry['program'], initial=frozen(target/'initial/outcome.json'),
                            confirmation=frozen(target/'confirmation/outcome.json'),
                            validity='pending_independent_full_test_audit')
                        result['stop_reason'] = 'repeated_quantity_bound_failure'
                break
            result['stop_reason'] = 'candidate_budget_exhausted'
        write(directory/'result.json', result); results.append(result)
        print(json.dumps(dict(case=case['case'], attempts=len(result['attempts']), alert=bool(result['alert']),
                              stop=result['stop_reason'])), flush=True)
    admission.verify_seal(protocol['algorithm'])
    summary = dict(version=VERSION, results=results, trial_denominator=protocol['trial_denominator'],
        native_executions=len(list((root/'cases').glob('*/candidate_*/**/native_outcome.json'))),
        external_model_calls=0, detector_alerts=sum(bool(row['alert']) for row in results),
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json', summary)
    return {key: value for key, value in summary.items() if key != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['schema', 'prepare', 'run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--relations-dir', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--deadline-utc')
    parser.add_argument('--limit', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.limit <= 16:
        parser.error('--limit must be between 1 and 16')
    print(json.dumps(relation.IR_SCHEMA if args.stage == 'schema' else prepare(args) if args.stage == 'prepare' else run(args), indent=2))
