"""Resume a frozen prefix probe after a recoverable emission refusal.

The parent set, programs, order, stopping rule and native budget stay fixed.
Cached outcomes retain their original receipts. A refused emission consumes no
native execution and cannot become an alert. No provider call occurs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.candidate_edit_transport import verify_emission
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts import run_test_prefix_component as prefix
from scripts.run_contract_repair_search import execute, frozen, verify, write
from scripts.run_type_projection_component import emit

VERSION = 'frozen-prefix-probe-continuation.v1'


def validate_cached(outcome, entry):
    if outcome['program'] != entry['program'] or outcome['rank'] != entry['rank']:
        raise ValueError('Cached outcome belongs to a different frozen program')
    if outcome['is_original'] != entry['is_original']:
        raise ValueError('Cached fallback status differs')
    if outcome.get('detector_alert'):
        raise ValueError('A construction probe cannot import detector alerts')
    if outcome.get('native'):
        verify(outcome['native']['runs'])


def prepare(args):
    old = args.previous
    verify(read(old / 'seal.json'))
    p = read(old / 'prepared.json')
    admission.verify_seal(p['algorithm'])
    verify(p['go_binding_materializer'])
    cache = {}
    for item in p['items']:
        for receipt in item['source_inputs'].values():
            verify(receipt)
        for entry in item['programs']:
            verify(entry['program'])
            path = old / 'cases' / item['name'] / f"candidate_{entry['rank']:04d}" / 'outcome.json'
            if path.exists():
                validate_cached(read(path), entry)
                cache[f"{item['name']}:{entry['rank']}"] = frozen(path)
    args.output.mkdir(parents=True, exist_ok=False)
    admission._preload_local_imports(prefix)
    p.update(version=VERSION, previous_prepared=frozen(old / 'prepared.json'),
             algorithm=admission._loaded_sources(), cached_outcomes=cache,
             emission_refusal='record_and_continue_next_prefix',
             created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output / 'prepared.json', p)
    write(args.output / 'seal.json', frozen(args.output / 'prepared.json'))
    return dict(parents=len(p['items']), cached_outcomes=len(cache),
                prepared=frozen(args.output / 'prepared.json'))


def try_emit(candidate, source, directory, protocol):
    artifact = directory / 'emitted/group_000'
    if (artifact / 'manifest.json').exists():
        return artifact, None
    if not (artifact / 'emission.json').exists():
        try:
            return emit(candidate, source, directory, protocol), None
        except ValueError as exc:
            if str(exc) != 'Projection did not emit one program':
                raise
    reports = sorted((directory / 'emitted').glob('group_*/emission.json'))
    manifests = list((directory / 'emitted').glob('group_*/manifest.json'))
    refused = [row for path in reports for row in read(path).get('unsupported', [])]
    if manifests or not refused:
        raise ValueError('Emission failed without an explicit unsupported-program record')
    return None, dict(status='emission_refused', unsupported=refused,
                      reports=[frozen(path) for path in reports])


def run(args):
    root = args.input
    verify(read(root / 'seal.json'))
    p = read(root / 'prepared.json')
    verify(p['previous_prepared'])
    verify(p['go_binding_materializer'])
    admission.verify_seal(p['algorithm'])
    results = {i['name']: dict(name=i['name'], case=i['case'], parent=i['parent'],
                             attempts=[], first_failure=None, stop_reason=None) for i in p['items']}
    count = reused = emitted_refusals = 0
    deadline = datetime.fromisoformat(p['deadline_utc'].replace('Z', '+00:00'))
    for rank in range(max((len(i['programs']) for i in p['items']), default=0)):
        for item in p['items']:
            result = results[item['name']]
            if result['stop_reason'] or rank >= len(item['programs']):
                continue
            entry = item['programs'][rank]
            directory = root / 'cases' / item['name'] / f'candidate_{rank + 1:04d}'
            cached = p['cached_outcomes'].get(f"{item['name']}:{rank + 1}")
            if cached:
                verify(cached)
                outcome = read(cached['path'])
                validate_cached(outcome, entry)
                reused += int(outcome.get('native') is not None)
            elif (directory / 'outcome.json').exists():
                outcome = read(directory / 'outcome.json')
                validate_cached(outcome, entry)
            else:
                if count >= p['max_native_executions'] or (deadline - datetime.now(timezone.utc)).total_seconds() < p['timeout'] + 30:
                    result['stop_reason'] = 'execution_budget'
                    continue
                for receipt in item['source_inputs'].values():
                    verify(receipt)
                verify(entry['program'])
                candidate = read(entry['program']['path'])
                corpus = read(item['source_inputs']['corpus']['path'])
                artifact, refusal = try_emit(candidate, Path(item['source']), directory / 'native', p)
                transport = (verify_emission(corpus, candidate, artifact) if artifact else
                             dict(status='not_emitted', reason=refusal))
                write(directory / 'transport.json', transport)
                native = (execute(candidate, Path(item['source']), corpus, directory / 'native', p)
                          if transport['status'] == 'matched' else None)
                outcome = dict(rank=rank + 1, is_original=entry['is_original'], program=entry['program'],
                               native=native, transport=transport, semantic_validity='unconfirmed',
                               emission_refusal=refusal, detector_alert=False)
                write(directory / 'outcome.json', outcome)
            result['attempts'].append(outcome)
            if outcome.get('emission_refusal'):
                emitted_refusals += 1
            elif outcome['native'] is None:
                result['stop_reason'] = 'program_transport_mismatch'
            else:
                count += 1
                if outcome['native']['controlled_failure']:
                    result['first_failure'] = outcome
                    result['stop_reason'] = 'first_controlled_failure'
                elif outcome['native']['controls']['status'] != 'all_source_controls_passed':
                    result['stop_reason'] = 'source_control_unavailable_or_failed'
            write(root / 'cases' / item['name'] / 'result.json', result)
            print(json.dumps(dict(case=item['case'], parent=item['name'], rank=rank + 1,
                                  controlled_failure=bool(result['first_failure']),
                                  stop_reason=result['stop_reason'], native_executions=count,
                                  reused_native_executions=reused, emission_refusals=emitted_refusals)), flush=True)
    admission.verify_seal(p['algorithm'])
    summary = dict(version=VERSION, results=list(results.values()), external_model_calls=0,
                   native_executions=count, reused_native_executions=reused,
                   new_native_executions=count - reused, emission_refusals=emitted_refusals,
                   detector_alerts=0, completed_utc=datetime.now(timezone.utc).isoformat())
    write(root / 'summary.json', summary)
    return {key: value for key, value in summary.items() if key != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
