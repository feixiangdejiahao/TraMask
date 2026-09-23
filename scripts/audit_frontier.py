"""Verify result provenance and label-independent ranking perturbations locally."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anchor_retrieval.frontier import rank_frontier
from anchor_retrieval.retrieve import rank


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--original', type=Path, default=ROOT / 'results/anchor_retrieval/final')
    args = parser.parse_args()
    manifest = json.loads((args.results / 'manifest.json').read_text())
    evaluation = json.loads((args.results / 'evaluation.json').read_text())
    labels = ROOT / 'configs/anchor_targets.json'
    assert hashlib.sha256(labels.read_bytes()).hexdigest() == evaluation['target_labels_sha256']
    assert subprocess.check_output(['git', 'show', 'retrieval-v0.1-baseline:configs/anchor_targets.json'], cwd=ROOT) == labels.read_bytes()
    for path, digest in manifest['code_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    checks = {}
    for path in sorted(args.results.glob('P?.json')):
        case = path.stem
        result = json.loads(path.read_text())
        original = json.loads((args.original / path.name).read_text())
        assert result['input_hashes'] == original['input_hashes'], case
        rows = result['anchors']
        ids = {row['id'] for row in rows}
        assert len(ids) == len(rows)
        assert len(result['rankings']['full']) == len(ids) and set(result['rankings']['full']) == ids
        patch = (ROOT / 'data/cases' / case / 'model.patch').read_text()
        seeds = [0, 1, 17, 91, 2026]
        for seed in seeds:
            shuffled = list(rows)
            random.Random(seed).shuffle(shuffled)
            ranked = rank_frontier(shuffled, rank(shuffled, 'legacy_keywords', patch))
            assert [row['id'] for row in ranked] == result['rankings']['full'], (case, seed)
        # Metadata perturbation, not a claim about arbitrary source transformations.
        anon = copy.deepcopy(rows)
        names = {r['name']: 'test_' + hashlib.sha256(r['name'].encode()).hexdigest()[:16] for r in rows}
        tests = {r['test_id']: 'unit_' + hashlib.sha256(r['test_id'].encode()).hexdigest() for r in rows}
        for row in anon:
            row['name'] = names[row['name']]
            row['test_id'] = tests[row['test_id']]
        ranked = rank_frontier(anon, rank(anon, 'legacy_keywords', patch))
        assert [row['id'] for row in ranked] == result['rankings']['full'], case
        checks[case] = {'same_original_input_hashes': True, 'all_assertions_ranked_once': True,
                        'candidate_order_shuffle_seeds': seeds,
                        'obfuscated_record_test_names_same_ranking': True}
    assert len(checks) == len(evaluation['cases']) == 7
    audit = {'code_commit': manifest['git_commit'], 'code_matches_manifest': True,
             'labels_unchanged_from_baseline_commit': True, 'cases': checks,
             'limits': 'Order/name perturbations operate on extracted records. Parsed-source alpha-renaming is checked in independent regression examples. This is not an unseen-data evaluation.'}
    (args.results / 'audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    print('PASS: seven cases; unchanged inputs/labels/code hashes; 35 order shuffles; seven name perturbations.')


if __name__ == '__main__':
    main()
