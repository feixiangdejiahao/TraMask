#!/usr/bin/env python3
"""Compare integrated algorithms with every frozen 88-case output."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from eviweave.artifacts import read_json, write_json
from eviweave.behavior_clusters import observed_fields
from comparison_audit import difference_domains, partition_records
from eviweave.comparison import PARTITIONS, query_partitions
from eviweave.slice_behavior import read_behavior_graph
from pilot_behavior_deltas import FR, load_case

BASE = ROOT / 'results/behavioral_masking'
CLUSTERS = BASE / '20261105_behavior_clusters_n88_r10'
QUERIES = BASE / '20261105_behavior_cluster_queries_n88_r02'
DELTAS = BASE / '20261105_behavior_deltas_n88_r04'


def verify_case(job):
    case, out = job
    sid = case['screen_id']
    started = time.perf_counter()
    index, records, views = load_case(case)
    fields = observed_fields((FR / 'public_inputs' / sid / 'patch.diff').read_text())
    result = partition_records(index, records, views, fields)
    query_started = time.perf_counter()
    queries = query_partitions(index, records, views, fields, modes=PARTITIONS)
    query_seconds = time.perf_counter() - query_started
    memberships = read_behavior_graph(CLUSTERS / 'cases' / sid / 'memberships.json.gz')
    pairs = read_behavior_graph(CLUSTERS / 'cases' / sid / 'cluster_pairs.json.gz')
    metrics = read_json(CLUSTERS / 'cases' / sid / 'metrics.json')
    lifted = read_behavior_graph(QUERIES / 'cases' / sid / 'cluster_pairs.json.gz')['original']
    for mode in PARTITIONS:
        actual = {str(c): [list(member) for member in sorted(rows)]
                  for c, rows in result['memberships'][mode].items()}
        assert actual == memberships[mode], (sid, mode, 'memberships')
        for kind in ('admitted', 'original'):
            assert [list(pair) for pair in sorted(result['cluster_pairs'][kind][mode])] == pairs[kind][mode], (sid, mode, kind)
        # The frozen run predates the later input-property fact representation;
        # relational_requests counts that vocabulary, rather than candidates.
        for key in ('clusters','cluster_pairs','full_domain_cluster_pairs','mapped_old_subpairs','same_cluster_old_subpairs'):
            value = metrics['arms'][mode][key]
            assert result['metrics']['arms'][mode][key] == value, (sid, mode, key)
        assert queries['memberships'][mode] == result['memberships'][mode], (sid, mode, 'query_memberships')
        assert queries['cluster_pairs']['original'][mode] == result['cluster_pairs']['lifted'][mode], (sid, mode, 'class_level_queries')
    for mode in ('ports', 'relations'):
        assert [list(pair) for pair in sorted(result['cluster_pairs']['lifted'][mode])] == lifted[mode], (sid, mode, 'lifted')
    differences = difference_domains(index, records)
    expected = read_json(DELTAS / 'cases' / sid / 'metrics.json')
    for key, value in differences['metrics'].items():
        assert value == expected[key], (sid, key)
    assert sum(mask.bit_count() for mask in differences['view_pairs'].values()) == expected['fixed_admitted_slice_pairs']
    row = {'case': sid, 'task': case['task'], 'language': case['language'],
           'occurrences': len(records), 'all_four_partitions_equal': True,
           'admitted_and_original_pairs_equal': True, 'lifted_pairs_equal': True,
           'difference_domains_equal': True,
           'class_level_queries_equal': True,'query_seconds': query_seconds,
           'ports_query_pairs': len(result['cluster_pairs']['lifted']['ports']),
           'seconds': time.perf_counter() - started}
    write_json(out / 'cases' / sid / 'verification.json', row)
    print(sid, row['ports_query_pairs'], round(row['seconds'], 2), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True)
    cases = read_json(FR / 'cases.json')['cases']
    write_json(out / 'protocol.json', {'cases': [c['screen_id'] for c in cases],
               'cluster_baseline': str(CLUSTERS), 'query_baseline': str(QUERIES), 'delta_baseline': str(DELTAS),
               'checks': 'All memberships, directed pairs, cluster-domain metrics and local-difference domain counts; direct class queries equal the old-profile union. Historical relational_requests used an earlier fact vocabulary and is recorded separately.',
               'new_llm_calls': 0, 'new_native_replays': 0})
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(verify_case, [(case, out) for case in cases]))
    write_json(out / 'summary.json', {'cases': len(rows), 'all_equal': True,
               'ports_query_pairs': sum(r['ports_query_pairs'] for r in rows),
               'occurrences': sum(r['occurrences'] for r in rows),
               'languages': sorted({r['language'] for r in rows})})


if __name__ == '__main__':
    main()
