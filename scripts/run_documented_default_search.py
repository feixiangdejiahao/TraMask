"""Freeze and execute documentation-constrained default omission uniformly."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import documented_defaults
from relation_search.candidate_edit_transport import verify_emission
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import execute, frozen, verify, write
from scripts.resume_test_prefix_probe import try_emit

VERSION = 'documented-default-search.v1'
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024


def documents(repository):
    """Read Markdown in the supplied source snapshot; never follow outside it."""
    result = subprocess.run(['rg', '--files', '-g', '*.md', '-g', '*.mdx'],
                            cwd=repository, capture_output=True, text=True, check=False)
    if result.returncode not in {0, 1}:
        raise ValueError('Documentation inventory failed: ' + result.stderr)
    records, total, skipped = [], 0, []
    for name in sorted(result.stdout.splitlines()):
        path = (repository / name).resolve()
        if not path.is_relative_to(repository.resolve()):
            skipped.append(dict(path=name, reason='outside_source_snapshot'))
            continue
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_DOCUMENT_BYTES:
            return dict(status='documentation_budget_incomplete', documents=[],
                        receipts=[], skipped=skipped, bytes_seen=total)
        code = path.read_text(encoding='utf-8')
        records.append(dict(path=name, text=code, receipt=frozen(path)))
    return dict(status='complete', documents=[dict(path=r['path'], text=r['text']) for r in records],
                receipts=[r['receipt'] for r in records], skipped=skipped, bytes_seen=total)


def prepare(args):
    verify(read(args.source_cohort / 'seal.json'))
    previous = read(args.source_cohort / 'prepared.json')
    by_case = {}
    for row in previous['items']:
        old = by_case.setdefault(row['case'], row['source'])
        if old != row['source']:
            raise ValueError('One source snapshot per trial is required')
    args.output.mkdir(parents=True, exist_ok=False)
    admission._preload_local_imports(documented_defaults)
    algorithm = admission._loaded_sources()
    cases = []
    for case, source_name in sorted(by_case.items()):
        source = Path(source_name)
        inputs = {name: frozen(source / name) for name in
                  ['corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md']}
        corpus = read(source / 'corpus.json')
        frontend = read(source / 'frontend.json')
        spec = read(source / 'case.json')
        if corpus['language'] == 'typescript':
            inventory = documents(Path(spec['repository']))
            evidence = documented_defaults.extract(inventory.pop('documents'))
            if inventory['status'] == 'complete':
                generated = documented_defaults.generate(corpus, frontend, evidence, limit=16)
            else:
                generated = dict(status=inventory['status'], candidates=[], total_candidates=0)
        else:
            inventory = dict(status='language_unsupported', receipts=[], skipped=[], bytes_seen=0)
            evidence = dict(facts=[], conflicts=[], rejected=[])
            generated = dict(status='language_unsupported', candidates=[], total_candidates=0)
        directory = args.output / 'cases' / case
        write(directory / 'documentation.json', dict(inventory=inventory, evidence=evidence))
        programs = generated.pop('candidates')
        entries = []
        for rank, candidate in enumerate(programs, 1):
            path = directory / f'candidate_{rank:04d}' / 'program.json'
            write(path, candidate)
            entries.append(dict(rank=rank, program=frozen(path)))
        write(directory / 'generation.json', generated)
        cases.append(dict(case=case, source=str(source.resolve()), inputs=inputs,
            documentation=frozen(directory / 'documentation.json'), document_inputs=inventory['receipts'],
            generation=frozen(directory / 'generation.json'), candidates=entries, status=generated['status']))
        print(json.dumps(dict(case=case, documentation_files=len(inventory['receipts']),
            facts=len(evidence['facts']), total_candidates=generated.get('total_candidates', 0),
            selected=len(entries), status=generated['status'])), flush=True)
    admission.verify_seal(algorithm)
    if set(admission._loaded_sources()) - set(algorithm):
        raise ValueError('Unsealed source imported during construction')
    protocol = dict(version=VERSION, policy=documented_defaults.POLICY, algorithm=algorithm,
        source_cohort=frozen(args.source_cohort / 'prepared.json'), cases=cases,
        source_cohort_use='Only the trial list and source snapshot paths; no candidates or outcomes read.',
        trial_denominator=len(cases), max_candidates_per_trial=16,
        max_native_executions=len(cases) * 17, timeout=180, deadline_utc=args.deadline_utc,
        ordering='sorted trials; frozen source order within trial',
        stop='first controlled failure, then one independent repeat; stop that trial even if repeat fails to confirm',
        alert='same frozen program has controlled failure twice and exact test transport twice',
        semantic_gate='scoped documentation-default relation; no model and no evaluator labels',
        external_model_calls=0, evaluator_labels_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output / 'prepared.json', protocol)
    write(args.output / 'seal.json', frozen(args.output / 'prepared.json'))
    return dict(trials=len(cases), selected=sum(len(c['candidates']) for c in cases),
                prepared=frozen(args.output / 'prepared.json'))


def one_run(candidate, source, corpus, directory, protocol):
    outcome_path = directory / 'outcome.json'
    if outcome_path.exists():
        outcome = read(outcome_path)
        if outcome.get('native'):
            verify(outcome['native']['runs'])
        return outcome
    artifact, refusal = try_emit(candidate, source, directory / 'native', protocol)
    transport = (verify_emission(corpus, candidate, artifact) if artifact else
                 dict(status='not_emitted', reason=refusal))
    native = (execute(candidate, source, corpus, directory / 'native', protocol)
              if transport['status'] == 'matched' else None)
    outcome = dict(transport=transport, native=native, emission_refusal=refusal)
    write(outcome_path, outcome)
    return outcome


def run(args):
    root = args.input
    verify(read(root / 'seal.json'))
    p = read(root / 'prepared.json')
    admission.verify_seal(p['algorithm'])
    deadline = datetime.fromisoformat(p['deadline_utc'].replace('Z', '+00:00'))
    results = []
    def enough_time():
        used = len(list((root / 'cases').glob('*/candidate_*/**/native_outcome.json')))
        return (used < p['max_native_executions'] and
                (deadline - datetime.now(timezone.utc)).total_seconds() > p['timeout'] + 30)
    for case in p['cases']:
        directory = root / 'cases' / case['case']
        if (directory / 'result.json').exists():
            results.append(read(directory / 'result.json'))
            continue
        for receipt in [*case['inputs'].values(), case['documentation'],
                        case['generation'], *case['document_inputs']]:
            verify(receipt)
        source = Path(case['source'])
        corpus = read(source / 'corpus.json')
        result = dict(case=case['case'], attempts=[], alert=None, stop_reason=case['status'])
        for entry in case['candidates']:
            candidate_dir = directory / f"candidate_{entry['rank']:04d}"
            verify(entry['program'])
            candidate = read(entry['program']['path'])
            if not enough_time():
                result['stop_reason'] = 'execution_budget'
                break
            outcome = one_run(candidate, source, corpus, candidate_dir / 'initial', p)
            attempt = dict(rank=entry['rank'], program=entry['program'], initial=outcome)
            result['attempts'].append(attempt)
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
                    confirmation = one_run(candidate, source, corpus, candidate_dir / 'confirmation', p)
                    attempt['confirmation'] = confirmation
                    if (confirmation.get('native') or {}).get('controlled_failure'):
                        result['alert'] = dict(program=entry['program'],
                            initial=frozen(candidate_dir / 'initial/outcome.json'),
                            confirmation=frozen(candidate_dir / 'confirmation/outcome.json'),
                            validity='pending_independent_full_test_audit')
                        result['stop_reason'] = 'repeated_documented_relation_failure'
                break
            result['stop_reason'] = 'candidate_budget_exhausted'
        write(directory / 'result.json', result)
        results.append(result)
        print(json.dumps(dict(case=case['case'], attempts=len(result['attempts']),
                              alert=bool(result['alert']), stop=result['stop_reason'])), flush=True)
    admission.verify_seal(p['algorithm'])
    summary = dict(version=VERSION, results=results, trial_denominator=p['trial_denominator'],
        native_executions=len(list((root / 'cases').glob('*/candidate_*/**/native_outcome.json'))),
        external_model_calls=0, detector_alerts=sum(bool(r['alert']) for r in results),
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root / 'summary.json', summary)
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
