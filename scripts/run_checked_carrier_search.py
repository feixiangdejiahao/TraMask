"""Run source-derived guest/host inverse edits after a scalar adapter probe."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import checked_carrier_inverse as relation
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import frozen, verify, write
from scripts.run_documented_default_search import one_run

VERSION = 'controlled-guest-carrier-inverse-search.v1'


def prepare(args):
    verify(read(args.source_cohort/'seal.json'))
    previous = read(args.source_cohort/'prepared.json')
    sources = {}
    for row in previous['items']:
        old = sources.setdefault(row['case'], row['source'])
        if old != row['source']:
            raise ValueError('One frozen source per trial is required')
    args.output.mkdir(parents=True, exist_ok=False)
    admission._preload_local_imports(relation)
    algorithm = admission._loaded_sources()
    cases = []
    for case, source_name in sorted(sources.items()):
        source = Path(source_name)
        inputs = {name: frozen(source/name) for name in
                  ['corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md']}
        generated = relation.generate(read(source/'corpus.json'), read(source/'frontend.json'),
                                      (source/'issue.md').read_text(), limit=16)
        pairs = generated.pop('pairs')
        generated.pop('candidates', None)
        directory = args.output/'cases'/case
        write(directory/'generation.json', generated)
        entries = []
        for rank, pair in enumerate(pairs, 1):
            target = directory/f'candidate_{rank:04d}'
            write(target/'program.json', pair['candidate'])
            write(target/'probe.json', pair['probe'])
            entries.append(dict(rank=rank, program=frozen(target/'program.json'),
                                probe=frozen(target/'probe.json'), order=pair['order']))
        cases.append(dict(case=case, source=str(source.resolve()), inputs=inputs,
                          generation=frozen(directory/'generation.json'),
                          candidates=entries, status=generated['status']))
        print(json.dumps(dict(case=case, status=generated['status'], selected=len(entries),
            generated=generated.get('total_candidates', 0), rejected=len(generated.get('skipped', [])))), flush=True)
    admission.verify_seal(algorithm)
    if set(admission._loaded_sources()) - set(algorithm):
        raise ValueError('Unsealed local source imported')
    protocol = dict(version=VERSION, algorithm=algorithm, policy=relation.POLICY,
        cases=cases, trial_denominator=len(cases), source_cohort=frozen(args.source_cohort/'prepared.json'),
        source_cohort_use='Only trial list and original source snapshot paths. No old candidates or outcomes.',
        max_candidates_per_trial=16, max_native_executions=33*len(cases), timeout=180,
        deadline_utc=args.deadline_utc, ordering='sorted trials, fixed source candidate rank',
        stop='First controlled candidate failure stops a trial even when its repeat does not confirm. A failed scalar probe is an unproven precondition, never a defect alert.',
        alert='Explicit contract, checked inverse, passing scalar probe, exact test transport, all source controls pass, same complete candidate fails twice.',
        external_model_calls=0, evaluator_labels_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output/'prepared.json', protocol)
    write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(trials=len(cases), selected=sum(len(row['candidates']) for row in cases),
                prepared=frozen(args.output/'prepared.json'))


def passed(outcome):
    native = outcome.get('native') or {}
    return (outcome.get('transport', {}).get('status') == 'matched'
            and native.get('controls', {}).get('status') == 'all_source_controls_passed'
            and bool(native.get('tests')) and not native.get('parser_errors')
            and all(test['status'] == 'pass' for test in native['tests']))


def run(args):
    root = args.input
    verify(read(root/'seal.json'))
    p = read(root/'prepared.json')
    admission.verify_seal(p['algorithm'])
    if (root/'summary.json').exists():
        return read(root/'summary.json')
    deadline = datetime.fromisoformat(p['deadline_utc'].replace('Z', '+00:00'))
    def enough_time():
        return (len(list((root/'cases').glob('*/candidate_*/**/native_outcome.json'))) < p['max_native_executions']
                and (deadline-datetime.now(timezone.utc)).total_seconds() > p['timeout']+30)
    results = []
    for case in p['cases']:
        directory = root/'cases'/case['case']
        if (directory/'result.json').exists():
            results.append(read(directory/'result.json'))
            continue
        for receipt in [*case['inputs'].values(), case['generation']]:
            verify(receipt)
        source = Path(case['source'])
        corpus = read(source/'corpus.json')
        result = dict(case=case['case'], attempts=[], alert=None, stop_reason=case['status'])
        for entry in case['candidates']:
            for receipt in [entry['program'], entry['probe']]:
                verify(receipt)
            if not enough_time():
                result['stop_reason'] = 'execution_budget'
                break
            candidate_dir = directory/f"candidate_{entry['rank']:04d}"
            probe = one_run(read(entry['probe']['path']), source, corpus, candidate_dir/'probe', p)
            attempt = dict(rank=entry['rank'], program=entry['program'], probe_program=entry['probe'], probe=probe)
            result['attempts'].append(attempt)
            if probe.get('native') and probe['native']['controls']['status'] != 'all_source_controls_passed':
                result['stop_reason'] = 'source_control_unavailable_or_failed'
                break
            if not passed(probe):
                attempt['candidate_status'] = 'adapter_precondition_unproven'
                result['stop_reason'] = 'adapter_precondition_unproven'
                continue
            if not enough_time():
                result['stop_reason'] = 'execution_budget'
                break
            candidate = read(entry['program']['path'])
            outcome = one_run(candidate, source, corpus, candidate_dir/'initial', p)
            attempt['initial'] = outcome
            native = outcome['native']
            if native is None:
                result['stop_reason'] = 'emission_or_transport_unavailable'
                continue
            if native['controls']['status'] != 'all_source_controls_passed':
                result['stop_reason'] = 'source_control_unavailable_or_failed'
                break
            if native['controlled_failure']:
                result['stop_reason'] = 'first_failure_unconfirmed'
                if enough_time():
                    confirmation = one_run(candidate, source, corpus, candidate_dir/'confirmation', p)
                    attempt['confirmation'] = confirmation
                    if (confirmation.get('native') or {}).get('controlled_failure'):
                        result['alert'] = dict(program=entry['program'], probe_program=entry['probe'],
                            probe=frozen(candidate_dir/'probe/outcome.json'),
                            initial=frozen(candidate_dir/'initial/outcome.json'),
                            confirmation=frozen(candidate_dir/'confirmation/outcome.json'),
                            validity='pending_independent_full_test_audit')
                        result['stop_reason'] = 'repeated_checked_carrier_failure'
                break
            result['stop_reason'] = 'candidate_budget_exhausted'
        write(directory/'result.json', result)
        results.append(result)
        print(json.dumps(dict(case=case['case'], attempts=len(result['attempts']),
                              alert=bool(result['alert']), stop=result['stop_reason'])), flush=True)
    admission.verify_seal(p['algorithm'])
    summary = dict(version=VERSION, results=results, trial_denominator=p['trial_denominator'],
        native_executions=len(list((root/'cases').glob('*/candidate_*/**/native_outcome.json'))),
        external_model_calls=0, detector_alerts=sum(bool(row['alert']) for row in results),
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json', summary)
    return {key: value for key, value in summary.items() if key != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--deadline-utc')
    args = parser.parse_args()
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
