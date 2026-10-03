"""Evaluator-only blind differential execution of every frozen emitted alert.

This module never chooses or repairs detector outputs. Reference paths are
resolved only after the complete alert list is supplied. Reference bodies are
never parsed or exposed to candidate generation or a model provider.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from combination_testing import runner
from combination_testing.test_reports import parse_report
from relation_search.candidate_edit_transport import rewrite_view, verify_emission, GO_MATERIALIZER_SOURCE
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.audit_requested_source_controls import inspect_controls, native
from scripts.execute_relation_search import _go_item_view
from scripts.evaluate_relational_gap import matches_runtime
from scripts.run_contract_repair_search import frozen, verify, write
from scripts.run_type_projection_component import emit

VERSION = 'frozen-alert-blind-reference-evaluator.v1'
DRIVER = '''import json, os, runpy
from pathlib import Path
module = runpy.run_path('.relational_phase_inputs/runner.py')
module['execute_plan'](json.loads(Path('.relational_phase_inputs/plan.json').read_text()),
                       logs=Path(os.environ['COMBINATION_REPORT_DIR']))
'''


def prepare(args):
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    alerts = read(args.alerts)['alerts']
    inventory = read(args.inventory)['controlled_failures']
    records = {row['key']: row for row in inventory}
    registry = read(args.registry)
    rows = registry['cases'] if isinstance(registry, dict) else registry
    cases = {row['id']: row for row in rows}
    items = []
    for index, alert in enumerate(alerts):
        record = records[alert['key']]
        if (record['case'], record['candidate_id']) != (alert['case'], alert['candidate_id']):
            raise ValueError('Alert/inventory identity differs')
        inputs = {key: value for key, value in record['inputs'].items()
                  if key in {'corpus', 'frontend', 'candidates'}}
        for receipt in inputs.values():
            verify(receipt)
        corpus = read(inputs['corpus']['path'])
        catalog = read(inputs['candidates']['path'])
        if isinstance(catalog, dict):
            catalog = catalog['candidates']
        candidate = rewrite_view(next(c for c in catalog if c['id'] == alert['candidate_id']))
        directory = root / 'cases' / f'item_{index:04d}'
        write(directory / 'program.json', candidate)
        source = Path(inputs['corpus']['path']).parent
        artifact = emit(candidate, source, directory / 'emission', {'timeout': 180})
        transport = verify_emission(corpus, candidate, artifact)
        write(directory / 'transport.json', transport)
        if transport['status'] != 'matched':
            raise ValueError('Frozen alert emission does not preserve intended test syntax')
        manifest = read(artifact / 'manifest.json')
        files = {}
        for mount in manifest['mounts']:
            verify(dict(path=mount['source'], sha256=mount['sha256']))
            files[mount['target']] = Path(mount['source']).read_text()
        files['.frozen_reference_evaluation.py'] = DRIVER
        generated = next(phase for phase in manifest['phases'] if phase['role'] == 'generated')
        frozen_artifact = directory / 'artifact'
        runner.freeze_artifact(frozen_artifact, record['case'], files,
            'python3 .frozen_reference_evaluation.py', generated['report']['format'],
            'generated/' + generated['report']['path'], timeout=manifest['timeout'],
            metadata=dict(evaluator_only=True, original_alert=alert['key'],
                          reference_used_for_generation=False))
        try:
            reference = dict(status='available', patch=frozen(runner.reference_patch_for(cases[record['case']])))
        except FileNotFoundError:
            reference = dict(status='unavailable_in_configured_reference_root')
        items.append(dict(name=f'item_{index:04d}', case=record['case'], key=alert['key'],
            program=frozen(directory / 'program.json'), source_inputs=inputs,
            source_emission=frozen(artifact / 'manifest.json'),
            artifact=frozen(frozen_artifact / 'manifest.json'), reference=reference,
            candidate_patch=frozen(cases[record['case']]['candidate_patch'])))
    admission._preload_local_imports(sys.modules[__name__])
    protocol = dict(version=VERSION, alerts=frozen(args.alerts), inventory=frozen(args.inventory),
        registry=frozen(args.registry), items=items, algorithm=admission._loaded_sources(),
        go_materializer=frozen(GO_MATERIALIZER_SOURCE),
        selection='Every supplied alert, with no replacement or oracle edits.',
        reference_role='independent evaluation only; acceptance alone does not establish oracle validity',
        no_reference_source_parsing=True, external_model_calls=0, detector_outputs_changed=False,
        max_native_executions=len(items) + sum(i['reference']['status'] == 'available' for i in items),
        created_utc=datetime.now(timezone.utc).isoformat())
    write(root / 'prepared.json', protocol)
    write(root / 'seal.json', frozen(root / 'prepared.json'))
    return dict(alerts=len(items), available_references=sum(i['reference']['status'] == 'available' for i in items),
                prepared=frozen(root / 'prepared.json'))


def normalize(output, emission, execution):
    rows = []
    for phase in emission['phases']:
        if phase['role'] not in {'control', 'generated'}:
            continue
        directory = output / phase['role']
        process = read(directory / 'result.json') if (directory / 'result.json').exists() else dict(error='phase_missing')
        items = emission['controls'] if phase['role'] == 'control' else emission['obligations']
        report = parse_report(directory, phase['report'], process, selected_names=[i['id'] for i in items])
        write(directory / 'normalized.json', report)
        isolated = phase.get('isolation', {}).get('kind') == 'go_test_process'
        isolation_path = directory / phase.get('isolation', {}).get('summary_path', 'not-applicable')
        isolation = read(isolation_path) if isolated and isolation_path.exists() else None
        for item in items:
            path = directory / 'normalized.json'
            if isolated:
                path, _ = _go_item_view(directory, phase, item, isolation)
            rows.append(dict(role=phase['role'], result=str(path.resolve()), test_ids=[item['id']],
                             control_ids=item.get('control_ids', []), candidate_id=item.get('candidate_id')))
    generated = [row for row in rows if row['role'] == 'generated']
    controls = inspect_controls(generated, rows)
    tests, errors = [], []
    for row in generated:
        found, issues, _ = native(row['result'])
        tests.extend(t for t in found if any(matches_runtime(t['id'], name) for name in row['test_ids']))
        errors.extend(issues)
    return dict(controls=controls, tests=tests, parser_errors=errors, execution=frozen(output / 'result.json'),
                controlled_failure=bool(tests and any(t['status'] in {'fail', 'error'} for t in tests)
                    and not errors and controls['status'] == 'all_source_controls_passed'),
                controlled_pass=bool(tests and all(t['status'] == 'pass' for t in tests)
                    and not errors and controls['status'] == 'all_source_controls_passed'))


def run(args):
    root = args.input
    verify(read(root / 'seal.json'))
    p = read(root / 'prepared.json')
    admission.verify_seal(p['algorithm'])
    verify(p['registry'])
    results = []
    for item in p['items']:
        directory = root / 'cases' / item['name']
        if (directory / 'result.json').exists():
            results.append(read(directory / 'result.json'))
            continue
        for key in ('program', 'source_emission', 'artifact', 'candidate_patch'):
            verify(item[key])
        emission = read(item['source_emission']['path'])
        outcome = dict(case=item['case'], key=item['key'], reference_availability=item['reference']['status'])
        programs = ['candidate'] + (['reference'] if item['reference']['status'] == 'available' else [])
        for program in programs:
            patch = None
            if program == 'reference':
                verify(item['reference']['patch'])
                patch = Path(item['reference']['patch']['path'])
            output = directory / program
            if (output / 'result.json').exists():
                execution = read(output / 'result.json')
            else:
                execution = runner.run_artifact(Path(item['artifact']['path']).parent, program, output,
                    registry=Path(p['registry']['path']), reference_patch=patch)
            outcome[program] = normalize(output, emission, execution)
        outcome['differential_observation'] = bool(outcome['candidate']['controlled_failure']
            and outcome.get('reference', {}).get('controlled_pass'))
        outcome['oracle_validity'] = 'requires_independent_contract_evidence'
        write(directory / 'result.json', outcome)
        results.append(outcome)
        print(json.dumps(dict(case=item['case'], differential_observation=outcome['differential_observation'],
                              reference_availability=item['reference']['status'])), flush=True)
    admission.verify_seal(p['algorithm'])
    summary = dict(version=VERSION, items=results, external_model_calls=0, detector_outputs_changed=False,
                   native_executions=sum(1 + ('reference' in r) for r in results),
                   completed_utc=datetime.now(timezone.utc).isoformat())
    write(root / 'summary.json', summary)
    return dict(alerts=len(results), native_executions=summary['native_executions'],
                differential_observations=sum(r['differential_observation'] for r in results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--alerts', type=Path)
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--registry', type=Path, default=ROOT / 'data/relational_gap_v1/registry.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
