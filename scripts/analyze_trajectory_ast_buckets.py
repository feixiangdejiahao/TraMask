"""Read source corpora/queues only and simulate a structural bucket schedule."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experimental.trajectory_ast_buckets import Buckets, rank_all, sha
from experimental.candidate_scheduling import select


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'source AST scheduling analysis; no execution, verdict, target or LLM input',
              'claim': 'same scheduling bucket does not imply behavioral equivalence',
              'files': {}, 'cases': []}
    for code in ('experimental/trajectory_ast_buckets.py', 'experimental/candidate_scheduling.py',
                 'experimental/source_edit_identity.py', 'scripts/analyze_trajectory_ast_buckets.py'):
        report['files'][str(ROOT/code)] = digest(ROOT/code)
        snapshot = args.output/'algorithm_snapshot'/code
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/code, snapshot)
    for folder in sorted(args.source.iterdir()):
        if not (folder/'corpus.json').exists():
            continue
        started = time.monotonic()
        corpus, selection = read(folder/'corpus.json'), read(folder/'selection.json')
        for name in ('corpus.json', 'selection.json'):
            report['files'][str((folder/name).resolve())] = digest(folder/name)
        buckets = Buckets(corpus, selection)
        groups, bodies, normalization = defaultdict(list), defaultdict(list), Counter()
        for test_id in corpus['tests']:
            unit = buckets.seed(test_id)
            normalization[unit['status']] += 1
            key = sha([unit['alpha'], unit['environment'], unit['imports']]) if unit['status'] == 'parsed' else sha(unit)
            body = unit.get('alpha', sha(unit))
            groups[key].append(test_id)
            bodies[body].append(test_id)
        result = {'case': folder.name, 'language': corpus['language'], 'tests': len(corpus['tests']),
                  'body_only_buckets': len(bodies), 'environment_bound_buckets': len(groups),
                  'potential_repeated_seed_slots': len(corpus['tests'])-len(groups),
                  'normalization': dict(normalization),
                  'environment_splits': len(groups)-len(bodies),
                  'duplicate_seed_groups': [ids for ids in groups.values() if len(ids)>1]}
        prepared = next((root/folder.name/'round_000/prepared' for root in args.queues
                         if (root/folder.name/'round_000/prepared/source_pool.json').exists()), None)
        if prepared:
            pool = read(prepared/'source_pool.json')['candidates']
            actual = read(prepared/'candidates.json')['candidates']
            assert digest(prepared/'corpus.json') == digest(folder/'corpus.json')
            for name in ('source_pool.json', 'candidates.json'):
                report['files'][str((prepared/name).resolve())] = digest(prepared/name)
            # Reproduce the physical-edit distinctness already present in v2;
            # bucket scheduling itself still returns every one of these rows.
            eligible = select(pool, len(pool))
            keys = {row['id']: buckets.candidate(row) for row in eligible}
            old = select(pool, min(args.budget, len(eligible)))
            ranked = rank_all(eligible, keys)
            proposed = ranked[:len(old)]
            assert Counter(row['id'] for row in eligible) == Counter(row['id'] for row in ranked)
            def inventory(rows):
                counts = Counter(keys[row['id']] for row in rows)
                return {'slots': len(rows), 'buckets': len(counts), 'repeated_bucket_slots': len(rows)-len(counts)}
            families = {}
            for family in sorted({row.get('operator', row.get('kind', 'unknown')) for row in eligible}):
                original = [row for row in old if row.get('operator', row.get('kind', 'unknown')) == family]
                after = [row for row in proposed if row.get('operator', row.get('kind', 'unknown')) == family]
                families[family] = {'before': inventory(original), 'after': inventory(after)}
            result['queue'] = {'source': str(prepared.resolve()), 'pool': len(pool), 'distinct_physical_inputs': len(eligible),
                               'actual_selected_count': len(actual), 'budget': args.budget,
                               'before': inventory(old), 'after': inventory(proposed), 'families': families,
                               'old_ids': [row['id'] for row in old], 'proposed_ids': [row['id'] for row in proposed],
                               'simulation': 'same source pool and operator rotation, structural bucket round robin within operator'}
        result['seconds'] = round(time.monotonic()-started, 3)
        report['cases'].append(result)
        (args.output/'analysis.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({key: result[key] for key in ('case','tests','body_only_buckets','environment_bound_buckets','potential_repeated_seed_slots','seconds')}
                         | {'queue': {key: result['queue'][key] for key in ('before','after')} if 'queue' in result else None}), flush=True)
    report['totals'] = {key: sum(row[key] for row in report['cases']) for key in
                       ('tests','body_only_buckets','environment_bound_buckets','potential_repeated_seed_slots','environment_splits')}
    report['totals']['queue_cases'] = sum('queue' in row for row in report['cases'])
    for key in ('slots','buckets','repeated_bucket_slots'):
        for stage in ('before','after'):
            report['totals'][stage+'_'+key] = sum(row['queue'][stage][key] for row in report['cases'] if 'queue' in row)
    (args.output/'analysis.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['totals']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--queues', type=Path, nargs='+', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget', type=int, default=128)
    main(parser.parse_args())
