"""Replay frozen actual writes and separately audit old phase-only novelty."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experimental.assertion_write_origin import Module
from experimental.observed_write_frontier import Frontier, fingerprint, project
from relation_search.checkpoint import digest, read, write
from relation_search.frontier import canonical_profile, _observed_roles


def traces(directory, name):
    path = directory / name
    if path.is_file():
        checksum = digest(path)
        for line, content in enumerate(path.read_text().splitlines(), 1):
            yield dict(trace=str(path.resolve()), trace_sha256=checksum,
                       trace_line=line, event=json.loads(content))


def owners(selection, role):
    manifest = read(selection['source_manifest'])
    phase = next(row for row in manifest['phases'] if row['role'] == role)
    mounts = {row['target']: row for row in manifest['mounts']}
    items = manifest[{'control': 'controls', 'source_profile': 'profile_obligations',
                      'generated': 'obligations'}[role]]
    result = []
    for row in phase['files']:
        mount = mounts[row['staged']]
        if digest(mount['source']) != row['sha256']:
            raise ValueError('Original emitted source changed')
        selected = [item for item in items if item['path'] == row['target']]
        if not selected:
            continue
        code = Path(mount['source']).read_text()
        module = Module(row['target'], code, ast.parse(code))
        for node in ast.walk(module.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for item in selected:
                    if item['test_name'] == node.name:
                        result.append(dict(item=item, span=module.span(node)))
    return result


def identity(event, known_owners, role):
    span = event.get('q_span', {})
    matches = [row for row in known_owners if row['span']['path'] == span.get('path')
               and row['span']['start_byte'] <= span.get('start_byte', -1)
               and span.get('end_byte', -1) <= row['span']['end_byte']]
    if len(matches) != 1:
        return None
    item = matches[0]['item']
    value = item['base_test_id'] if role == 'control' else item['candidate_id']
    return dict(representative=role + ':' + value, emitted_test=item)


def replay_case(case, selected, representatives):
    frontier = Frontier(representatives)
    observations, retained = [], []
    totals = Counter()
    baseline_keys = set()
    # Every control is registered first. Generated groups and trace lines then
    # preserve the already completed execution order. No source-profile events
    # are needed to establish the new projection's control baseline.
    for role in ['control', 'generated']:
        for selection in selected:
            known_owners = owners(selection, role)
            directory = Path(selection['output']) / 'execution' / role
            for located in traces(directory, 'observed_writes.jsonl'):
                event = located['event']
                if event['kind'] != 'assertion_read':
                    continue
                owner = identity(event, known_owners, role)
                representative = (owner['representative'] if owner else
                    'unbound_event:' + located['trace'] + '#' + str(located['trace_line']))
                state = frontier.observe(event, representative)
                entry = dict(**located, case=case, group=selection['group'], role=role,
                             owner=owner, result=state)
                observations.append(entry)
                totals[role + '_read_events'] += 1
                totals[role + '_' + state['status']] += 1
                totals[role + '_new_states'] += state['new']
                if not owner:
                    totals[role + '_unresolved_owner'] += 1
                if state['retained']:
                    retained.append(entry)
                if role == 'control' and state['key']:
                    baseline_keys.add(state['key'])
    snapshot = frontier.snapshot()
    restored = Frontier.restore(snapshot)
    for located in observations:
        owner = located['owner']
        representative = (owner['representative'] if owner else
            'unbound_event:' + located['trace'] + '#' + str(located['trace_line']))
        result = restored.observe(located['event'], representative)
        if result['new'] or result['retained']:
            raise ValueError('Repeated completed replay changed state')
    if restored.snapshot() != snapshot:
        raise ValueError('Checkpoint replay was not idempotent')
    generated_representatives = sorted({r['owner']['representative'] for r in retained
        if r['role'] == 'generated' and r['owner']})
    summary = dict(case=case, groups=len(selected), counters=dict(totals),
        control_state_count=len(baseline_keys), state_count=len(frontier.states),
        representative_count=sum(len(row['representatives']) for row in frontier.states.values()),
        retained_generated_candidates=len(generated_representatives),
        generated_representatives=generated_representatives,
        checkpoint_replay_idempotent=True, correctness_evaluated=False)
    return summary, observations, retained, snapshot


def old_phase_comparison(case, selected):
    full, reduced, baseline_reduced = set(), set(), set()
    records = []
    counts = Counter()
    for role in ['source_profile', 'generated']:
        for selection in selected:
            directory = Path(selection['output']) / 'execution' / role
            for located in traces(directory, 'relation_trace.jsonl'):
                event = located['event']
                if not _observed_roles(event):
                    counts[role + '_unknown_events'] += 1
                    continue
                profile = canonical_profile(event)
                key = fingerprint(profile)
                without_phase = fingerprint({k: v for k, v in profile.items() if k != 'phase'})
                phase_only_new = key not in full and without_phase in reduced
                phase_only_against_source = key not in full and without_phase in baseline_reduced
                records.append(dict(**located, case=case, group=selection['group'], role=role,
                    canonical_profile=profile, profile_key=key, without_phase_key=without_phase,
                    new_profile=key not in full, new_without_phase=without_phase not in reduced,
                    phase_only_new=phase_only_new, phase_only_against_source=phase_only_against_source))
                counts[role + '_observed_events'] += 1
                counts[role + '_new_profiles'] += key not in full
                counts[role + '_new_without_phase'] += without_phase not in reduced
                counts[role + '_phase_only_new'] += phase_only_new
                counts[role + '_phase_only_against_source'] += phase_only_against_source
                full.add(key)
                reduced.add(without_phase)
                if role == 'source_profile':
                    baseline_reduced.add(without_phase)
    return dict(case=case, counters=dict(counts), total_profiles=len(full),
                profiles_ignoring_phase=len(reduced)), records


def run(execution, output, representatives):
    seal = read(execution / 'seal.json')
    for relative, checksum in seal['files_sha256'].items():
        if digest(execution / relative) != checksum:
            raise ValueError('Execution evidence changed')
    protocol = read(execution / 'protocol.json')
    output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for case in sorted({row['case'] for row in protocol['selected']}):
        selected = [row for row in protocol['selected'] if row['case'] == case]
        summary, observations, retained, snapshot = replay_case(case, selected, representatives)
        old, old_records = old_phase_comparison(case, selected)
        summary['old_profile_phase_comparison'] = old
        summaries.append(summary)
        write(output / case / 'observations.json', observations)
        write(output / case / 'retained.json', retained)
        write(output / case / 'frontier.json', snapshot)
        write(output / case / 'old_profiles.json', old_records)
    write(output / 'summary.json', summaries)
    code = [Path(__file__), ROOT / 'experimental/observed_write_frontier.py',
            ROOT / 'relation_search/frontier.py']
    write(output / 'protocol.json', dict(
        input_execution=str(execution.resolve()), input_seal_sha256=digest(execution / 'seal.json'),
        verified_execution_files=len(seal['files_sha256']),
        representative_limit=representatives,
        new_replay_order='all controls first, then generated groups in frozen execution order and events in JSONL order; separate frontier per case',
        old_replay_order='all source-profile traces first, then generated groups/events in frozen execution order',
        old_comparison='Existing canonical_profile unchanged, compared with exactly its phase field omitted, on the same old trace events.',
        comparability_limit='New and old probes have different observation coverage and representations; counts are not a controlled search ablation or bug metric.',
        parent_eligibility_evaluated=False, correctness_evaluated=False,
        code_sha256={str(p.relative_to(ROOT)): digest(p) for p in code}))
    write(output / 'seal.json', dict(files_sha256={str(p.relative_to(output)): digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--execution', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--representatives', type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(run(args.execution, args.output, args.representatives), sort_keys=True))
