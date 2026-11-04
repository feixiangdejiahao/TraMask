#!/usr/bin/env python3
"""Check the sources, retained byte ranges, and candidate edges in a manual audit."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from eviweave.artifacts import read_json, write_json
from eviweave.pre_slice import covered
from prepare_cluster_material_review import load_views, show_view, compressed, QUERIES, FR

REVIEWS = ROOT / 'research/cluster_material_review_20261105/manual_reviews.json'


def locate(text, raw, ranges):
    needle = text.encode()
    start = raw.find(needle)
    while start != -1:
        end = start + len(needle)
        if covered(start, end, ranges):
            return [start, end]
        start = raw.find(needle, start + 1)
    raise AssertionError(f'Manually cited text is not in the retained payload: {text!r}')


def verify_case(case, review, out):
    sid = case['screen_id']
    sources, views = load_views(case)
    pairs = compressed(QUERIES / 'cases' / sid / 'cluster_pairs.json.gz')['original']['ports']
    memberships = compressed(QUERIES / 'cases' / sid / 'memberships.json.gz')['ports']
    assert review['candidate'] in pairs, (sid, review['candidate'])
    endpoints = []
    for identity, cluster in zip(review['views'], review['candidate']):
        view = views[identity]
        rows = [r for r in memberships[str(cluster)] if r[0] == identity]
        assert rows, (sid, identity, cluster)
        endpoints.append({'view': identity, 'class': cluster, 'source': view['source'],
                          'membership_occurrences': rows})
        path = out / 'cases' / sid / 'inspected_views' / f'{identity}.txt'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(show_view(case, identity))
    citations = []
    for material in review['materials']:
        view = views[material['view']]
        assert material['view'] in review['views']
        raw = sources[view['source']][1]
        span = locate(material['text'], raw, view['ranges'])
        citations.append({**material, 'source': view['source'], 'range': span,
                          'first_line': raw[:span[0]].count(b'\n') + 1})
    receipt = {**review, 'task': case['task'], 'language': case['language'],
               'known_case': case['known_case'], 'candidate_exists': True,
               'endpoints': endpoints, 'verified_materials': citations,
               'view_bytes': {str(v): sum(b-a for a, b in views[v]['ranges']) for v in review['views']}}
    write_json(out / 'cases' / sid / 'manual_review.json', receipt)
    print(sid, review['verdict'], len(citations), 'citations checked', flush=True)
    return receipt


def excluded_materials(cases, out):
    result = []
    by_id = {c['screen_id']: c for c in cases}
    sources, views = load_views(by_id['S010'])
    source = 'H:s113_c0:0025'
    assert source not in {v['source'] for v in views.values()}
    result.append({'case': 'S010', 'source': source, 'path': sources[source][0],
                   'candidate_source_present': False, 'text': sources[source][1].decode()})
    sources, views = load_views(by_id['S057'])
    active = {v['source'] for v in views.values()}
    source = 'F:crates/oxvg_optimiser/src/jobs/collapse_groups.rs'
    assert source not in active
    raw = sources[source][1]
    a = raw.index(b'<!-- Should preserve groups with classes -->')
    b = raw.index(b'</svg>', a) + len(b'</svg>')
    result.append({'case': 'S057', 'source': source, 'range': [a, b],
                   'candidate_source_present': False, 'text': raw[a:b].decode()})
    snapshots = [(source, raw) for source, (path, raw) in sources.items()
                 if 'collapse_groups' in path and path.endswith('.snap')
                 and b'<g class="n">' in raw and b'<g class="i" id="b"/>' in raw]
    assert snapshots
    for source, raw in snapshots:
        assert source not in active
        result.append({'case': 'S057', 'source': source, 'candidate_source_present': False,
                       'text': raw.decode()})
    actions = read_json(FR / 'public_inputs/S015/history.json')['actions']
    action = next(a for a in actions if a['id'] == 's54_c0')
    lines = [line for line in action['observation']['output'].splitlines()
             if line.startswith('background: "red" ->')]
    assert len(lines) == 1 and '"background-color":"red"' in lines[0]
    result.append({'case': 'S015', 'action': 's54_c0', 'channel': 'observation.output',
                   'candidate_payload': 'Source-only frozen views do not attach this output.', 'text': lines[0]})
    write_json(out / 'excluded_materials.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    protocol = read_json(out / 'protocol.json')
    reviews = read_json(REVIEWS)
    population = read_json(FR / 'cases.json')['cases']
    by_task = {}
    for c in population:
        by_task.setdefault(c['task'], []).append(c)
    rng = random.Random(protocol['seed'])
    tasks = rng.sample(sorted(by_task), protocol['sample_size'])
    sample = [rng.choice(sorted(by_task[t], key=lambda c: c['screen_id'])) for t in tasks]
    assert [c['screen_id'] for c in sample] == protocol['sample_order']
    assert [r['case'] for r in reviews] == protocol['sample_order']
    rows = [verify_case(case, review, out) for case, review in zip(protocol['cases'], reviews)]
    excluded_materials(protocol['cases'], out)
    write_json(out / 'manual_reviews.json', rows)
    summary = {'sample_size': len(rows), 'distinct_tasks': len({r['task'] for r in rows}),
               'seed': protocol['seed'], 'language_counts': dict(Counter(r['language'] for r in rows)),
               'verdict_counts': dict(Counter(r['verdict'] for r in rows)),
               'known_cases': [r['case'] for r in rows if r['known_case']],
               'candidate_edges_verified': len(rows),
               'literal_citations_verified': sum(len(r['verified_materials']) for r in rows),
               'model_calls': 0, 'new_generated_tests': 0,
               'question': 'At least one current candidate supplies the missing historical information; combination is deferred.',
               'reviewer': 'Codex manually inspected retained source payloads and alternate materials; scripts only verify coordinates and membership.'}
    write_json(out / 'summary.json', summary)
    with (out / 'cases.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=['case', 'task', 'language', 'verdict', 'candidate', 'views', 'assessment'])
        writer.writeheader()
        writer.writerows({k: r[k] for k in writer.fieldnames} for r in rows)
    (out / 'verifier.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
