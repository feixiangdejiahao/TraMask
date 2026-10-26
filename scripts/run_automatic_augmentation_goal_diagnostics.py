"""Separate, explicitly human-goal generation controls for missed pilot targets.

This is not the automatic main method. It reuses the unchanged automatic
history payload, replacing only the model's goal with a public-source-reviewed
goal. It never supplies test code, previous execution logs or reference patches.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_automatic_augmentation_pilot as base
from scripts import run_automatic_augmentation_io_repair as main
from scripts import execute_automatic_augmentation_pilot as executor

DEFAULT_ROOT = main.DEFAULT_OUTPUT
FILES = [ROOT / 'research/automatic_augmentation_diagnostic_goals_n_20261005.json',
         ROOT / 'research/automatic_augmentation_diagnostic_goals_p_20261005.json']
GOAL_FIELDS = ['existing_validation', 'missing_relation', 'preconditions', 'object_binding',
               'operations', 'observation', 'expectation', 'oracle_basis', 'missing_evidence']


def prepare(root, selected):
    root = Path(root)
    protocol = main.load_protocol(root)
    dest = root / 'goal_diagnostics'
    if (dest / 'prepared.json').exists():
        base.verify(base.read(dest / 'seal.json'))
        prior = base.read(dest / 'prepared.json')
        for receipt in [prior['main_protocol'], prior['algorithm'], *prior['source_goal_records']]:
            base.verify(receipt)
        if {row['case'] for row in prior['rows']} != set(selected):
            raise ValueError('diagnostic_selection_changed')
        return prior
    manual = []
    for path in FILES:
        value = base.read(path)
        manual.extend(value.get('goals', value.get('cases', [])))
    rows = []
    for item in manual:
        if item['case'] not in selected:
            continue
        case = next(c for c in protocol['cases'] if c['case'] == item['case'])
        tid = item.get('base_test_id', item.get('host_base_test_id'))
        choices = [(b, s) for b in case['batches'] for s in b['candidates'] if s['base_test_id'] == tid]
        if len(choices) != 1:
            raise ValueError('manual_host_not_unique_in_automatic_candidates')
        batch, seed = choices[0]
        payload = base.read(batch['history_payload']['path'])
        issue = next(e['evidence_id'] for e in payload['evidence_catalog'] if e['kind'] == 'public_issue')
        goal = {k: item['goal'][k] for k in GOAL_FIELDS}
        goal.update(goal_id='DIAG_' + case['case'], seed_alias=seed['seed_alias'],
                    evidence_ids=[issue, seed['evidence_id']])
        if goal['missing_evidence']:
            raise ValueError('manual_goal_not_supported')
        row = dict(case=case['case'], source=case['source'], repository=case['repository'], inputs=case['inputs'],
                   batch=batch['batch_id'], payload=batch['history_payload'], seed=seed, goal=goal,
                   provenance='Explicit human interpretation of original public issue/source. Diagnostic only.',
                   test_code_or_old_execution_output_supplied=False)
        rows.append(row)
    if {r['case'] for r in rows} != set(selected):
        raise ValueError('unknown_diagnostic_case')
    record = dict(version='automatic-augmentation-human-goal-diagnostics.v1',
        main_protocol=base.receipt(root / 'prepared.json'), algorithm=base.receipt(__file__),
        source_goal_records=[base.receipt(p) for p in FILES], rows=rows,
        main_method=False, repeats=1, role='Conditional failure localization, never substitute for main scores.',
        selection='Only explicitly selected main target misses. All main outcomes remain unchanged.',
        input='Same automatic history payload; only the frozen goal comes from a human source review.',
        limits='A successful control establishes generator feasibility with supplied goals. It does not by itself separate missing-context from reasoning/prioritization failures.')
    base.write(dest / 'prepared.json', record)
    base.write(dest / 'seal.json', base.receipt(dest / 'prepared.json'))
    return record


def run(root, selected, workers=2):
    dest = root / 'goal_diagnostics'
    protocol = prepare(root, selected)
    def job(row):
        directory = dest / row['case']
        if (directory / 'result.json').exists():
            base.verify(base.read(directory / 'result_seal.json'))
            return base.read(directory / 'result.json')
        base.verify(row['payload'])
        payload = base.read(row['payload']['path'])
        req = main.request(main.GENERATION_SYSTEM, dict(original_evidence=payload, frozen_goals=[row['goal']]), 'human_goal_diagnostic')
        req['manual_labels_included'] = True
        req['diagnostic_only'] = True
        req['hidden_reference_or_verifier_inputs'] = False
        req['id'] = req['query_sha256'] = base.digest({k: v for k, v in req.items() if k not in {'id', 'query_sha256'}})
        content, meta = main.dispatch_once(req, directory / 'generation')
        corpus = base.read(row['inputs']['corpus.json']['path'])
        case = dict(case=row['case'], source=row['source'], repository=row['repository'],
                    seeds=[row['seed']], goals=[row['goal']])
        decoded = executor.decode(corpus, case, content, meta.get('finish_reason'))
        base.write(directory / 'generation/decoded.json', decoded)
        for i, candidate in enumerate(decoded['candidates'], 1):
            base.write(directory / 'generation' / f'candidate_{i:02d}' / 'program.json', candidate)
        result = dict(case=row['case'], main_method=False, status=decoded['status'],
            candidates=len(decoded['candidates']), rejected=decoded.get('rejected', []),
            decoded=base.receipt(directory / 'generation/decoded.json'),
            provider_calls=meta.get('external_model_calls', 0),
            measured_tokens=(meta.get('usage') or {}).get('total_tokens', 0),
            usage_missing=int(not meta.get('usage')), goal=row['goal'])
        base.write(directory / 'result.json', result)
        base.write(directory / 'result_seal.json', base.receipt(directory / 'result.json'))
        print(base.canonical(result), flush=True)
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(job, protocol['rows']))
    summary = dict(main_method=False, rows=rows, provider_calls=sum(r['provider_calls'] for r in rows),
                   measured_tokens=sum(r['measured_tokens'] for r in rows), candidates=sum(r['candidates'] for r in rows))
    base.write(dest / 'summary.json', summary)
    return {k: v for k, v in summary.items() if k != 'rows'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--cases', required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    print(base.canonical(run(args.root, args.cases.split(','), args.workers)))
