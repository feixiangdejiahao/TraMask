"""Evaluation-only JSON round-trip adapter for an immutable baseline snapshot.

Preserves the original request, response, candidate bodies, validation fields and
snapshot. Only Python tuple/list representation differences in reconstructed JSON
are normalized before the snapshot's full-object equality check.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys


def canonical_json(value):
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False))


def equivalent_json(left, right):
    return canonical_json(left) == canonical_json(right)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(args):
    snapshot = args.output.resolve() / 'algorithm_snapshot'
    sys.path.insert(0, str(snapshot))
    driver = importlib.import_module('scripts.run_llm_generation_baseline')
    baseline = importlib.import_module('prototypes.llm_baseline')
    runner = importlib.import_module('generic_composition.runner')
    assert Path(driver.__file__).resolve().is_relative_to(snapshot)
    original_load = baseline.load_generation
    original_freeze = runner.freeze_artifact
    adapter = {'source': str(Path(__file__).resolve()), 'sha256': digest(__file__),
               'reason': 'Original freeze compared JSON-loaded lists to reconstructed lexical-signature tuples.',
               'operation': 'Canonical JSON round-trip of the entire regenerated object before the original complete equality check.',
               'candidate_oracle_modified': False, 'snapshot_modified': False,
               'model_request_repeated': False}
    protected = [args.output / 'baseline_prepare.json']
    rd = args.output / 'rounds' / args.rerun_id
    protected.extend(rd / name for name in ('prepare.json', 'generated.json', 'candidates.json', 'generation_round.json'))
    protected.extend(p for p in (rd / 'generation').iterdir() if p.is_file())
    before = {str(p): digest(p) for p in protected}

    def normalized_load(*positional, **keywords):
        response, generated = original_load(*positional, **keywords)
        return response, canonical_json(generated)

    def recorded_freeze(*positional, **keywords):
        metadata = dict(keywords.get('metadata') or {})
        metadata['evaluation_only_json_adapter'] = adapter
        keywords['metadata'] = metadata
        return original_freeze(*positional, **keywords)

    baseline.load_generation = normalized_load
    runner.freeze_artifact = recorded_freeze
    try:
        result = driver.freeze(args)
        receipt_path = rd / 'freezes/direct.json'
        receipt = json.loads(receipt_path.read_bytes())
        receipt['evaluation_only_json_adapter'] = adapter
        driver.write_json(receipt_path, receipt)
        result['evaluation_only_json_adapter'] = adapter
    finally:
        baseline.load_generation = original_load
        runner.freeze_artifact = original_freeze
    assert {str(p): digest(p) for p in protected} == before, 'Protected baseline bytes changed'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--rerun-id', required=True, choices=('r1', 'r2'))
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    print(json.dumps(freeze(args), indent=2))


if __name__ == '__main__':
    main()
