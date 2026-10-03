"""Snapshot every available first failure from a frozen prefix probe.

This evaluator helper never changes the search or selects a replacement after
review. It preserves complete test bodies, source receipts and native receipts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import oracle
from relation_search.checkpoint import read
from scripts.run_contract_repair_search import frozen, verify, write
from scripts.resume_test_prefix_probe import validate_cached


def collect(root, output):
    verify(read(root / 'seal.json'))
    protocol = read(root / 'prepared.json')
    corpus_cache = {}
    packs = []
    for item in protocol['items']:
        for entry in item['programs']:
            receipt = protocol.get('cached_outcomes', {}).get(f"{item['name']}:{entry['rank']}")
            if receipt is None:
                path = root / 'cases' / item['name'] / f"candidate_{entry['rank']:04d}" / 'outcome.json'
                if not path.exists():
                    break
                receipt = frozen(path)
            verify(receipt)
            outcome = read(receipt['path'])
            validate_cached(outcome, entry)
            native = outcome.get('native')
            if native and native['controlled_failure']:
                for source in item['source_inputs'].values():
                    verify(source)
                verify(entry['program'])
                corpus_path = item['source_inputs']['corpus']['path']
                if corpus_path not in corpus_cache:
                    corpus_cache[corpus_path] = read(corpus_path)
                candidate = read(entry['program']['path'])
                pack = dict(case=item['case'], parent_name=item['name'], rank=entry['rank'],
                    is_original=entry['is_original'], candidate=candidate,
                    full_test=oracle.preview(corpus_cache[corpus_path], candidate),
                    source_inputs=item['source_inputs'], issue=str(Path(item['source']) / 'issue.md'),
                    native=native, outcome=receipt)
                path = output / 'audit_pack' / f"{item['name']}.json"
                write(path, pack)
                packs.append(dict(parent_name=item['name'], case=item['case'],
                                  rank=entry['rank'], audit_pack=frozen(path)))
                break
            if outcome.get('emission_refusal'):
                continue
            if native is None or native['controls']['status'] != 'all_source_controls_passed':
                break
    index = dict(stage='all_available_first_failures_snapshot', prepared=frozen(root / 'prepared.json'),
                 evaluator_only=True, used_by_generation=False, detector_alerts=0,
                 created_utc=datetime.now(timezone.utc).isoformat(), packs=packs)
    write(output / 'index.json', index)
    return dict(first_failures=len(packs), index=frozen(output / 'index.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(collect(args.input, args.output))
