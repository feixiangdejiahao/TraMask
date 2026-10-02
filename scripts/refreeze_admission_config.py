"""Freeze a dispatch-configuration ablation without recomputing source facts.

Parent requests, analysis, and algorithm seals are immutable. No provider or
subject executes here. Completed responses and decisions are never copied.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_test_admission import _configure_request, _deadline
from scripts.evaluate_test_validity import digest, frozen, read, verify_seal, write_new


def refreeze(args):
    if not 1 <= args.output_token_limit <= 16384 or args.max_total_tokens <= 0:
        raise ValueError('Invalid dispatch budget')
    parent_path = args.input / 'prepared.json'
    parent = read(parent_path)
    verify_seal(parent['algorithm_entry_modules'])
    verify_seal(parent['imported_source_modules'])
    prepared = copy.deepcopy(parent)
    args.output.mkdir(parents=True, exist_ok=False)
    for item in prepared['items']:
        destination = args.output / item['name']
        destination.mkdir()
        original_analysis = Path(item['analysis_path'])
        analysis = read(original_analysis)
        write_new(destination / 'analysis.json', analysis)
        item['parent_analysis'] = frozen(original_analysis)
        item['analysis_path'] = str((destination / 'analysis.json').resolve())
        if item['request_path'] is None:
            continue
        original_request = Path(item['request_path'])
        if digest(original_request) != item['request_sha256']:
            raise ValueError('Parent request changed')
        request = read(original_request)
        modified = _configure_request(copy.deepcopy(request), args)
        if (modified['system'], modified['prompt']) != (request['system'], request['prompt']):
            raise ValueError('Semantic request contents changed')
        write_new(destination / 'request.json', modified)
        item['parent_request'] = frozen(original_request)
        item['request_path'] = str((destination / 'request.json').resolve())
        item['request_sha256'] = digest(destination / 'request.json')
    prepared.update(
        created_utc=datetime.now(timezone.utc).isoformat(),
        thinking=args.thinking, reasoning_effort=args.reasoning_effort,
        output_token_limit=args.output_token_limit,
        max_total_tokens=args.max_total_tokens,
        deadline_utc=_deadline(args.deadline_utc).isoformat(),
        source_analysis_reused=True, responses_reused=False, provider_calls=0,
        configuration_ablation_parent=frozen(parent_path),
        configuration_ablation_script=frozen(__file__),
    )
    verify_seal(parent['algorithm_entry_modules'])
    verify_seal(parent['imported_source_modules'])
    write_new(args.output / 'prepared.json', prepared)
    return dict(items=len(prepared['items']), requests=sum(bool(r['request_path']) for r in prepared['items']),
                semantic_inputs_unchanged=True, provider_calls=0, responses_reused=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--thinking', choices=['disabled', 'enabled'], required=True)
    parser.add_argument('--reasoning-effort', choices=['low', 'high', 'max'])
    parser.add_argument('--output-token-limit', type=int, required=True)
    parser.add_argument('--max-total-tokens', type=int, required=True)
    parser.add_argument('--deadline-utc', required=True)
    print(json.dumps(refreeze(parser.parse_args())))
