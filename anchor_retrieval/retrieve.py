"""Patch → observed production location → assertion → unvaried input bindings."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import time
from pathlib import Path

from .index import Index
from .frontier import ObservationFrontier, rank_frontier
from .syntax import canonical, is_test_path, json_safe, load_sources

STRONG_RESOLUTION = {'local_symbol', 'import_symbol', 'constructor', 'receiver_type',
                     'package_symbol', 'fixture', 'literal_registered_dispatch'}


def call_input_bindings(index, flow, calls):
    from .syntax import literal
    bindings = collections.defaultdict(set)
    raw_values = set()
    for call in calls:
        for i, arg in enumerate(call.args):
            values = set(arg.constants)
            for n in flow.slice([arg.id]):
                node = flow.nodes[n]
                if node['kind'] == 'literal':
                    try:
                        values.add(canonical(literal(node['text'])))
                    except ValueError:
                        pass
                if node['kind'] == 'parameter':
                    values.update(canonical(v) for v in flow.unit.parameter_values.get(node.get('parameter'), []))
            raw_values.update(values)
            for target, reason in call.targets:
                callee = index.units[target]
                if reason not in STRONG_RESOLUTION or callee.test:
                    continue
                params = [p for p in callee.params if p not in {'self', 'cls'}]
                if reason == 'literal_registered_dispatch':
                    if i == 0:
                        continue
                    position = i - 1
                else:
                    position = i
                if is_test_path(callee.source.path):
                    # A helper formal can feed an argument of a real production call.
                    if position >= len(params):
                        continue
                    formal = params[position]
                    helper = index.flow(target)
                    for inner in helper.calls:
                        for j, argument in enumerate(inner.args):
                            dependencies = helper.slice([argument.id])
                            if not any(helper.nodes[n].get('parameter') == formal for n in dependencies):
                                continue
                            for dst, dst_reason in inner.targets:
                                dest = index.units[dst]
                                if dst_reason not in STRONG_RESOLUTION or is_test_path(dest.source.path):
                                    continue
                                dest_params = [p for p in dest.params if p not in {'self', 'cls'}]
                                dest_slot = dest_params[j] if j < len(dest_params) else f'arg{j}'
                                bindings[f'{dst}#param:{dest_slot}'].update(values)
                    continue
                slot = params[position] if position < len(params) else f'arg{position}'
                if values:
                    bindings[f'{target}#param:{slot}'].update(values)
    for key, values in index.regex_bindings(raw_values).items():
        bindings[key].update(values)
    return bindings


def make_anchors(index: Index):
    records, duplicates = [], collections.defaultdict(list)
    frontier = ObservationFrontier(index)
    index.input_donors = []
    all_tests = [u for u in index.units.values() if u.test]
    # Prefer the final repository copy; retain historical provenance separately.
    ordered = sorted(all_tests, key=lambda u: (u.source.origin != 'repository', u.id))
    unique = {}
    for unit in ordered:
        fp = (unit.fingerprint, unit.source.type_only)
        if fp not in unique:
            unique[fp] = unit
        duplicates[fp].append({'path': unit.source.path, 'line': unit.line,
                               'step': unit.source.step, 'origin': unit.source.origin})
    type_only = 0
    no_oracle = 0
    excluded_editor = 0
    for unit in unique.values():
        if unit.source.type_only:
            type_only += 1
            continue
        flow = index.flow(unit.id)
        donor_bindings = call_input_bindings(index, flow, flow.calls)
        if donor_bindings:
            index.input_donors.append({'id': unit.id + ':inputs', 'test_id': unit.id,
                                      'origin': unit.source.origin, 'setup_lines': [],
                                      'bindings': {k: sorted(v) for k, v in donor_bindings.items()}})
        if not flow.assertions:
            no_oracle += 1
        for assertion in flow.assertions:
            sliced = flow.slice([assertion.node])
            calls = [c for c in flow.calls if c.node in sliced]
            affected, reached, witnesses, unresolved = {}, set(), [], []
            truncated = False
            production_roots = set()
            for call in calls:
                if not call.targets:
                    unresolved.append(call.name)
                for target, reason in call.targets:
                    reach = index.reach(target)
                    reached.update(reach['seen'])
                    truncated |= reach['truncated']
                    for changed, path in reach['changed'].items():
                        chain = [(unit.id, flow.nodes[call.node]['line'], target, reason)] + list(path)
                        if changed not in affected or len(chain) < len(affected[changed]):
                            affected[changed] = chain
                    targetunit = index.units[target]
                    if not is_test_path(targetunit.source.path) and targetunit.source.origin == 'repository':
                        production_roots.add(target)
            # Editing guards have no behavioral API provenance. Keep their exclusion explicit.
            editor = unit.name == '<script>' and not affected and any(
                'content' in n.get('text', '') and n['kind'] in {'read', 'definition'} for n in (flow.nodes[i] for i in sliced))
            if editor:
                excluded_editor += 1
                continue
            typed_fields = collections.defaultdict(set)
            for n in sliced:
                node = flow.nodes[n]
                if node['kind'] == 'field_read':
                    typed_fields[node['field']].update(node.get('receiver_types', []))
            fields = index.field_witnesses(assertion.fields, reached, typed_fields)
            field_factors = set()
            for w in fields:
                field_factors.update(index.field_factors(w['symbol'], w['field']))
            bindings = call_input_bindings(index, flow, calls)
            # The donor index retains all inputs; an anchor uses only its projected groups.
            bindings = {k: v for k, v in bindings.items() if '#group:' not in k or k in field_factors}
            if fields:
                # Field-sensitive regex projection is more precise than a whole string argument.
                projected = {k: v for k, v in bindings.items() if '#group:' in k}
                if projected:
                    bindings = collections.defaultdict(set, projected)
            ordered_impact = sorted(affected, key=lambda k: (len(affected[k]), k))
            strongest = 0
            for symbol in ordered_impact:
                chain = affected[symbol]
                exact = all(edge[3] in STRONG_RESOLUTION for edge in chain)
                strongest = max(strongest, 2 if exact else 1)
                if len(witnesses) < 6:
                    witnesses.append({'changed_symbol': symbol, 'resolution': 'resolved' if exact else 'may_call',
                                      'chain': [{'caller': e[0], 'line': e[1], 'callee': e[2], 'kind': e[3]} for e in chain]})
            if fields:
                observation = '|'.join(sorted({f"{w['owner']}.{w['field']}" for w in fields}))
            else:
                root = ordered_impact[0] if ordered_impact else 'unresolved'
                field = '.'.join(assertion.fields[-2:]) or '$return'
                observation = f'{root}::{field}'
            setup_lines = sorted({flow.nodes[n]['line'] for n in sliced if flow.nodes[n]['kind'] not in {'literal', 'global'}})
            aid = f'{unit.source.path}:{assertion.line}:{unit.name}:{assertion.node}'
            record = {
                'id': aid, 'test_id': unit.id, 'path': unit.source.path, 'name': unit.name,
                'test_line': unit.line, 'line': assertion.line, 'end_line': assertion.end_line,
                'origin': unit.source.origin, 'step': unit.source.step,
                'source_version': 'final_candidate' if unit.source.origin == 'repository' else 'historical_script_analyzed_against_final_candidate_unexecuted',
                'assertion': assertion.text, 'observed': assertion.observed,
                'predicate': assertion.predicate, 'expected': assertion.expected,
                'incidental': assertion.incidental, 'observation': observation,
                'field_witnesses': fields, 'impact_witnesses': witnesses,
                'impact_symbols': ordered_impact, 'resolution_strength': strongest,
                'unresolved_calls': sorted(set(unresolved)), 'reach_truncated': truncated,
                'setup_lines': setup_lines, 'slice_nodes': len(sliced),
                'bindings': {k: sorted(v) for k, v in sorted(bindings.items())},
                'parameter_rows': json_safe(unit.parameter_rows),
                'provenance': duplicates[unit.fingerprint, unit.source.type_only],
                'changed_test': bool(index.changed_lines.get(unit.source.path, set()) & set(range(unit.line, unit.body.end_point.row + 2))),
                'changed_assertion': bool(index.changed_lines.get(unit.source.path, set()) & set(range(assertion.line, assertion.end_line + 1))),
                'calls': sorted({c.name for c in calls}),
                'input_gap_candidates': [],
            }
            frontier.annotate(flow, assertion, record)
            records.append(record)
    return records, {'test_units': len(all_tests), 'unique_test_units': len(unique),
                     'type_only_units_excluded': type_only, 'no_direct_or_helper_oracle': no_oracle,
                     'editor_assertions_excluded': excluded_editor}


def annotate_gaps(records, donors=None):
    """Inverted input index: no quadratic all-test-pair construction."""
    inputs = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in donors if donors is not None else records:
        for slot, values in row['bindings'].items():
            for value in values:
                inputs[slot][value].append(row)
    for row in records:
        for slot, checked in row['bindings'].items():
            available = inputs[slot]
            novel = sorted(set(available) - set(checked))
            if not novel:
                continue
            donors = []
            for value in novel[:4]:
                candidates = sorted((d for d in available[value] if d['test_id'] != row['test_id']),
                                    key=lambda d: (d['origin'] != 'repository', len(d['setup_lines']), d['id']))
                if candidates:
                    donors.append({'value': value, 'anchor_id': candidates[0]['id'], 'test_id': candidates[0]['test_id']})
            if donors:
                row['input_gap_candidates'].append({'slot': slot, 'observed_values': checked, 'donors': donors})
    return len(inputs)


def priority(row, use_gaps=True):
    gaps = row['input_gap_candidates'] if use_gaps else []
    default_gaps = sum(any(v in {'null', '""', '0', 'false', '[]'} for v in g['observed_values']) for g in gaps)
    return (int(not row['incidental']), int(bool(row['field_witnesses'])),
            int(bool(gaps)), min(default_gaps, 4), min(len(gaps), 8),
            min(len(row['impact_symbols']), 4), row['resolution_strength'],
            -len(row['setup_lines']), -row['slice_nodes'])


def rank(records, variant='full', patch=''):
    if variant == 'legacy_keywords':
        import re
        identifiers = set(re.findall(r'\b[A-Za-z_]\w{3,}\b', '\n'.join(
            s[1:] for s in patch.splitlines() if s.startswith('+') and not s.startswith('+++'))))
        def key(row):
            score = (200 if row['changed_test'] else 0) + (100 if row['path'] in re.findall(r'^\+\+\+ b/(.+)$', patch, re.M) else 0)
            score += (15 if row['origin'] == 'trajectory' else 0)
            score += sum(bool(set(re.findall(r'\w+', c)) & identifiers) for c in row['calls'])
            return (-score, row['path'], row['test_line'], row['line'], row['id'])
        return sorted(records, key=key)
    candidates = [r for r in records if r['impact_symbols']]
    key = lambda r: tuple(-v for v in priority(r, variant != 'no_input_gaps')) + (r['path'], r['test_line'], r['line'], r['id'])
    if variant == 'no_diversity':
        return sorted(candidates, key=key)
    buckets = collections.defaultdict(list)
    for row in candidates:
        buckets[row['observation']].append(row)
    queues = []
    for observation, rows in buckets.items():
        # One representative per test at each pass; retain every assertion eventually.
        rows.sort(key=key)
        seen, first, rest = set(), [], []
        for row in rows:
            (rest if row['test_id'] in seen else first).append(row)
            seen.add(row['test_id'])
        queues.append(collections.deque(first + rest))
    queues.sort(key=lambda q: key(q[0]))
    result = []
    while queues:
        remaining = []
        for queue in queues:
            result.append(queue.popleft())
            if queue:
                remaining.append(queue)
        queues = remaining
    return result


def retrieve(repo: Path, patch_path: Path, language: str, trajectory_path: Path | None = None,
             max_depth=5, max_reachable=160):
    started = time.perf_counter()
    patch = patch_path.read_text()
    trajectory = json.loads(trajectory_path.read_text()) if trajectory_path else None
    sources = load_sources(repo, language, trajectory)
    parsed = time.perf_counter()
    index = Index(sources, patch, max_depth, max_reachable)
    indexed = time.perf_counter()
    records, counts = make_anchors(index)
    analyzed = time.perf_counter()
    slots = annotate_gaps(records, index.input_donors)
    baseline = rank(records, 'legacy_keywords', patch)
    variants = {name: [r['id'] for r in rank(records, name, patch)]
                for name in ('no_input_gaps', 'no_diversity', 'legacy_keywords')}
    variants['legacy_full'] = [r['id'] for r in rank(records, 'full', patch)]
    for name, settings in (
            ('full', {}),
            ('frontier_no_dependencies', {'use_dependencies': False}),
            ('frontier_no_expectation', {'use_expectation': False}),
            ('frontier_no_test_rounds', {'test_rounds': False})):
        variants[name] = [r['id'] for r in rank_frontier(records, baseline, **settings)]
    by_id = {r['id']: r for r in records}
    selections = {}
    for variant in ('full', 'legacy_keywords'):
        selected, seen_tests = [], set()
        for aid in variants[variant]:
            record = by_id[aid]
            if record['test_id'] in seen_tests:
                continue
            seen_tests.add(record['test_id'])
            unit = index.units[record['test_id']]
            selected.append({'rank': len(selected) + 1, 'test_id': unit.id, 'anchor_id': aid,
                             'path': unit.source.path, 'line': unit.line, 'name': unit.name,
                             'code': unit.source.text(unit.node), 'parameter_rows': json_safe(unit.parameter_rows),
                             'note': 'Original source excerpt; imports/fixtures/helpers remain in the source repository.'})
            if len(selected) == 20:
                break
        selections[variant] = selected
    elapsed = time.perf_counter() - started
    result = {
        'algorithm': 'observation_frontier_retrieval_v0.2',
        'settings': {'max_call_depth': max_depth, 'max_reachable_per_entry': max_reachable,
                     'external_model_calls': 0, 'executes_subject_code': False},
        'input_hashes': {'patch_sha256': hashlib.sha256(patch.encode()).hexdigest(),
                         'source_manifest_sha256': hashlib.sha256(canonical(
                             [(s.path, hashlib.sha256(s.data).hexdigest()) for s in sources]).encode()).hexdigest()},
        'counts': {**counts, 'sources': len(sources), 'functions': len(index.units),
                   'changed_production_functions': len(index.changed), 'assertions': len(records),
                   'affected_assertions': sum(bool(r['impact_symbols']) for r in records), 'input_slots': slots,
                   'analyzed_function_bodies': len(index.flows), 'parse_error_sources': len(index.parse_errors),
                   'truncated_anchor_reaches': sum(r['reach_truncated'] for r in records),
                   'field_projected_assertions': sum(bool(r['field_witnesses']) for r in records)},
        'timing_seconds': {'parse': parsed - started, 'index': indexed - parsed,
                           'dependence': analyzed - indexed, 'total': elapsed},
        'parse_error_sources': index.parse_errors,
        'anchors': records, 'rankings': variants, 'selected_tests': selections['full'],
        'baseline_selected_tests': selections['legacy_keywords'],
        'limitations': ['May-dependence, not sound whole-language analysis.',
                        'Observation-footprint inclusion does not imply oracle entailment or fault preservation.',
                        'Dynamic calls are labeled; call expansion is bounded.',
                        'No Tengo guest-language alias/capture semantics or TypeScript closure points-to model.',
                        'No inferred oracle validity; input novelty is a retrieval signal only.',
                        'Historical scripts are not replayed; their past pass status is not transferred.'],
    }
    # Instance-method lru caches otherwise keep complete prior repositories alive.
    index.reach.cache_clear()
    index.module_paths.cache_clear()
    index.field_factors.cache_clear()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--patch', type=Path, required=True)
    parser.add_argument('--language', choices=['python', 'go', 'typescript'], required=True)
    parser.add_argument('--trajectory', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-depth', type=int, default=5)
    parser.add_argument('--max-reachable', type=int, default=160)
    args = parser.parse_args()
    result = retrieve(args.repo, args.patch, args.language, args.trajectory, args.max_depth, args.max_reachable)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=True))
    print(json.dumps({'output': str(args.output), 'counts': result['counts'], 'seconds': result['timing_seconds']['total']}), flush=True)


if __name__ == '__main__':
    main()
