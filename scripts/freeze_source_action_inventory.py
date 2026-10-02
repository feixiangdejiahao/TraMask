"""Freeze source inputs independently of reviewed candidate labels.

Only baseline.controlled_failures supplies inventory records. No runtime result,
review, positive witness, verifier, or reference implementation is consulted.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


VERSION = 'source-action-inventory.v1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def receipt(path):
    return dict(path=str(Path(path).resolve()), sha256=digest(path))


def order(record):
    inputs = record['inputs']
    return (record['case'], record['key'], inputs['corpus']['path'], inputs['frontend']['path'],
            inputs['corpus']['sha256'], inputs['frontend']['sha256'])


def source_groups(records):
    """Project only case/key/round and corpus/frontend receipts before sorting."""
    groups = defaultdict(list)
    for record in records:
        projected = dict(case=record['case'], key=record['key'], round=record['round'],
            inputs={kind: {key: record['inputs'][kind][key] for key in ('path', 'sha256')}
                    for kind in ('corpus', 'frontend')})
        groups[projected['case']].append(projected)
    return {case: sorted(rows, key=order) for case, rows in sorted(groups.items())}


def build(baseline_path):
    baseline_path = Path(baseline_path)
    baseline = json.loads(baseline_path.read_text())
    groups = source_groups(baseline['controlled_failures'])
    del baseline
    cases = []
    for case, rows in groups.items():
        selected = rows[0]
        variants = {}
        for row in rows:
            identity = tuple((row['inputs'][kind]['path'], row['inputs'][kind]['sha256'])
                             for kind in ('corpus', 'frontend'))
            entry = variants.setdefault(identity, dict(inputs=row['inputs'],
                first_source_key=row['key'], rounds=set(), source_record_count=0))
            entry['rounds'].add(row['round'])
            entry['source_record_count'] += 1
        for entry in variants.values():
            for frozen in entry['inputs'].values():
                if digest(frozen['path']) != frozen['sha256']:
                    raise ValueError('Changed source input: ' + frozen['path'])
            entry['rounds'] = sorted(entry['rounds'])
        corpus = json.loads(Path(selected['inputs']['corpus']['path']).read_text())
        frontend = json.loads(Path(selected['inputs']['frontend']['path']).read_text())
        paths = sorted(corpus['sources'])
        source_hashes = {path: hashlib.sha256(corpus['sources'][path]['code'].encode()).hexdigest()
                         for path in paths}
        cases.append(dict(case=case, language=corpus['language'],
            corpus=selected['inputs']['corpus'], frontend=selected['inputs']['frontend'],
            tests_count=len(corpus['tests']), frontend_tests_count=len(frontend['tests']),
            source_count=len(paths), source_paths=paths, source_sha256=source_hashes,
            selected_source_key=selected['key'], selected_round=selected['round'],
            source_record_count=len(rows), source_variant_count=len(variants),
            source_variants=list(variants.values())))
    return dict(version=VERSION, created_utc=datetime.now(timezone.utc).isoformat(),
        producer=receipt(__file__), source_inventory=receipt(baseline_path),
        source_records_field='controlled_failures',
        selection_rule='For each case, take first record sorted by(case,key,corpus.path,frontend.path,corpus.sha256,frontend.sha256). Record all distinct corpus/frontend variants.',
        excluded_inputs=['positive_witnesses', 'development_reviews', 'heldout reviews',
                         'native_evidence', 'runs', 'reference solutions', 'hidden verifiers'],
        selection_uses_candidate_outcomes_or_review_labels=False,
        population_limitation='Cases come from the existing controlled-failure inventory; this is not an unseen-task sample. Original source corpora/frontends are used, not selected generated tests.',
        case_count=len(cases), source_record_count=sum(row['source_record_count'] for row in cases),
        language_counts=dict(Counter(row['language'] for row in cases)),
        cases=cases, provider_calls=0, native_executions=0)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    document = build(args.baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(document, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(output=receipt(args.output), cases=document['case_count'],
                         languages=document['language_counts'])))


if __name__ == '__main__':
    main()
