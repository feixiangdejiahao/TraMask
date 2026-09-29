"""Prepare source-only relational search rounds and record measured feedback."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def prepare(args):
    from relation_search.frontier import select_round
    corpus = read(args.source/'corpus.json')
    frontend = read(args.source/'frontend.json')
    candidates, counts = [], {}
    if corpus['language'] == 'python':
        from relation_search.representations import generate
        rows = generate(corpus, frontend, budget=args.pool)
        candidates.extend(rows)
        counts['resource_representation'] = len(rows)
        if not args.representations_only:
            from experimental.relation_search_python import generate as python_generate
            rows = python_generate(corpus, frontend)
            candidates.extend(rows)
            counts['python_contexts'] = len(rows)
    else:
        from experimental.relation_search_go_ts import enrich
        rows = enrich(corpus, frontend, budget=args.pool)
        candidates.extend(rows)
        counts['typed_contexts'] = len(rows)
    if args.include_baseline:
        old = read(args.source/'candidates.json')['candidates']
        candidates.extend(old)
        counts['baseline_candidates'] = len(old)
    previous = read(args.previous).get('executed_candidate_ids', []) if args.previous else []
    selected = select_round(candidates, args.limit, previous)
    args.output.mkdir(parents=True, exist_ok=False)
    for name in ['corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md']:
        source = args.source/name
        if source.exists():
            (args.output/name).symlink_to(source.resolve())
    for row in selected:
        row['source_provenance'] = dict(seed=row['base_test_id'],
                                        seed_snapshot=str((args.source/'corpus.json').resolve()),
                                        algorithm=row.get('operator', row.get('kind')))
        row['execution_lane'] = 'relation_search'
        row['static_parent_id'] = row['id']
    write(args.output/'candidates.json', dict(candidates=selected, counts=counts,
                                             pool_size=len(candidates), selected=len(selected),
                                             selection='fair source/operator rotation without evaluation labels'))
    paths = sorted([*ROOT.glob('relation_search/*.py'), ROOT/'scripts/run_relation_search.py',
                    ROOT/'scripts/execute_relation_search.py',
                    *ROOT.glob('experimental/relation_search_*.py')])
    manifest = dict(status='prepared', case=read(args.source/'case.json')['id'],
                    source_prepare=str((args.source/'prepare.json').resolve()),
                    model_calls=0,
                    files_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in args.output.iterdir() if p.is_file()},
                    algorithm_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in paths})
    write(args.output/'prepare.json', manifest)
    return dict(pool=len(candidates), selected=len(selected), families=counts)


def feedback(args):
    from relation_search.frontier import Frontier
    frontier = Frontier()
    results, executed = [], set()
    for path in sorted(args.source.rglob('relation_trace.jsonl')):
        grouped = {}
        for line in path.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            grouped.setdefault(event['candidate_id'], []).append(event)
        for identifier, events in grouped.items():
            executed.add(identifier)
            results.append(frontier.observe(identifier, events))
    write(args.output, dict(executed_candidate_ids=sorted(executed), results=results,
                           measured_profile_count=len(frontier.profiles),
                           unresolved_without_events=True))
    return dict(executed=len(executed), profiles=len(frontier.profiles))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'feedback'])
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=128)
    parser.add_argument('--pool', type=int, default=512)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--include-baseline', action='store_true')
    parser.add_argument('--representations-only', action='store_true')
    arguments = parser.parse_args()
    print(json.dumps({'prepare': prepare, 'feedback': feedback}[arguments.stage](arguments)))
