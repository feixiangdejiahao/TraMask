"""Catalog or prepare a bounded contract-observation experiment; no dispatch.

Catalogs contain syntax and binding opportunities, not validated relations.
Prepare consumes independent discovery IR in <relations-dir>/<case>.json.
Native execution and model discovery are deliberately separate stages.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import contract_observation_boundary as relation
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import frozen, verify, write

VERSION = 'source-contract-observation-boundary-search.v1'


def prepare(args):
    verify(read(args.source_cohort/'seal.json'))
    previous = read(args.source_cohort/'prepared.json')
    sources = {}
    for row in previous.get('items', previous.get('cases', [])):
        existing = sources.setdefault(row['case'], row['source'])
        if existing != row['source']:
            raise ValueError('one_source_per_trial_required')
    if not sources:
        raise ValueError('source_cohort_is_empty')
    args.output.mkdir(parents=True, exist_ok=False)
    admission._preload_local_imports(relation)
    algorithm = admission._loaded_sources()
    cases = []
    for case, name in sorted(sources.items()):
        source = Path(name); corpus = read(source/'corpus.json'); frontend = read(source/'frontend.json')
        inputs = {key: frozen(source/key) for key in ['corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md']}
        directory = args.output/'cases'/case
        if args.stage == 'catalog':
            catalog = relation.catalog(corpus, frontend)
            candidates = []
            result = dict(status=catalog['status'], total_candidates=0, discovery='not_run')
        else:
            relation_file = args.relations_dir/(case+'.json')
            if relation_file.exists():
                inputs['relation_ir'] = frozen(relation_file); ir = read(relation_file)
            else:
                ir = dict(version=relation.IR_VERSION, relations=[])
            result = relation.generate(corpus, frontend, (source/'issue.md').read_text(), ir, limit=args.limit)
            catalog = result.pop('source_catalog'); candidates = result.pop('candidates')
            if not relation_file.exists():
                result['status'] = 'relation_discovery_missing'
        write(directory/'catalog.json', catalog)
        write(directory/'generation.json', result)
        entries = []
        for rank, candidate in enumerate(candidates, 1):
            path = directory/f'candidate_{rank:04d}'/'program.json'; write(path, candidate)
            entries.append(dict(rank=rank, program=frozen(path)))
        cases.append(dict(case=case, source=str(source.resolve()), inputs=inputs,
            catalog=frozen(directory/'catalog.json'), generation=frozen(directory/'generation.json'),
            candidates=entries, status=result['status']))
        print(json.dumps(dict(case=case, status=result['status'],
            opportunities=len(catalog['opportunities']), selected=len(entries))), flush=True)
    admission.verify_seal(algorithm)
    if set(admission._loaded_sources())-set(algorithm):
        raise ValueError('unsealed_local_import')
    protocol = dict(version=VERSION, stage=args.stage, algorithm=algorithm, policy=relation.POLICY,
        source_cohort=frozen(args.source_cohort/'prepared.json'), cases=cases,
        source_cohort_use='Trial list and frozen original sources only; no old candidate or outcome input.',
        trial_denominator=len(cases), max_candidates_per_trial=args.limit,
        deadline_utc=args.deadline_utc, native_executions=0, external_model_calls=0,
        evaluator_labels_used=False, semantic_validity='unassessed',
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output/'prepared.json', protocol); write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(trials=len(cases), selected=sum(len(case['candidates']) for case in cases),
                prepared=frozen(args.output/'prepared.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['catalog', 'prepare'])
    parser.add_argument('--source-cohort', type=Path, required=True)
    parser.add_argument('--relations-dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--deadline-utc')
    parser.add_argument('--limit', type=int, default=4)
    args = parser.parse_args()
    if args.stage == 'prepare' and args.relations_dir is None:
        parser.error('--relations-dir is required for prepare')
    if not 1 <= args.limit <= 16:
        parser.error('--limit must be between 1 and 16')
    print(json.dumps(prepare(args)))
