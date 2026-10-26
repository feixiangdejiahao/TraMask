"""Read-only first-gate diagnostic for observation-address source search.

The input is a frozen original-source inventory, never evaluation outcomes. All
observation-linked calls with supported indexed-return summaries are inspected;
there are no case-name or candidate-result selection rules.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ''}:
    sys.path.insert(0, str(ROOT))

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Source
from experimental import observation_address_join as join
from experimental.observation_address_effects import summarize_method
from relational_gap import state_cells as cells


def read_frozen(receipt):
    raw = Path(receipt['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('Frozen source input changed: ' + receipt['path'])
    return json.loads(raw)


def diagnose(corpus, frontend):
    started = time.monotonic()
    index = Index([Source(p, r['code'], r.get('language', corpus['language']))
                   for p, r in sorted(corpus['sources'].items())
                   if r.get('complete_file', True) and not r.get('parse_error')], '')
    summaries = {}
    def summary(uid):
        if uid not in summaries:
            summaries[uid] = summarize_method(index, uid)
        return summaries[uid]
    calls = defaultdict(list)
    for call in frontend['calls']:
        calls[call['test_id']].append(call)
    preprocessing = Counter()
    groups = join._collect(corpus, index, preprocessing)
    group_rows = []
    for group, recipients in groups.items():
        bank_skips = Counter()
        bank = cells._action_bank(recipients, index, 32, bank_skips)
        demand_skips = Counter()
        demands = [d for r in recipients for d in join._demands(r, calls, summary, demand_skips)]
        group_rows.append(dict(group=group, read_call_ids=sorted({d['call']['id'] for d in demands}),
            source_bank_size=len(bank), bank_skips=dict(bank_skips), demand_skips=dict(demand_skips)))
    rows = []
    capsules = defaultdict(list)
    for q in corpus.get('capsules', []):
        if q.get('assertion_span'):
            capsules[q['test_id']].append(q)
    for call in frontend['calls']:
        if not call.get('observation_ids'):
            continue
        targets = call.get('targets', [])
        if len(targets) != 1 or not targets[0].get('resolved'):
            continue
        result = summary(targets[0]['function_id'])
        reads = [e for e in result.get('reads', []) if e.get('key') is not None]
        if not reads:
            continue
        matched = [r for r in group_rows if call['id'] in r['read_call_ids']]
        record = corpus['tests'].get(call['test_id'])
        unit = index.units.get(call['test_id'])
        if matched:
            gate = ('same_file_scope_constructor_action_bank_empty'
                    if all(not r['source_bank_size'] for r in matched)
                    else 'pair_join_or_render_not_evaluated')
        elif not record or not unit or not record.get('enclosing_scope_span') or not capsules[call['test_id']]:
            gate = 'source_test_or_observation_unavailable'
        elif record.get('parameterization_status', 'none_detected') != 'none_detected':
            gate = 'test_parameterization_unknown'
        elif not join._simple_root(unit, capsules[call['test_id']]):
            gate = 'test_scope_not_straight_line'
        else:
            gate = 'no_supported_phase_or_key'
        rows.append(dict(read_call_id=call['id'], read_call=call['span'], source_test_id=call['test_id'],
                         read_effects=reads, first_excluding_gate=gate, groups=matched))
    return dict(read_sites=rows, preprocessing_skips=dict(preprocessing),
                elapsed_seconds=time.monotonic()-started,
                limitation='First supported gate only; absence of a demand does not prove absence of a dependency.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError('Refusing to overwrite diagnostic artifact')
    inventory_raw = args.inventory.read_bytes()
    inventory = json.loads(inventory_raw)
    started = time.monotonic()
    rows = []
    for item in inventory['cases']:
        row = dict(case=item['case'], corpus=item['corpus'], frontend=item['frontend'],
                   **diagnose(read_frozen(item['corpus']), read_frozen(item['frontend'])))
        rows.append(row)
        print(json.dumps(dict(case=item['case'], indexed_read_sites=len(row['read_sites']),
                              gates=dict(Counter(r['first_excluding_gate'] for r in row['read_sites'])))), flush=True)
    sources = [Path(__file__), ROOT/'experimental/observation_address_join.py',
               ROOT/'experimental/observation_address_effects.py']
    output = dict(version='source-address-first-gates.v2',
        inventory=dict(path=str(args.inventory.resolve()), sha256=hashlib.sha256(inventory_raw).hexdigest()),
        modules=[dict(path=str(p.resolve()), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sources],
        rows=rows, elapsed_seconds=time.monotonic()-started, provider_calls=0,
        native_executions=0, reads_evaluation_outcomes=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2)+'\n')


if __name__ == '__main__':
    main()
