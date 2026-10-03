"""Check test bodies and their local import/helper dependencies uniformly."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import read
from relation_search.candidate_edit_transport import verify_emission
from scripts import inspect_typescript_candidate as compiler
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import write, frozen, verify

VERSION = 'paired-typescript-local-dependency-census.v1'
WORKER = ROOT / 'scripts/compare_typescript_dependency_closure.cjs'


def prepare(args):
    prior = read(args.cohort / 'prepared.json')
    verify(read(args.cohort / 'seal.json'))
    for item in prior['items']:
        for receipt in item['inputs'].values():
            verify(receipt)
    args.output.mkdir(parents=True, exist_ok=False)
    admission._preload_local_imports(compiler)
    protocol = dict(version=VERSION, items=prior['items'], cohort=frozen(args.cohort / 'prepared.json'),
        algorithm=admission._loaded_sources(), worker=frozen(WORKER), timeout=180,
        selection='Every program in the previous complete typed-parent cohort; no runtime outcomes or labels.',
        max_dependency_declarations=128, max_compiler_runs=len(prior['items']),
        source_scope='Selected tests plus symbol-linked import bindings and helper declarations in the same source file.',
        external_model_calls=0, subject_test_executions=0, detector_alerts=0,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output / 'prepared.json', protocol)
    write(args.output / 'seal.json', frozen(args.output / 'prepared.json'))
    return dict(programs=len(prior['items']), prepared=frozen(args.output / 'prepared.json'))


def prepare_compiler(artifact, output, protocol):
    output.mkdir(parents=True, exist_ok=False)
    # Preserve the established source/command adapter. Only the sealed compiler
    # worker changes. Its dependency scope has a fixed finite bound.
    p = compiler.prepare(artifact, output / 'source_plan')
    p['mounts'] = [dict(source=protocol['worker']['path'], target=row['target'], sha256=protocol['worker']['sha256'])
                   if row['target'] == '.type_analysis/worker.cjs' else row for row in p['mounts']]
    p['worker'] = protocol['worker']
    p['diagnostic_method'] = VERSION
    write(output / 'prepared.json', p)


def run(args):
    root = args.input
    verify(read(root / 'seal.json'))
    p = read(root / 'prepared.json')
    admission.verify_seal(p['algorithm'])
    verify(p['worker'])
    results = []
    for item in p['items']:
        directory = root / 'cases' / item['case'] / item['occurrence']
        if (directory / 'result.json').exists():
            results.append(read(directory / 'result.json'))
            continue
        for receipt in item['inputs'].values():
            verify(receipt)
        source = Path(item['source'])
        corpus = read(source / 'corpus.json')
        candidate = read(source / 'candidates.json')['candidates'][0]
        transport = verify_emission(corpus, candidate, Path(item['artifact']))
        outcome = dict(case=item['case'], occurrence=item['occurrence'], transport=transport)
        if transport['status'] == 'matched':
            comparison = directory / 'compiler'
            if not (comparison / 'prepared.json').exists():
                prepare_compiler(Path(item['artifact']), comparison, p)
            if (comparison / 'outcome.json').exists():
                result = read(comparison / 'outcome.json')
            else:
                result = compiler.run(comparison, p['timeout'])
                write(comparison / 'outcome.json', result)
            outcome['compile'] = result
        else:
            outcome['compile'] = dict(status='program_transport_mismatch', new_diagnostics=[])
        write(directory / 'result.json', outcome)
        results.append(outcome)
        print(json.dumps(dict(case=item['case'], occurrence=item['occurrence'],
            status=outcome['compile']['status'], new_diagnostics=len(outcome['compile']['new_diagnostics']))), flush=True)
    admission.verify_seal(p['algorithm'])
    summary = dict(version=VERSION, items=results, external_model_calls=0, subject_test_executions=0,
        detector_alerts=0, compiler_runs=sum(r['transport']['status'] == 'matched' for r in results),
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root / 'summary.json', summary)
    return dict(programs=len(results), compiler_runs=summary['compiler_runs'],
        statuses=dict(Counter(r['compile']['status'] for r in results)),
        new_dependency_diagnostics=sum(d.get('scope') == 'local_dependency'
            for r in results for d in r['compile'].get('new_diagnostics', [])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--cohort', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
