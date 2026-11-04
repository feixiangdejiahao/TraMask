#!/usr/bin/env python3
"""Measure port-backed admission before joining held-out manual relations."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from eviweave.artifacts import read_json, write_json
from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph
from eviweave.port_admission import PortAdmissionIndex, admission_groups, admission_seed, admission_witnesses, endpoint_operations
from eviweave.relational_alignment import RelationalAlignmentIndex, view_pair_masks as pair_masks
from verify_pre_slice_five_pilot import FR, original_sources

FROZEN = ROOT/'results/behavioral_masking/20261104_port_relation_current_f_n88_r02'
EXPECT = ROOT/'research/behavior_alignment_pilot_20261104/alignment_expectations.json'


def compressed(path):
    with gzip.open(path, 'rt') as handle:
        return json.load(handle)


def locations(index, views, source, a, b):
    """Select exact/contained operations before considering an outer operand."""
    keys = endpoint_operations(index, source, a, b)
    result = set()
    for v in views:
        if v['source'] != source:
            continue
        if any(index.operations[key]['statement'] in v['nodes'] for key in keys):
            result.add(v['id'])
    return result


def linked(left, right, masks):
    return any(masks.get(v, 0) & sum(1 << w for w in right - {v}) for v in left)


def evaluate(case, index, views, originals, masks, records):
    sid = case['screen_id']
    expected = []
    by_key = defaultdict(list)
    for record in records:
        by_key[record['key']].append(record)
    for r in read_json(EXPECT)['expectations']:
        if r['case'] != sid:
            continue
        sides = [locations(index, views, r[side]['source'], r[side]['start'], r[side]['end'])
                 if r[side] is not None else set() for side in ['left', 'right']]
        ops = [endpoint_operations(index, r[side]['source'], r[side]['start'], r[side]['end'])
               if r[side] is not None else set() for side in ['left', 'right']]
        pair_records = [(a, b) for ak in ops[0] for bk in ops[1] for a in by_key[ak] for b in by_key[bk]]
        same_port = any(a['roles'] & b['roles'] for a, b in pair_records)
        anchored_port = any(a['anchor'] and a['roles'] & b['roles'] for a, b in pair_records)
        connected_port = any(a['flow_anchor'] and a['roles'] & b['roles'] for a, b in pair_records)
        direct_decisions = {}
        for mode in ['edge', 'receiver', 'two_edge', 'shape', 'connected', 'observed', 'subject']:
            direct_decisions[mode] = any(admission_seed(a, mode) and
                admission_witnesses(a, mode) & admission_witnesses(b, mode) and
                (a['exact'] != b['exact'] or admission_witnesses(a, mode) != admission_witnesses(b, mode))
                for a, b in pair_records)
        exact_endpoints = [any(index.operations[k]['expression_range'] == [r[side]['start'], r[side]['end']]
                               for k in ops[n]) if r[side] is not None else False
                           for n, side in enumerate(['left', 'right'])]
        expected.append({'id': r['id'], 'status': r['expected']['status'],
                         'left_views': len(sides[0]), 'right_views': len(sides[1]),
                         'direct_endpoint_port_witness': same_port,
                         'anchored_endpoint_port_witness': anchored_port,
                         'connected_endpoint_port_witness': connected_port,
                         'exact_native_operation_endpoints': exact_endpoints,
                         'direct_admission': direct_decisions,
                         'already_in_one_view': bool(sides[0] & sides[1]),
                         'arms': {name: linked(*sides, m) or bool(sides[0] & sides[1])
                                  for name, m in masks.items()}})
    # Independent evaluation references: exact fragments from required factors.
    # They are never read until feature generation and candidate masks finish.
    doc = read_json(FR/'observation/adjudicated'/f'{sid}.json')
    inventory = doc.get('required_factor_inventory', [])
    cache = {}

    def fragment_views(fragment):
        # The frozen adjudications contain two explicitly named source fields.
        literal = (fragment['code'] if 'code' in fragment else fragment['literal_fragment']).strip().encode()
        if literal in cache:
            return cache[literal]
        found = set()
        for source, (_, raw) in originals.items():
            if source not in index.sources:
                continue
            start = raw.find(literal)
            while start != -1:
                found.update(locations(index, views, source, start, start+len(literal)))
                start = raw.find(literal, start+1)
        cache[literal] = found
        return found

    base = set()
    for f in inventory:
        if f['present_in_base']:
            for fragment in f.get('source_fragments', []):
                base.update(fragment_views(fragment))
    factors = []
    for f in doc['missing_factors']:
        donor = set()
        for fragment in f['source_fragments']:
            donor.update(fragment_views(fragment))
        factors.append({'factor': f['factor_id'], 'role': f['role'],
                        'base_views': len(base), 'donor_views': len(donor),
                        'already_in_one_view': bool(base & donor),
                        'arms': {name: linked(base, donor, m) or bool(base & donor)
                                 for name, m in masks.items()}})
    return expected, factors


def run_case(job):
    case, out = job
    sid = case['screen_id']; started = time.perf_counter()
    frozen = FROZEN/'cases'/sid
    data = compressed(frozen/'domains.json.gz'); slices = compressed(frozen/'slices.json.gz')
    originals = original_sources(case)
    sources, selected, bodies, views = {}, {}, {}, []
    for source, record in slices.items():
        path, raw = originals[source]
        assert hashlib.sha256(raw).hexdigest() == record['sha256']
        graph = SourceGraph({'id': source, 'path': path, 'raw': raw})
        sources[source] = graph, BehaviorIndex(graph)
        selected[source] = {n for v in record['views'] for f in v['files'] for n in f['nodes']+f['context_nodes']}
    anchors = defaultdict(set)
    for g in data['groups']:
        for v, operation in g['anchors']:
            anchors[v].add((data['views'][v]['source'], operation))
    for v in data['views']:
        record = slices[v['source']]['views'][v['original_view']]
        body = json.dumps({k: x for k, x in record.items() if k != 'entries'}, sort_keys=True)
        identity = bodies.setdefault(body, len(bodies))
        views.append({'id': identity, 'source': v['source'],
                      'nodes': {n for f in record['files'] for n in f['nodes']+f['context_nodes']},
                      'anchors': anchors[v['id']]})
    # Merge aliases before feature extraction; retain the union of their seeds.
    unique = {}
    for v in views:
        if v['id'] in unique:
            unique[v['id']]['anchors'].update(v['anchors'])
        else:
            unique[v['id']] = v
    views = list(unique.values())
    index = PortAdmissionIndex(sources, selected)
    records = [r for view in views for r in index.view_features(view)]
    masks, counts = {}, {}
    # Rebuild the old decision rule with the corrected deterministic syntax.
    old = RelationalAlignmentIndex(sources, selected)
    groups, domains = old.grouped_view_domains(views)
    masks['old'], _ = pair_masks(groups, domains)
    for mode in ['edge', 'receiver', 'two_edge', 'shape', 'connected', 'observed', 'subject']:
        groups, domains = admission_groups(records, mode)
        mask, work = pair_masks(groups, domains)
        if mode == 'shape':
            # Concrete scalar alternatives remain candidates; only comparisons
            # are shared. No literal-equality class is declared equivalent.
            mask = masks['edge'].copy()
        masks[mode] = mask
        counts[mode] = {'slice_pairs': sum(m.bit_count() for m in mask.values()),
                        'profile_groups': len(groups), 'witness_bucket_comparisons': work,
                        'within_template_parameter_domains': sum(len(g['exact_signatures']) > 1 for g in groups)}
    # Different operation names can meet through an observed output/input edge.
    provided = defaultdict(list)
    for r in records:
        for role, other in r['outputs']:
            if other[0] == r['key'][0]:
                provided[index.descriptor(other), role, r['interface']].append(r)
    supply = defaultdict(int)
    for r in records:
        if not r['anchor']:
            continue
        for direction, role, provider in [(w[1], w[2], w[3]) for w in r['roles'] if len(w) == 4]:
            if direction != 'inputs' or role == 'callee':
                continue
            for p in provided[r['interface'], role, provider]:
                if p['view'] != r['view']:
                    supply[r['view']] |= 1 << p['view']
    masks['edge_supply'] = {v: masks['edge'].get(v, 0) | supply.get(v, 0) for v in masks['edge'].keys() | supply.keys()}
    directory = out/'cases'/sid
    write_json(directory/'candidate_counts.json', counts)
    # Freeze candidate decisions before evaluator reads any manual annotation.
    write_json(directory/'pair_masks.json', {name: {str(v): hex(m) for v, m in mm.items()} for name, mm in masks.items()})
    expected, factors = evaluate(case, index, views, originals, masks, records)
    write_json(directory/'expected_pairs.json', expected); write_json(directory/'factor_sources.json', factors)
    examples = []
    for r in records:
        if r['anchor'] and r['roles'] and len(examples) < 12:
            op = index.operations[r['key']]; graph = sources[r['key'][0]][0]
            a, b = op['expression_range']
            examples.append({'source': r['key'][0], 'range': [a, b], 'text': graph.raw[a:b].decode()[:800],
                             'roles': sorted(r['roles'], key=repr), 'definitions': r['definitions']})
    write_json(directory/'witness_examples.json', examples)
    row = {'case': sid, 'task': case['task'], 'views': len(views), 'operation_records': len(records),
           'old_pairs': sum(m.bit_count() for m in masks['old'].values()), 'arms': counts,
           'edge_supply_pairs': sum(m.bit_count() for m in masks['edge_supply'].values()),
           'records_without_port_witness': sum(not r['roles'] for r in records),
           'tracking_edges': dict(index.tracking_counts), 'seconds': time.perf_counter()-started}
    write_json(directory/'metrics.json', row)
    print(sid, row['old_pairs'], counts['edge']['slice_pairs'], counts['receiver']['slice_pairs'], round(row['seconds'], 1), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+'); parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True)
    cases = read_json(FR/'cases.json')['cases']
    if args.cases:
        cases = [c for c in cases if c['screen_id'] in args.cases]
    write_json(out/'protocol.json', {'case_ids': [c['screen_id'] for c in cases],
        'input': str(FROZEN), 'algorithm_inputs': 'source bytes, F coordinates, D anchors; no human labels',
        'arms': ['old', 'edge', 'receiver', 'two_edge', 'shape', 'connected', 'observed', 'subject', 'edge_supply'],
        'new_model_calls': 0, 'new_task_executions': 0})
    code = out/'code'; code.mkdir()
    for name in ['scripts/pilot_port_admission.py', 'src/eviweave/port_admission.py', 'src/eviweave/relations.py']:
        (code/Path(name).name).write_bytes((ROOT/name).read_bytes())
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(run_case, [(c, out) for c in cases]))
    write_json(out/'counts.json', rows)
    summary = {'cases': len(rows), 'tasks': len({r['task'] for r in rows}),
               'old_pairs': sum(r['old_pairs'] for r in rows),
               'edge_supply_pairs': sum(r['edge_supply_pairs'] for r in rows), 'arms': {}}
    for arm in rows[0]['arms']:
        summary['arms'][arm] = {k: sum(r['arms'][arm][k] for r in rows) for k in rows[0]['arms'][arm]}
    write_json(out/'summary.json', summary); print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
