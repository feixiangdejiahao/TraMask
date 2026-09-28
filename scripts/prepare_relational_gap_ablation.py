"""Freeze an offline observation-retention ablation of every offered source q."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def main():
    from relational_gap.oracle_retention_ablation import restore_source_observations, RetentionBudget
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--emitted', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.source/'prepare.json').read_text())
    for name, expected in manifest['files_sha256'].items():
        if sha(args.source/name) != expected:
            raise ValueError('Frozen source changed: ' + name)
    accepted_path = args.emitted/'accepted.json'
    accepted = json.loads(accepted_path.read_text())
    corpus = json.loads((args.source/'corpus.json').read_text())
    source_candidates = [candidate for candidate in accepted if candidate.get('execution_lane') == 'source_q']
    result = restore_source_observations(corpus, source_candidates, budget=RetentionBudget(max_candidates=128))
    candidates = result['candidates']
    for candidate in candidates:
        candidate['static_parent_id'] = candidate['id']
    args.output.mkdir(parents=True, exist_ok=False)
    for name in manifest['files_sha256']:
        if name == 'candidates.json':
            continue
        destination = args.output/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((args.source/name).read_bytes())
    write(args.output/'candidates.json', {**result, 'candidates': candidates})
    provenance = {'mode': 'whole_source_observation_retention', 'provider_calls': 0,
                  'prior_prepare': {'path': str((args.source/'prepare.json').resolve()), 'sha256': sha(args.source/'prepare.json')},
                  'prior_accepted': {'path': str(accepted_path.resolve()), 'sha256': sha(accepted_path)},
                  'counts': result['counts'], 'budget': result['budget'],
                  'excluded_non_source_lanes': len(accepted) - len(source_candidates),
                  'selection': 'all_offered_source_q_no_outcome_or_target_filter',
                  'reference_or_verifier_inputs': False}
    write(args.output/'ablation.json', provenance)
    files = [*manifest['files_sha256'], 'ablation.json']
    algorithm = dict(manifest['algorithm_sha256'])
    for name in ['relational_gap/oracle_retention_ablation.py', 'scripts/prepare_relational_gap_ablation.py']:
        algorithm[name] = sha(ROOT/name)
    write(args.output/'prepare.json', {'case': manifest['case'], 'status': 'prepared',
          'stage': 'offline_whole_source_observation_ablation', 'model_calls': 0,
          'algorithm_sha256': algorithm,
          'files_sha256': {name: sha(args.output/name) for name in files},
          'ablation': provenance})
    print(json.dumps({'case': manifest['case'], 'candidates': len(candidates), 'counts': result['counts']}))


if __name__ == '__main__':
    main()
