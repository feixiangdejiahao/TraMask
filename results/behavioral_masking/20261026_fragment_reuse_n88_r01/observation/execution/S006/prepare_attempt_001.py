"""Freeze a two-condition historical setup transfer and both singleton controls."""
from pathlib import Path
import copy
import difflib
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / 'src'))
from context_recovery_pilot1_runtime import patch_paths

RUN = ROOT / 'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
OUT = Path(__file__).parent / 'attempt_001'
OUT.mkdir(exist_ok=False)


def receipt(path):
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


checkpoint = json.loads((RUN / 'cases/S006/checkpoint.json').read_text())
history_path = RUN / 'public_inputs/S006/history.json'
actions = {a['id']: a for a in json.loads(history_path.read_text())['actions']}
model_patch = Path(checkpoint['input_directory']) / 'model.patch'
reference_patch = Path(checkpoint['task_directory']) / 'solution/solution.patch'
test_path = 'src/__tests__/container.initialize.test.ts'
patch = model_patch.read_text()
section = patch.split(f'diff --git a/{test_path} b/{test_path}\n', 1)[1].split('\ndiff --git ', 1)[0]
assert 'new file mode ' in section and '--- /dev/null' in section
original = ''.join(line[1:] + '\n' for line in section.splitlines() if line.startswith('+') and not line.startswith('+++'))
name = 'limits concurrency within a level'
pattern = re.compile(r"  it\('" + re.escape(name) + r"', async \(\) => \{.*?\n  \}\)", re.S)
match = pattern.search(original)
assert match is not None
block = match.group()
assert re.sub(r'\s+', '', block) == re.sub(r'\s+', '', pattern.search(actions['s57_c0']['command']).group())
assert 'container.register({ a: mk(), b: mk(), c: mk() })' in block
assert 'await container.initialize({ concurrency: 2 })' in block
base = {
    'checkpoint': {k: checkpoint[k] for k in ('image_id', 'head')},
    'checkpoint_validation': str(RUN / 'cases/S006/checkpoint_validation/qualification.json'),
    'base_commit': checkpoint['base_commit'],
    'task_directory': checkpoint['task_directory'],
    'input_directory': checkpoint['input_directory'],
    'timeout': 180, 'build_commands': [], 'requires_build': False,
    'workdir': '/app', 'resources': {'cpus': 2, 'memory': '4g', 'pids_limit': 512},
    'production_paths': sorted(set(patch_paths(model_patch.read_text())) | set(patch_paths(reference_patch.read_text()))),
    'mode': 'agent',
    'command': './node_modules/.bin/jest --runInBand src/__tests__/container.initialize.test.ts -t "limits concurrency within a level"',
}
variants = {'original': (False, False), 'default_only': (True, False),
            'two_services_only': (False, True), 'default_and_two_services': (True, True)}
plans = []
for variant, (default, two) in variants.items():
    edited = block
    if default:
        edited = edited.replace('await container.initialize({ concurrency: 2 })', 'await container.initialize()')
    if two:
        edited = edited.replace('container.register({ a: mk(), b: mk(), c: mk() })', 'container.register({ a: mk(), b: mk() })')
    candidate = original[:match.start()] + edited + original[match.end():]
    for assertion in ('expect(maxActive).toBeLessThanOrEqual(2)', 'expect(maxActive).toBe(2)'):
        assert assertion in edited
    prepared = OUT / 'prepared' / variant
    prepared.mkdir(parents=True)
    path = prepared / 'container.initialize.test.ts'
    path.write_text(candidate)
    (prepared / 'edit.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True), fromfile='original.ts', tofile='candidate.ts')))
    write(prepared / 'frozen.json', {'variant': variant, 'file': receipt(path), 'default_concurrency': default,
          'two_independent_services': two, 'target_and_assertions_preserved': True})
    for implementation in ('delivered', 'reference'):
        for repeat in (1, 2):
            run_id = f'{variant}_{implementation}_{repeat}'
            plan = copy.deepcopy(base)
            plan.update(implementation=implementation, files=[{'source': str(path), 'destination': '/app/' + test_path}])
            plan_path = OUT / 'plans' / (run_id + '.json')
            write(plan_path, plan)
            plans.append({'id': run_id, 'variant': variant, 'implementation': implementation,
                          'repeat': repeat, 'plan': receipt(plan_path), 'out': str(OUT / 'runs' / run_id)})
write(OUT / 'manifest.json', {
    'case_id': 'S006', 'stage': 'informed_observation', 'counts_as_blind_result': False,
    'scope': 'entire selected original named concurrency test, chosen before execution',
    'selected_test': name, 'source_receipts': [receipt(history_path), receipt(model_patch), receipt(reference_patch), receipt(Path(__file__))],
    'base': {'definition': 's57_c0', 'named_pass': 's65_c0', 'final_suite_pass': 's104_c0'},
    'donor': {'unit': 'waits for in-flight initializers in a level before rolling back',
              'definition': 's57_c0', 'named_pass': 's65_c0',
              'conditions': ['default initialize options', 'two independent same-level services slow/fast; later depends on slow']},
    'adaptation': 'Keep base mk/counter/delay and both max2 assertions; omit explicit concurrency cap and remove third independent registration.',
    'control_rationale': 'Default-only with three services may also fail R because the old max2 oracle was for a cap. This singleton outcome must be retained.',
    'candidate_order': list(variants), 'plans': plans,
})
print(json.dumps({'out': str(OUT), 'plans': len(plans)}))
