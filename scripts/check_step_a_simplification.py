#!/usr/bin/env python3
"""Recollect S030 from its frozen observations and compare algorithm facts."""
import base64
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from eviweave.artifacts import read_json, write_json
from eviweave.collection import ReplayTestCollector
from eviweave.replay.trajectory import resolve_submission_actions

SOURCE = ROOT / 'results/behavioral_masking/20261031_eviweave_refactor_smoke_r02/S030'
OUT = ROOT / 'results/behavioral_masking/20261101_step_a_simplification_r02'


def files(rows):
    return [{k: row[k] for k in ('path', 'kind', 'sha256', 'target') if k in row} for row in rows]


class RecordedObservations:
    def __init__(self):
        self.output = SOURCE / 'runtime'
        self.point = 'initial'
        self.reads = 0

    def control(self, argv, *, input_bytes, **kwargs):
        request = json.loads(input_bytes)
        snapshot = read_json(SOURCE / 'tests/snapshots' / (self.point + '.json'))
        known = set(request['known_blobs'])
        blobs = {r['sha256']: base64.b64encode((SOURCE / 'tests/blobs' / r['sha256']).read_bytes()).decode()
                 for r in snapshot['files'] if r['kind'] == 'file' and r['sha256'] not in known}
        self.reads += 1
        return SimpleNamespace(stdout=json.dumps({'files': files(snapshot['files']), 'blobs': blobs}).encode())


def key(unit):
    return tuple(unit[k] for k in ('path', 'source_sha256', 'name', 'first_line', 'last_line'))


def main():
    actions, _ = resolve_submission_actions(read_json(SOURCE / 'inputs/trajectory.json'))
    old_path = SOURCE / 'tests/manifest.json'
    old = read_json(old_path)
    collector = ReplayTestCollector(OUT / 'recollected/S030/tests', actions)
    runtime = RecordedObservations()
    collector.start(runtime)
    for action in actions:
        runtime.point = action['id'] + '_before'
        collector.before_action(runtime, action)
        runtime.point = action['id'] + '_after'
        result = read_json(runtime.output / 'calls' / action['id'] / 'result.json')
        collector.after_action(runtime, action, result)
    runtime.point = 'submission'
    collector.capture_submission(runtime)
    validation = read_json(SOURCE / 'summary.json')['validation']
    collector.finish(old['checkpoint'], validation)
    new_path = collector.out / 'manifest.json'
    new = read_json(new_path)
    # The original replay owns commands, inputs and checkpoint. No copied logs.
    new['replay'] = str(SOURCE)
    write_json(new_path, new)
    old_units = {key(t): t for t in old['historical_test_versions']}
    new_units = {key(t): t for t in new['tests']}
    assert old_units.keys() == new_units.keys()
    for identity, unit in new_units.items():
        previous = old_units[identity]
        assert unit['execution_status'] == previous['execution_status']
        observed = [a for a in previous['historical_associations'] if a['original_named_reports'] or a['replay_named_reports']]
        assert len(unit['historical_associations']) == len(observed)
        for link, original in zip(unit['historical_associations'], observed):
            assert link == {k: original[k] for k in link}
    old_current = {key(t) for t in old['current_tests'] + old['retained_unlinked_tests']}
    new_current = {key(t) for t in new['tests'] if t['retained_at_submission']}
    assert old_current == new_current
    old_versions = {(r['path'], r['sha256']) for r in old['source_versions']}
    new_versions = {(r['path'], r['sha256']) for r in new['source_versions']}
    assert old_versions == new_versions
    for _, digest in new_versions:
        assert (SOURCE / 'tests/blobs' / digest).read_bytes() == (collector.out / 'blobs' / digest).read_bytes()
    old_literals = {(s['action_id'], s['path'], s['sha256']) for s in old['unobserved_source_candidates']
                    if (s['path'], s['sha256']) not in old_versions}
    assert old_literals == {(s['action_id'], s['path'], s['sha256']) for s in new['unobserved_source_candidates']}
    old_events = sorted((SOURCE / 'tests/executions').glob('*.json'))
    for path in old_events:
        original = read_json(path)
        event = read_json(collector.out / 'executions' / path.name)
        for field in ('before_snapshot', 'after_snapshot'):
            old_state = read_json(SOURCE / 'tests/snapshots' / (original[field] + '.json'))
            new_state = read_json(collector.out / 'snapshots' / (event[field] + '.json'))
            assert files(old_state['files']) == new_state['files']
    previous_snapshots = list((SOURCE / 'tests/snapshots').glob('*.json'))
    new_snapshots = list((collector.out / 'snapshots').glob('*.json'))
    result = {
        'source': str(SOURCE), 'output': str(collector.out),
        'verification': 'Recollection from frozen source snapshots and real outputs; original commands are not reexecuted.',
        'actions': len(actions), 'test_versions': len(new_units), 'retained_tests': len(new_current),
        'source_versions': len(new_versions), 'validation_actions': len(old_events),
        'historical_associations': sum(len(t['historical_associations']) for t in new['tests']),
        'previous_scope_associations': sum(len(t['historical_associations']) for t in old_units.values()),
        'facts_equal': ['test identities and ranges', 'retained tests', 'all source bytes',
                        'named reports and execution classification', 'version/runner ambiguity and notices',
                        'before/after source states', 'unobserved source candidates'],
        'manifest_bytes': {'before': old_path.stat().st_size, 'after': new_path.stat().st_size},
        'snapshot_files': {'before': len(previous_snapshots), 'after': len(new_snapshots)},
        'snapshot_bytes': {'before': sum(p.stat().st_size for p in previous_snapshots),
                           'after': sum(p.stat().st_size for p in new_snapshots)},
        'snapshot_reads': runtime.reads,
        'removed_git_queries_per_snapshot': 4,
        'removed_manifest_fields': sorted(old.keys() - new.keys()),
        'test_fields': list(new['tests'][0]),
        'association_fields': list(next(t for t in new['tests'] if t['historical_associations'])['historical_associations'][0])}
    write_json(OUT / 'verification.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
