"""Prepare paired singleton prompts or audit source-only semantic eligibility.

This script never calls a provider or evaluates a target oracle.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prototypes.singleton_oracle_slots import adapt_frozen_singleton, eligible_candidates
from relation_search.checkpoint import digest, read, write
from relation_search.semantic_selection import select


def freeze(output, inputs, stage):
    output.mkdir(parents=True, exist_ok=False)
    files = ['prototypes/singleton_oracle_slots.py', 'prototypes/assertion_operand_guard.py',
             'relation_search/oracle.py', 'relation_search/semantic_selection.py',
             'anchor_retrieval/syntax.py', 'scripts/analyze_singleton_oracle_slots.py']
    code = {}
    for relative in files:
        target = output / 'algorithm_snapshot' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
        code[relative] = digest(ROOT / relative)
    protocol = dict(stage=stage, created_utc=datetime.now(timezone.utc).isoformat(),
        inputs=inputs, code_sha256=code, provider_calls=0, target_labels_read=False,
        production_oracle_unchanged=True, fallback_baseline_preserved=True)
    write(output / 'protocol.json', protocol)
    write(output / 'protocol.seal.json', dict(sha256=digest(output / 'protocol.json')))


def paired(baseline, output, max_bytes=64000):
    protocol_path = baseline / 'protocol.json'
    baseline_protocol = read(protocol_path)
    frozen = baseline_protocol['requests']
    freeze(output, dict(baseline_protocol=str(protocol_path.resolve()),
        baseline_protocol_sha256=digest(protocol_path), count=len(frozen),
        order='exact existing inventory order; no output-based inclusion',
        max_bytes=max_bytes), 'paired_singleton_expected_slots')
    cache, records = {}, []
    for row in frozen:
        request_path = Path(row['request'])
        if digest(request_path) != row['request_sha256']:
            raise ValueError('Frozen baseline request changed')
        original = read(request_path)
        source = Path(original['source_prepared'])
        if source not in cache:
            cache[source] = (read(source/'corpus.json'), read(source/'frontend.json'),
                             (source/'issue.md').read_text())
        corpus, frontend, issue = cache[source]
        adapted = adapt_frozen_singleton(original, corpus, frontend, issue, max_bytes=max_bytes)
        record = dict(index=row['index'], case=row.get('case'), **adapted['record'],
            baseline_request=str(request_path.resolve()), baseline_request_sha256=digest(request_path),
            source_hashes={name: digest(source/name) for name in ['corpus.json', 'frontend.json', 'issue.md']},
            baseline_prompt_bytes=len(original['prompt'].encode())+len(original['system'].encode()))
        if adapted['request'] is not None:
            destination = output/'requests'/f"request_{row['index']:03d}.json"
            write(destination, adapted['request'])
            record.update(request=str(destination.resolve()), request_sha256=digest(destination),
                thinking=adapted['request']['thinking'])
        records.append(record)
        write(output/'summary.json', dict(finished=False, records=records))
    result = dict(finished=True, frozen_parent_count=len(frozen),
        prepared_requests=sum('request' in row for row in records),
        statuses=dict(Counter(row['status'] for row in records)), records=records,
        protocol_sha256=digest(output/'protocol.json'), provider_calls=0,
        interpretation='All parent rows remain in denominator; unknown/skipped rows are not model successes.')
    write(output/'summary.json', result)
    write(output/'summary.seal.json', dict(sha256=digest(output/'summary.json')))
    print(json.dumps({key:value for key,value in result.items() if key!='records'}), flush=True)
    return result


def eligibility(inventory, output):
    cases = sorted(path for path in inventory.iterdir() if (path/'source_pool.json').is_file())
    inputs = {path.name: {name:digest(path/name) for name in ['corpus.json','frontend.json','source_pool.json']}
              for path in cases}
    freeze(output, dict(inventory=str(inventory.resolve()), sources=inputs,
        budget=16, selection='unchanged semantic_selection.select on all candidates versus eligible candidates'),
        'source_only_expected_slot_eligibility')
    records = []
    for case in cases:
        corpus, frontend = read(case/'corpus.json'), read(case/'frontend.json')
        candidates = read(case/'source_pool.json')['candidates']
        qualification = eligible_candidates(corpus, frontend, candidates)
        baseline = select(corpus, candidates, budget=16)
        filtered = select(corpus, qualification['candidates'], budget=16)
        before = [row['id'] for row in baseline['selected']]
        after = [row['id'] for row in filtered['selected']]
        accepted = {row['id'] for row in qualification['candidates']}
        write(output/case.name/'qualification.json', dict(records=qualification['records']))
        write(output/case.name/'baseline_selection.json', baseline)
        write(output/case.name/'eligible_selection.json', filtered)
        record = dict(case=case.name, language=corpus['language'], input_candidates=len(candidates),
            eligible_candidates=len(accepted), no_editable_slots=len(candidates)-len(accepted),
            baseline_selected=len(before), baseline_selected_eligible=sum(identifier in accepted for identifier in before),
            eligible_selected=len(after), original_selected_retained=len(set(before)&set(after)),
            new_selected_ids=[identifier for identifier in after if identifier not in before],
            removed_selected_ids=[identifier for identifier in before if identifier not in after])
        records.append(record)
        write(output/'summary.json', dict(finished=False, cases=records))
        print(json.dumps({key:value for key,value in record.items() if not key.endswith('_ids')}), flush=True)
    result = dict(finished=True, cases=records, provider_calls=0, targets_read=False,
        protocol_sha256=digest(output/'protocol.json'),
        interpretation='Qualification of editable syntax only; no oracle applicability or target coverage claim.')
    write(output/'summary.json', result)
    write(output/'summary.seal.json', dict(sha256=digest(output/'summary.json')))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['paired','eligibility'])
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--max-bytes', type=int, default=64000)
    args = parser.parse_args()
    if args.stage == 'paired':
        paired(args.source, args.output, args.max_bytes)
    else:
        eligibility(args.source, args.output)
