#!/usr/bin/env python3
"""Collect and baseline two real tests in the existing local S030 checkpoint."""
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from eviweave.artifacts import read_json, write_json
from eviweave.baseline import run_selected_test
from eviweave.collection import collect_tests
from eviweave.replay import load_case

PREVIOUS = ROOT / 'results/behavioral_masking/20261031_eviweave_refactor_smoke_r02'
OUT = ROOT / 'results/behavioral_masking/20261101_step_a_simplification_r02'


def identity(unit):
    return tuple(unit[k] for k in ('path', 'source_sha256', 'name', 'first_line', 'last_line'))


def main():
    checkpoint = read_json(PREVIOUS / 'S030/checkpoint.json')
    raw = OUT / 'live_inputs'
    raw.mkdir()
    (raw / 'instruction.md').write_text('Regression smoke: collect and baseline existing S030 tests in its submitted checkpoint.\n')
    (raw / 'model.patch').write_bytes(b'')
    (raw / 'task.toml').write_text('[metadata]\nbase_commit_hash="' + checkpoint['head'] +
                                  '"\n[environment]\ndocker_image="' + checkpoint['image_id'] + '"\n')
    jobs, steps = [], []
    for index, name in enumerate(('baseline_streaming', 'baseline_malformed')):
        plan = read_json(PREVIOUS / name / 'plan.json')
        baseline = read_json(PREVIOUS / name / 'baseline.json')
        output = (PREVIOUS / name / 'container/calls/test/output.bin').read_text()
        jobs.append({'name': name, 'command': plan['command'], 'test_name': baseline['test']['name']})
        steps.append({'step_id': index, 'source': 'agent',
                      'tool_calls': [{'function_name': 'bash', 'arguments': {'command': plan['command']}}],
                      'observation': {'results': [{'content': json.dumps({'returncode': 0, 'output': output})}]}})
    write_json(raw / 'trajectory.json', {'steps': steps})
    collected = collect_tests(load_case('S030-regression', raw), raw, OUT / 'live_collect')
    assert collected['state_validation_passed']
    manifest_path = Path(collected['step_a']['manifest'])
    manifest = read_json(manifest_path)
    retained = [t for t in manifest['tests'] if t['retained_at_submission']]
    old = read_json(PREVIOUS / 'S030/tests/manifest.json')
    assert {identity(t) for t in retained} == {identity(t) for t in old['current_tests'] + old['retained_unlinked_tests']}
    print(json.dumps({'collected': len(retained), 'submission_state_validated': True}), flush=True)
    outcomes = []
    for job in jobs:
        unit = next(t for t in retained if t['name'] == job['test_name'])
        result = run_selected_test(manifest_path, unit['id'], job['command'], OUT / ('live_' + job['name']))
        assert result['test_outcome'] == 'passed' and result['sources_unchanged']
        outcomes.append({'test': job['test_name'], 'outcome': result['test_outcome'],
                         'named_instances': len(result['named_reports']), 'sources_unchanged': True})
        print(json.dumps(outcomes[-1]), flush=True)
    summary = {'source_checkpoint': checkpoint, 'observed_commands': len(steps),
               'state_validation_passed': True, 'retained_tests': len(retained),
               'retained_test_identities_equal': True, 'baselines': outcomes,
               'scope': 'Fresh replay and collection of two validation commands on the existing submitted checkpoint; not a rerun of the full original trajectory.'}
    write_json(OUT / 'live_smoke.json', summary)


if __name__ == '__main__':
    main()
