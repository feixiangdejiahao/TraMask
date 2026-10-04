"""Generate and evaluate one uniform source declaration-order relation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import guest_declaration_order as relation
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import frozen, verify, write
from scripts.run_documented_default_search import one_run

VERSION = 'controlled-guest-declaration-order-search.v1'


def collect(args, *, freeze):
    verify(read(args.source_cohort/'seal.json'))
    previous = read(args.source_cohort/'prepared.json')
    sources = {}
    for row in previous.get('items', previous.get('cases', [])):
        if sources.setdefault(row['case'], row['source']) != row['source']:
            raise ValueError('One original source snapshot per trial is required')
    if not sources:
        raise ValueError('Empty source cohort')
    args.output.mkdir(parents=True, exist_ok=False)
    admission._preload_local_imports(relation)
    algorithm = admission._loaded_sources()
    cases = []
    for case, name in sorted(sources.items()):
        source = Path(name)
        inputs = {item: frozen(source/item) for item in
                  ['corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md']}
        generated = relation.generate(read(source/'corpus.json'), read(source/'frontend.json'),
                                      (source/'issue.md').read_text(), limit=16)
        programs = generated.pop('candidates')
        directory = args.output/'cases'/case
        entries = []
        for rank, candidate in enumerate(programs, 1):
            path = directory/f'candidate_{rank:04d}'/'program.json'
            write(path, candidate)
            entries.append(dict(rank=rank, program=frozen(path), order=candidate['order']))
        write(directory/'generation.json', generated)
        cases.append(dict(case=case, source=str(source.resolve()), inputs=inputs,
                          generation=frozen(directory/'generation.json'), candidates=entries,
                          status=generated['status']))
        print(json.dumps(dict(case=case, selected=len(entries), total=generated['total_candidates'],
                              status=generated['status'], rejected=len(generated['skipped']))), flush=True)
    admission.verify_seal(algorithm)
    if set(admission._loaded_sources())-set(algorithm):
        raise ValueError('Unrecorded local source imported')
    record = dict(version=VERSION, policy=relation.POLICY, algorithm=algorithm,
        cases=cases, trial_denominator=len(cases), source_cohort=frozen(args.source_cohort/'prepared.json'),
        source_cohort_use='Only original snapshot paths and the full trial list; no old candidates or outcomes.',
        max_candidates_per_trial=16, external_model_calls=0, evaluator_labels_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    if freeze:
        record.update(max_native_executions=17*len(cases), timeout=180, deadline_utc=args.deadline_utc,
            ordering=relation.POLICY['ordering'],
            stop='First controlled failure, then one repeat; stop even if the repeat does not confirm.',
            alert=relation.POLICY['alert'])
        write(args.output/'prepared.json', record)
        write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    else:
        record.update(stage='source_census_only_not_a_native_execution_protocol', native_executions=0,
                      total_candidates=sum(len(row['candidates']) for row in cases))
        write(args.output/'census.json', record)
    return dict(trials=len(cases), selected=sum(len(row['candidates']) for row in cases),
                record=frozen(args.output/('prepared.json' if freeze else 'census.json')))


def _controlled(outcome):
    native = outcome.get('native') or {}
    return (outcome.get('transport', {}).get('status') == 'matched'
            and native.get('controls', {}).get('status') == 'all_source_controls_passed'
            and native.get('controlled_failure') is True)


def run(args):
    root = args.input
    verify(read(root/'seal.json'))
    protocol = read(root/'prepared.json')
    admission.verify_seal(protocol['algorithm'])
    if (root/'summary.json').exists():
        return read(root/'summary.json')
    deadline = datetime.fromisoformat(protocol['deadline_utc'].replace('Z', '+00:00'))
    def enough_time():
        return (len(list((root/'cases').glob('*/candidate_*/**/native_outcome.json'))) < protocol['max_native_executions']
                and (deadline-datetime.now(timezone.utc)).total_seconds() > protocol['timeout']+30)
    results = []
    for case in protocol['cases']:
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
            verify(entry['program'])
            if not enough_time():
                result['stop_reason'] = 'execution_budget'
                break
            candidate = read(entry['program']['path'])
            candidate_dir = directory/f"candidate_{entry['rank']:04d}"
            outcome = one_run(candidate, source, corpus, candidate_dir/'initial', protocol)
            attempt = dict(rank=entry['rank'], program=entry['program'], initial=outcome)
            result['attempts'].append(attempt)
            native = outcome.get('native')
            if native is None:
                result['stop_reason'] = 'emission_or_transport_unavailable'
                continue
            if native.get('controls', {}).get('status') != 'all_source_controls_passed':
                result['stop_reason'] = 'source_control_unavailable_or_failed'
                break
            if _controlled(outcome):
                result['stop_reason'] = 'first_failure_unconfirmed'
                if enough_time():
                    confirmation = one_run(candidate, source, corpus, candidate_dir/'confirmation', protocol)
                    attempt['confirmation'] = confirmation
                    if _controlled(confirmation):
                        result['alert'] = dict(program=entry['program'],
                            initial=frozen(candidate_dir/'initial/outcome.json'),
                            confirmation=frozen(candidate_dir/'confirmation/outcome.json'),
                            validity='pending_independent_full_test_audit')
                        result['stop_reason'] = 'repeated_declaration_order_failure'
                break
            result['stop_reason'] = 'candidate_budget_exhausted'
        write(directory/'result.json', result)
        results.append(result)
        print(json.dumps(dict(case=case['case'], attempts=len(result['attempts']),
                              alert=bool(result['alert']), stop=result['stop_reason'])), flush=True)
    admission.verify_seal(protocol['algorithm'])
    summary = dict(version=VERSION, results=results, trial_denominator=protocol['trial_denominator'],
        native_executions=len(list((root/'cases').glob('*/candidate_*/**/native_outcome.json'))),
        external_model_calls=0, detector_alerts=sum(bool(row['alert']) for row in results),
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json', summary)
    return {key:value for key,value in summary.items() if key != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['census', 'prepare', 'run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--deadline-utc')
    args = parser.parse_args()
    if args.stage == 'prepare' and not args.deadline_utc:
        parser.error('--deadline-utc is required for prepare')
    print(json.dumps(run(args) if args.stage == 'run' else collect(args, freeze=args.stage == 'prepare')))
