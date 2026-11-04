#!/usr/bin/env python3
"""Compare fixed representatives with source-version-preserving material containers."""
import argparse
from bisect import bisect_left
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import reduce
import gzip
import json
from operator import or_
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from eviweave.artifacts import read_json, write_json
from pilot_port_admission import compressed, FROZEN
from prepare_cluster_material_review import QUERIES, FR

AUDIT = ROOT / 'results/behavioral_masking/20261105_cluster_material_review_n16_r01'
POLICIES = ['first', 'shortest', 'largest', 'source_containment']


def read_views(sid):
    domains = compressed(FROZEN / 'cases' / sid / 'domains.json.gz')
    slices = compressed(FROZEN / 'cases' / sid / 'slices.json.gz')
    bodies, views = {}, {}
    for entry in domains['views']:
        row = slices[entry['source']]['views'][entry['original_view']]
        body = json.dumps({k: v for k, v in row.items() if k != 'entries'}, sort_keys=True)
        identity = bodies.setdefault(body, len(bodies))
        assert all(f['material'] == entry['source'] for f in row['files'])
        ranges = [r for f in row['files'] for r in f['ranges']]
        views[identity] = {'source': entry['source'], 'ranges': ranges,
                           'bytes': sum(b-a for a, b in ranges)}
    return views


def atom_masks(views):
    boundaries = defaultdict(set)
    for view in views.values():
        boundaries[view['source']].update(x for span in view['ranges'] for x in span)
    boundaries = {source: sorted(xs) for source, xs in boundaries.items()}
    masks = {}
    for identity, view in views.items():
        points = boundaries[view['source']]
        mask = 0
        for a, b in view['ranges']:
            start, end = bisect_left(points, a), bisect_left(points, b)
            mask |= ((1 << (end-start)) - 1) << start
        masks[identity] = mask
    return masks


def policies_for(views, masks, members):
    result = {name: {} for name in POLICIES}
    for cluster, occurrences in members.items():
        ids = sorted({v for v, _, _ in occurrences})
        result['first'][cluster] = [ids[0]]
        result['shortest'][cluster] = [min(ids, key=lambda v: (views[v]['bytes'], v))]
        result['largest'][cluster] = [min(ids, key=lambda v: (-views[v]['bytes'], v))]
        by_source = defaultdict(list)
        for v in ids:
            by_source[views[v]['source']].append(v)
        representatives = []
        for source_ids in by_source.values():
            kept = []
            for v in sorted(source_ids, key=lambda v: (-masks[v].bit_count(), v)):
                if not any(masks[v] & ~masks[w] == 0 for w in kept):
                    kept.append(v)
            assert reduce(or_, (masks[v] for v in source_ids), 0) == reduce(or_, (masks[v] for v in kept), 0)
            representatives.extend(kept)
        result['source_containment'][cluster] = sorted(representatives)
    return result


def audit_package(receipt, selection, views):
    # This is preservation of a manually inspected package, not task recall:
    # other material packages may also suffice for the same task.
    retained = defaultdict(list)
    for cluster in map(str, receipt['candidate']):
        for identity in selection[cluster]:
            view = views[identity]
            retained[view['source']].extend(view['ranges'])
    checks = []
    for citation in receipt['verified_materials']:
        a, b = citation['range']
        intervals = sorted(retained[citation['source']])
        cursor = a
        for start, end in intervals:
            if start <= cursor:
                cursor = max(cursor, end)
        checks.append(cursor >= b)
    return checks


def run_case(job):
    case, out = job
    sid = case['screen_id']
    views = read_views(sid)
    members = compressed(QUERIES / 'cases' / sid / 'memberships.json.gz')['ports']
    edges = compressed(QUERIES / 'cases' / sid / 'cluster_pairs.json.gz')['original']['ports']
    masks = atom_masks(views)
    selections = policies_for(views, masks, members)
    directory = out / 'cases' / sid
    directory.mkdir(parents=True)
    # The four selections are fixed before reading the manual review.
    with gzip.open(directory / 'selections.json.gz', 'wt') as handle:
        json.dump(selections, handle, separators=(',', ':'))
    counts = {}
    for policy, selected in selections.items():
        counts[policy] = {'material_view_references': sum(map(len, selected.values())),
                          'material_bytes_referenced': sum(views[v]['bytes'] for vs in selected.values() for v in vs),
                          'distinct_material_views': len({v for vs in selected.values() for v in vs})}
    before = {c: sorted({v for v, _, _ in rs}) for c, rs in members.items()}
    row = {'case': sid, 'classes': len(members), 'queries': len(edges),
           'same_class_queries': sum(a == b for a, b in edges),
           'before': {'material_view_references': sum(map(len, before.values())),
                      'material_bytes_referenced': sum(views[v]['bytes'] for vs in before.values() for v in vs),
                      'distinct_material_views': len({v for vs in before.values() for v in vs})},
           'policies': counts, 'source_union_preserved_for_every_class': True}
    receipt_path = AUDIT / 'cases' / sid / 'manual_review.json'
    sample_ids = read_json(AUDIT / 'protocol.json')['sample_order']
    if sid in sample_ids:
        receipt = read_json(receipt_path)
        row['sample_verdict'] = receipt['verdict']
        row['package_checks'] = {policy: audit_package(receipt, selection, views)
                                 for policy, selection in selections.items()}
    write_json(directory / 'counts.json', row)
    print(sid, row['before']['material_view_references'], counts['source_containment']['material_view_references'], flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--workers', default=4, type=int)
    args = parser.parse_args()
    out = args.out.resolve()
    cases = read_json(FR / 'cases.json')['cases']
    write_json(out / 'protocol.json', {'cases': [c['screen_id'] for c in cases], 'input': str(QUERIES),
               'policies': POLICIES, 'selection_inputs': 'source-version ids, view ranges, class membership; no manual labels',
               'evaluation': 'byte preservation of fixed manually reviewed packages; not semantic task recall',
               'preservation': 'original member/condition rows stay; containing views are material containers, not equivalent behaviors',
               'source_channel_recovery': 'not applied in this pilot'})
    (out / 'pilot.py').write_bytes(Path(__file__).read_bytes())
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(run_case, [(case, out) for case in cases]))
    write_json(out / 'case_counts.json', rows)
    totals = {key: sum(r['before'][key] for r in rows) for key in rows[0]['before']}
    sample = [r for r in rows if 'sample_verdict' in r and r['sample_verdict'] == 'material_sufficient']
    summary = {'cases': len(rows), 'classes': sum(r['classes'] for r in rows),
               'queries': sum(r['queries'] for r in rows), 'same_class_queries': sum(r['same_class_queries'] for r in rows),
               'before': totals,
               'policies': {policy: {key: sum(r['policies'][policy][key] for r in rows) for key in totals}
                            for policy in POLICIES},
               'positive_manual_packages': len(sample),
               'package_preservation': {policy: {'complete_packages': sum(all(r['package_checks'][policy]) for r in sample),
                                               'citations': sum(sum(r['package_checks'][policy]) for r in sample),
                                               'failed_packages': [r['case'] for r in sample if not all(r['package_checks'][policy])]}
                                        for policy in POLICIES},
               'all_class_source_unions_preserved': all(r['source_union_preserved_for_every_class'] for r in rows),
               'meaning': 'material containers and query counts; no generated-test or full-task-recall claim'}
    write_json(out / 'summary.json', summary)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
