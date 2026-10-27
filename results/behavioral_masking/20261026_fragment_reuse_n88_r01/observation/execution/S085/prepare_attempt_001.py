"""Freeze informed S085 assembly controls from executed history, before running them."""
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
OLD = ROOT / 'results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01/cases/S085'
OUT = Path(__file__).parent / 'attempt_001'
OUT.mkdir(exist_ok=False)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def receipt(path):
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


history_path = RUN / 'public_inputs/S085/history.json'
actions = {a['id']: a for a in json.loads(history_path.read_text())['actions']}
original_path = OLD / 'prepared_candidate_001/original.ts'
original = original_path.read_text()
name = 'isolateSlowThreshold isolates slow files across shards'
pattern = re.compile(r"test\('" + re.escape(name) + r"', async \(\) => \{.*?\n\}\)", re.S)
block = pattern.search(original).group()
assert block == pattern.search(actions['s108_c0']['command']).group()
assert block.count('isolateSlowThreshold: 150') == 2
donor_history = json.loads(actions['s87_c0']['observation']['output'].split('---history---\n', 1)[1])
fixture_relative = 'test/config/fixtures/duration-shard'
fixtures = OLD / 'prepared_candidate_001/required-files' / fixture_relative
base_history = json.loads((fixtures / 'duration-history.json').read_text())
for fixture in fixtures.rglob('*'):
    if fixture.is_file():
        assert fixture.read_text() in actions['s107_c0']['command']

base_plan = json.loads((OLD / 'execution_plans/candidate_001_original_delivered.json').read_text())
checkpoint = json.loads((RUN / 'cases/S085/checkpoint.json').read_text())
base_plan['checkpoint'] = {k: checkpoint[k] for k in ('image_id', 'head')}
base_plan['checkpoint_validation'] = str(RUN / 'cases/S085/checkpoint_validation/qualification.json')
model_patch = Path(base_plan['input_directory']) / 'model.patch'
reference_patch = Path(base_plan['task_directory']) / 'solution/solution.patch'
base_plan['production_paths'] = sorted(set(patch_paths(model_patch.read_text())) | set(patch_paths(reference_patch.read_text())))

variants = {
    'original': {'records': [], 'threshold': None},
    'history_b_only': {'records': [('test/b.test.ts', 'test/2.test.js')], 'threshold': None},
    'history_c_only': {'records': [('test/c.test.ts', 'test/3.test.js')], 'threshold': None},
    'history_bc': {'records': [('test/b.test.ts', 'test/2.test.js'), ('test/c.test.ts', 'test/3.test.js')], 'threshold': None},
    'derived_threshold_350': {'records': [], 'threshold': 350},
}
plans = []
for variant, spec in variants.items():
    prepared = OUT / 'prepared' / variant
    prepared.mkdir(parents=True)
    changed_history = copy.deepcopy(base_history)
    for source, destination in spec['records']:
        changed_history[destination] = copy.deepcopy(donor_history[source])
    history_file = prepared / 'duration-history.json'
    if spec['records']:
        write(history_file, changed_history)
    else:
        history_file.write_bytes((fixtures / 'duration-history.json').read_bytes())
    test_file = prepared / 'duration-shard.test.ts'
    test = original
    if spec['threshold']:
        replacement = block.replace('isolateSlowThreshold: 150', 'isolateSlowThreshold: 350')
        test = original[:pattern.search(original).start()] + replacement + original[pattern.search(original).end():]
    test_file.write_text(test)
    files = [{'source': str(test_file), 'destination': '/app/test/config/test/duration-shard.test.ts'},
             {'source': str(history_file), 'destination': f'/app/{fixture_relative}/duration-history.json'}]
    for source in sorted((fixtures / 'test').glob('*.js')):
        destination = prepared / source.name
        destination.write_bytes(source.read_bytes())
        files.append({'source': str(destination), 'destination': f'/app/{fixture_relative}/test/{source.name}'})
    (prepared / 'test.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True), test.splitlines(True), fromfile='original.ts', tofile='assembled.ts')))
    (prepared / 'history.diff').write_text(''.join(difflib.unified_diff(json.dumps(base_history, indent=2).splitlines(True), json.dumps(changed_history, indent=2).splitlines(True), fromfile='original-history.json', tofile='assembled-history.json')))
    write(prepared / 'frozen.json', {'variant': variant, 'edits': spec,
          'files': [receipt(Path(f['source'])) for f in files],
          'threshold_provenance': 'new numeric parameter derived to instantiate historical low-slow-count relation; 350 is not an executed historical value' if spec['threshold'] else None,
          'record_transfer': 'Whole recorded observation objects from s87, alpha-renamed b->2 and c->3; timestamps and observation lists retained' if spec['records'] else None,
          'preserved': ['both shard operations', 'both full expected path arrays', 'selected named test', 'production source']})
    for implementation in ('delivered', 'reference'):
        for repeat in (1, 2):
            plan = copy.deepcopy(base_plan)
            plan.update(files=files, implementation=implementation)
            run_id = f'{variant}_{implementation}_{repeat}'
            plan_path = OUT / 'plans' / f'{run_id}.json'
            write(plan_path, plan)
            plans.append({'id': run_id, 'variant': variant, 'implementation': implementation,
                          'repeat': repeat, 'plan': receipt(plan_path), 'out': str(OUT / 'runs' / run_id)})

write(OUT / 'manifest.json', {
    'case_id': 'S085', 'stage': 'informed_observation', 'counts_as_blind_result': False,
    'selected_test': name, 'scope': 'entire original named test, selected before new execution; other named tests are filtered',
    'source_receipts': [receipt(history_path), receipt(original_path), receipt(model_patch), receipt(reference_patch), receipt(Path(__file__))],
    'base_test_definition': 's108_c0; exact selected block equals original final test block',
    'base_fixture_definition': 's107_c0; all original fixture contents exactly appear in command',
    'donor_state_snapshot': 's87_c0; actual four-file execution followed by history-file output',
    'donor_joint_execution': 's95_c0 low-slow-count CLI; printed allocation but lacked isolation assertion',
    'candidate_order': list(variants), 'plans': plans,
    'semantic_granularity': {'historical_transfer': 'one duration-distribution condition, two complete record substitutions; singleton controls test their joint necessity in this fixture',
                             'threshold_variant': 'one parameter instantiated twice; derived literal, not direct historical record reuse'},
})
print(json.dumps({'out': str(OUT), 'plans': len(plans)}))
