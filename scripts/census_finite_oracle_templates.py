"""Seal lossless, source-only finite templates for every saved pool candidate.

Reads corpus.json, frontend.json and source_pool.json only. Model responses,
runtime outcomes, evaluation labels and hidden tests are not inputs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prototypes.finite_oracle_templates import build_catalogue, expand, source_size_summary
from relation_search.oracle import preview, program_candidate

FILES = [
    'prototypes/finite_oracle_templates.py', 'tests/test_finite_oracle_templates.py',
    'scripts/census_finite_oracle_templates.py', 'prototypes/singleton_oracle_slots.py',
    'prototypes/assertion_operand_guard.py', 'relation_search/instrument.py',
    'relation_search/oracle.py', 'anchor_retrieval/syntax.py', 'anchor_retrieval/graph.py',
    'anchor_retrieval/index.py', 'relational_gap/frontend.py', 'generic_composition/corpus.py',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)+'\n')


def run(inventory, output, expected_candidates=None):
    output.mkdir(parents=True, exist_ok=False)
    inputs = {case.name: {name: dict(path=str((case/name).resolve()), sha256=digest(case/name))
                          for name in ('corpus.json', 'frontend.json', 'source_pool.json')}
              for case in sorted(inventory.iterdir()) if (case/'source_pool.json').exists()}
    hashes = {name: digest(ROOT/name) for name in FILES}
    write(output/'protocol.json', dict(version='finite-template-census-v2',
        inventory=str(inventory.resolve()), input_sha256=inputs, code_sha256=hashes,
        cases=sorted(inputs), expected_candidates=expected_candidates,
        selection='every saved source_pool candidate, in original per-case order',
        family_rule='same original base_test_id and path/start/end edit coordinate set',
        representation_order='families by content SHA; variants by candidate id; independent of input candidate order',
        no_family_filters=['kind', 'shape', 'profile', 'role', 'oracle eligibility'],
        source_guarantee='exact expansion equals oracle.preview(program_candidate(original candidate))',
        unknown='retain unsupported candidate as a separate singleton; preserve available mechanical preview',
        semantic_guarantee=False, oracle_correctness_guarantee=False,
        catalogue_truncation=False, provider_calls=0, subject_executions=0,
        read_boundaries=['corpus.json', 'frontend.json', 'source_pool.json', 'listed source code']))
    for name in FILES:
        destination = output/'code_snapshot'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT/name).read_bytes())
    summaries = {}
    for case, paths in inputs.items():
        start = time.monotonic()
        corpus, frontend, pool = [read(Path(paths[name]['path']))
                                 for name in ('corpus.json', 'frontend.json', 'source_pool.json')]
        candidates = pool['candidates']
        catalogue = build_catalogue(corpus, frontend, candidates)
        by_id = {candidate['id']: candidate for candidate in candidates}
        assert set(catalogue['candidate_info']) == set(by_id)
        rows = []
        for family in catalogue['families']:
            for variant in family['variants']:
                cid = variant['candidate_id']
                try:
                    expected = preview(corpus, program_candidate(by_id[cid]))
                except (ValueError, KeyError, TypeError, UnicodeError) as error:
                    if family['status'] != 'unknown' or variant.get('mechanical_preview') is not None:
                        raise ValueError('unavailable preview was not preserved as unknown') from error
                    row = dict(candidate_id=cid, status='unknown_preview_unavailable', reason=str(error))
                else:
                    actual = expand(family, variant)
                    if actual != expected:
                        raise ValueError('mechanical roundtrip mismatch for '+cid)
                    row = dict(candidate_id=cid, status='exact_source_roundtrip',
                        utf8_bytes=len(actual.encode()), preview_sha256=hashlib.sha256(actual.encode()).hexdigest())
                rows.append(row)
        write(output/case/'catalogue.json', catalogue)
        write(output/case/'roundtrip.json', rows)
        summary = dict(input_candidates=len(candidates), families=len(catalogue['families']),
            family_size_histogram=dict(Counter(str(len(family['variants'])) for family in catalogue['families'])),
            factorized_candidates=sum(len(family['variants']) for family in catalogue['families'] if family['status']=='factorized'),
            unknown_candidates=sum(len(family['variants']) for family in catalogue['families'] if family['status']=='unknown'),
            unknown_reasons=dict(Counter(family['reason'] for family in catalogue['families'] if family['status']=='unknown')),
            exact_roundtrips=sum(row['status']=='exact_source_roundtrip' for row in rows),
            unavailable_previews=sum(row['status']=='unknown_preview_unavailable' for row in rows),
            assertion_inventory_entries=sum(len(variant['assertions']) for family in catalogue['families'] for variant in family['variants']),
            byte_sizes=source_size_summary(catalogue), elapsed_seconds=round(time.monotonic()-start, 3))
        summaries[case] = summary
        print(json.dumps(dict(case=case, **summary)), flush=True)
        if any(digest(Path(row['path'])) != row['sha256'] for row in paths.values()):
            raise ValueError('input changed during census; no seal')
    totals = dict(cases=len(summaries), input_candidates=sum(row['input_candidates'] for row in summaries.values()),
        families=sum(row['families'] for row in summaries.values()),
        exact_roundtrips=sum(row['exact_roundtrips'] for row in summaries.values()),
        unknown_candidates=sum(row['unknown_candidates'] for row in summaries.values()),
        unavailable_previews=sum(row['unavailable_previews'] for row in summaries.values()),
        expanded_source_json_bytes=sum(row['byte_sizes']['expanded_source_json_bytes'] for row in summaries.values()),
        factorized_source_json_bytes=sum(row['byte_sizes']['factorized_source_json_bytes'] for row in summaries.values()))
    if expected_candidates is not None and totals['input_candidates'] != expected_candidates:
        raise ValueError('candidate count differs from frozen expected count; no seal')
    write(output/'summary.json', dict(totals=totals, cases=summaries))
    if {name: digest(ROOT/name) for name in FILES} != hashes:
        raise ValueError('code changed during census; no seal')
    write(output/'seal.json', dict(files_sha256={str(path.relative_to(output)): digest(path)
        for path in sorted(output.rglob('*')) if path.is_file()}))
    return totals


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-candidates', type=int)
    args = parser.parse_args()
    print(json.dumps(run(args.inventory, args.output, args.expected_candidates)))
