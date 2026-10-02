"""Explain closed-bank exclusions using frozen source-search receipts only.

For each indexed demand, inspect uniquely resolved source calls whose current
method summaries write the same declaration owner and field. Reuse the frozen
bank eligibility function on each such call; do not relax transport rules.
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
if __package__ in {None, ''}:
    sys.path.insert(0, str(ROOT))

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Source, walk
from experimental import observation_address_search as search
from experimental.observation_address_effects import summarize_method
from scripts.diagnose_observation_address_gates import read_frozen


def freeze(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def verify_census_seals(current, census_seals):
    for receipt in current:
        previous = census_seals.get(receipt['path'])
        if previous is not None and previous != receipt['sha256']:
            raise ValueError('Imported source differs from frozen search census: ' + receipt['path'])


def diagnose(corpus, frontend, demand_rows):
    wanted = {(tuple(d['owner_key']), d['field']) for d in demand_rows}
    if not wanted:
        return dict(status='no_indexed_demand', calls=[], counts={})
    index = Index([Source(p, r['code'], r.get('language', corpus['language']))
                   for p, r in sorted(corpus['sources'].items())
                   if r.get('complete_file', True) and not r.get('parse_error')], '')
    cache = {}
    def summary(uid):
        if uid not in cache:
            cache[uid] = summarize_method(index, uid)
        return cache[uid]
    rows = []
    for call in frontend['calls']:
        targets = call.get('targets', [])
        if len(targets) != 1 or not targets[0].get('resolved'):
            continue
        relevant = [w for w in summary(targets[0]['function_id']).get('writes', [])
                    if (tuple(w['owner_key']), w['field']) in wanted]
        if not relevant:
            continue
        record = corpus['tests'].get(call['test_id'])
        if record is None:
            continue
        skips = Counter()
        bank = search._bank(dict(corpus, tests={call['test_id']: record}),
                            {call['test_id']: [call]}, index, summary, skips)
        reasons = [k for k in skips if k != 'donor_nested_region']
        gate = ('supported_closed_donor' if bank else reasons[0] if len(reasons) == 1
                else 'multiple_region_boundaries' if reasons else 'no_eligible_root_statement')
        unit = index.units.get(call['test_id'])
        nodes = {(n.start_byte, n.end_byte): n for n in walk(unit.body)} if unit else {}
        arguments = []
        for arg in call['arguments']:
            at = arg['span']
            node = nodes.get((at['start_byte'], at['end_byte']))
            arguments.append(dict(slot=arg['slot'], span=at,
                syntax_type=node.type if node else 'not_root_ast_node',
                literal_known=arg.get('literal_known', False), source_text=arg['text']))
        rows.append(dict(call_id=call['id'], call=call['span'], function_id=targets[0]['function_id'],
            write_effects=relevant, arguments=arguments, first_gate=gate,
            all_boundary_counts=dict(skips), bank_entries=len(bank)))
    return dict(status='source_diagnostic_only', calls=rows,
                counts=dict(Counter(row['first_gate'] for row in rows)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--search-census', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError('Refusing to overwrite diagnostic artifact')
    source_paths = [Path(__file__), ROOT/'experimental/observation_address_search.py',
        ROOT/'experimental/observation_address_join.py', ROOT/'experimental/observation_address_effects.py',
        ROOT/'scripts/diagnose_observation_address_gates.py']
    seals = [freeze(p) for p in source_paths]
    inventory_receipt = freeze(args.inventory)
    inventory = read_frozen(inventory_receipt)
    manifest_receipt = freeze(args.search_census/'manifest.json')
    manifest = read_frozen(manifest_receipt)
    verify_census_seals(seals, manifest['source_seals'])
    if manifest['inventory']['sha256'] != inventory_receipt['sha256']:
        raise ValueError('Search census used a different source inventory')
    cases = {row['case']: row for row in manifest['cases']}
    started = time.monotonic()
    rows = []
    for item in inventory['cases']:
        receipt = cases[item['case']]['variants']['address']['output']
        result = read_frozen(receipt)
        row = dict(case=item['case'], corpus=item['corpus'], frontend=item['frontend'],
            source_search_receipt=receipt, indexed_demand_count=len(result['demand_rows']),
            **diagnose(read_frozen(item['corpus']), read_frozen(item['frontend']), result['demand_rows']))
        rows.append(row)
        print(json.dumps(dict(case=item['case'], status=row['status'], counts=row['counts'])), flush=True)
    if seals != [freeze(p) for p in source_paths]:
        raise ValueError('Diagnostic source modules changed during the run')
    output = dict(version='source-demanded-donor-closure-diagnostic.v2', inventory=inventory_receipt,
        search_census=manifest_receipt, source_seals=seals, rows=rows,
        elapsed_seconds=time.monotonic()-started, provider_calls=0, native_executions=0,
        reads_evaluation_outcomes=False,
        limitation='Diagnoses source transport boundaries only; summaries are may-access facts and no oracle or runtime influence is established.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2)+'\n')


if __name__ == '__main__':
    main()
