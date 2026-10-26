"""Independent paired source-global lookup census; no truth or native inputs.

This runner reuses the original-source artifact and AST audit only. Each search
mode gets its own lookup-derived pair schedule; schedules need not be equal.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ''}:
    sys.path.insert(0, str(ROOT))

from scripts.census_observation_address_join import (
    audit_candidate, data_sha, freeze, local_modules, read, require, sha,
    verify_modules, write,
)


def verify_lookup_rows(bank, demands, queries, *, mode):
    """Recompute membership from exposed keys; source-summary truth is separate."""
    require(mode in {'receiver_only', 'address'}, 'Unexpected lookup mode')
    donors = {row['id']: row for row in bank}
    demand_by_id = {row['id']: row for row in demands}
    require(len(donors) == len(bank), 'Duplicate donor identity')
    require(len(demand_by_id) == len(demands), 'Duplicate demand identity')
    require(len(queries) == len(demands), 'Exactly one lookup receipt required per demand')
    require({row['demand_id'] for row in queries} == set(demand_by_id), 'Lookup demand population mismatch')
    raw_hits = retrieved = 0
    for query in queries:
        demand = demand_by_id[query['demand_id']]
        require(query.get('owner_key', demand['owner_key']) == demand['owner_key'], 'Lookup owner metadata mismatch')
        if 'lookup_kind' in query:
            require(query['lookup_kind'] == ('owner' if mode == 'receiver_only' else 'owner_field'), 'Lookup kind mismatch')
            require(query['field'] == (None if mode == 'receiver_only' else demand['field']), 'Lookup field metadata mismatch')
        expected = {row['id'] for row in bank if row['owner_key'] == demand['owner_key']
                    and (mode == 'receiver_only' or demand['field'] in row['fields'])}
        actual = query['all_hit_ids']
        require(len(actual) == len(set(actual)) and set(actual) == expected,
                'Lookup membership is not implied by frozen bank keys')
        selected = query['retrieved_ids']
        require(selected == actual[:len(selected)], 'Retrieved donors must preserve raw lookup prefix')
        require(len(selected) == len(actual), 'Undeclared per-query retrieval truncation')
        raw_hits += len(actual)
        retrieved += len(selected)
    return dict(query_count=len(queries), raw_retrieved_count=raw_hits, retrieved_count=retrieved,
                membership_basis='exposed source summary owner/field keys; effect validity not proved')


def verify_source_refs(value, corpus):
    """Validate bounds and explicit text/value provenance without executing code."""
    count = 0
    def excerpt(at):
        nonlocal count
        raw = corpus['sources'][at['path']]['code'].encode()
        begin, end = at['start_byte'], at['end_byte']
        require(0 <= begin <= end <= len(raw), 'Original-source evidence outside frozen corpus')
        count += 1
        return raw[begin:end].decode()
    def visit(node):
        if isinstance(node, dict):
            if {'path','start_byte','end_byte'} <= set(node):
                excerpt(node)
            if 'text' in node and 'span' in node and isinstance(node['span'],dict):
                require(node['text'] == excerpt(node['span']), 'Actual argument text/span provenance mismatch')
            if 'text' in node and 'value_span' in node:
                require(node['text'] == excerpt(node['value_span']), 'Literal definition text/span provenance mismatch')
            for child in node.values():
                visit(child)
        elif isinstance(node,(list,tuple)):
            for child in node:
                visit(child)
    visit(value)
    return count


def snapshot_sources(seals, output):
    snapshots = []
    for filename, digest in sorted(seals.items()):
        source = Path(filename)
        require(sha(source) == digest, 'Source changed before snapshot: ' + filename)
        destination = output / 'frozen_sources' / source.relative_to(ROOT)
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(source.read_bytes())
        require(sha(destination) == digest, 'Frozen source snapshot mismatch')
        snapshots.append(dict(source=filename, sha256=digest, snapshot=str(destination.resolve())))
    return snapshots


def verify_frontend_linkage(result, frontend):
    """Every bank/read call must be an unchanged call in the frozen frontend."""
    calls = {row['id']: row for row in frontend['calls']}
    count = 0
    for row in result['full_source_bank']:
        original = calls[row['id']]
        require(row['call'] == original['span'] and row['source_test_id'] == original['test_id'],
                'Donor source call differs from frozen frontend')
        require(row['fields'] == sorted({effect['field'] for effect in row['write_effects']})
                and all(effect['owner_key'] == row['owner_key'] for effect in row['write_effects']),
                'Donor lookup keys differ from reported write summaries')
        count += 1
    for row in result['demand_rows']:
        original = calls[row['call_id']]
        require(row['call'] == original['span'] and row['source_test_id'] == original['test_id'],
                'Read source call differs from frozen frontend')
        require(row['owner_key'] == row['read_effect']['owner_key']
                and row['field'] == row['read_effect']['field'], 'Demand lookup keys differ from read summary')
        count += 1
    return count


def verify_search_receipt(result, mode, budget):
    require(result['mode'] == mode, 'Wrong mode receipt')
    require(result['budget'] == budget, 'Mode budget differs from protocol')
    require(result['provider_calls'] == result['native_executions'] == 0, 'Unexpected execution claim')
    bank, demands = result['full_source_bank'], result['demand_rows']
    require(result['full_source_bank_count'] == len(bank)
            and result['full_source_bank_sha256'] == data_sha(bank), 'Full bank receipt mismatch')
    require(result['indexed_demand_count'] == len(demands)
            and result['demand_population_sha256'] == data_sha(demands), 'Demand population receipt mismatch')
    lookup = verify_lookup_rows(bank, demands, result['queries'], mode=mode)
    for key in ('query_count', 'raw_retrieved_count', 'retrieved_count'):
        require(result[key] == lookup[key], 'Lookup count mismatch: ' + key)
    planned, attempted = result['scheduled_pairs'], result['attempted_pairs']
    require(result['scheduled_pair_count'] == len(planned) <= budget['max_attempts'], 'Planned pair schedule exceeds budget')
    retrieved = {query['demand_id']: set(query['retrieved_ids']) for query in result['queries']}
    require(all(pair['donor_bank_id'] in retrieved[pair['demand_id']] for pair in planned),
            'Scheduled donor pair was not retrieved by this mode lookup')
    require(len(planned) == min(lookup['retrieved_count'], budget['max_attempts']), 'Schedule has missing eligible pairs')
    require(len({(pair['demand_id'],pair['donor_bank_id']) for pair in planned}) == len(planned), 'Duplicate scheduled pair')
    require(result['attempts'] == len(attempted) <= len(planned)
            and attempted == planned[:len(attempted)], 'Actual pairs must be a prefix of mode schedule')
    require(len(result['candidates']) <= min(result['attempts'], budget['max_candidates']), 'Candidate cap exceeded')
    require(sum(result['pair_skipped'].values()) + len(result['candidates']) == result['attempts'],
            'Attempted pair outcomes do not account for all attempts')
    require(result['pair_schedule_sha256'] == data_sha(planned), 'Planned pair hash mismatch')
    require(result['attempted_pair_schedule_sha256'] == data_sha(attempted), 'Attempted pair hash mismatch')
    timings = result['timings']
    require(all(isinstance(value,(int,float)) and value >= 0 for value in timings.values()), 'Invalid source timing')
    require(sum(timings[key] for key in ('index_seconds','bank_seconds','demand_seconds'))
            <= timings['preprocessing_seconds'] + 1e-6, 'Preanalysis component timing mismatch')
    require(abs(timings['preprocessing_seconds']+timings['search_seconds']-timings['total_seconds']) < 1e-6,
            'Total timing mismatch')
    return lookup


def run(args):
    requested_sources = set()
    for specification in args.source_sha:
        filename, digest = specification.rsplit('=', 1)
        path = (ROOT / filename).resolve()
        require(path.is_relative_to(ROOT) and sha(path) == digest, 'Requested source freeze mismatch: ' + filename)
        requested_sources.add(path)
    require({ROOT/'prototypes'/filename for filename in ('observation_address_search.py',
            'observation_address_join.py','observation_address_effects.py')} <= requested_sources,
            'Freeze must name search, join, and effect modules before import')
    generator = importlib.import_module('prototypes.observation_address_search')
    seals = local_modules()
    inventory, protocol = read(args.inventory), read(args.protocol)
    require(inventory['case_count'] == 17 and len(inventory['cases']) == 17, 'Expected frozen17 cases')
    require(protocol['inventory']['sha256'] == sha(args.inventory), 'Protocol inventory hash mismatch')
    require(protocol['case_order'] == [row['case'] for row in inventory['cases']], 'Frozen case order mismatch')
    expected_budget = dict(max_candidates=16, max_attempts=128)
    require(protocol['budget'] == expected_budget, 'Protocol budget mismatch')
    budget = generator.JoinBudget(**expected_budget)
    started = time.monotonic()
    write(args.output / 'protocol.json', dict(inventory=freeze(args.inventory), protocol=freeze(args.protocol),
        evaluator=freeze(__file__), initial_source_seals=seals, required_source_freezes=args.source_sha,
        source_only=True, provider_calls=0, native_executions=0))
    snapshot_sources(seals, args.output)
    cases = []
    for entry in inventory['cases']:
        for kind in ('corpus', 'frontend'):
            require(sha(entry[kind]['path']) == entry[kind]['sha256'], 'Frozen input file changed')
        corpus, frontend = read(entry['corpus']['path']), read(entry['frontend']['path'])
        inputs = dict(corpus=data_sha(corpus), frontend=data_sha(frontend))
        variants = {}
        for mode in ('receiver_only', 'address'):
            verify_modules(seals)
            t0 = time.monotonic()
            result = generator.generate(corpus, frontend, mode=mode, budget=budget)
            path = args.output / entry['case'] / (mode + '.json')
            write(path, result)
            require(inputs == dict(corpus=data_sha(corpus), frontend=data_sha(frontend)), 'Generator mutated input data')
            lookup = verify_search_receipt(result, mode, expected_budget)
            source_reference_checks = verify_source_refs([result['full_source_bank'],result['demand_rows']],corpus)
            frontend_call_checks = verify_frontend_linkage(result,frontend)
            audits = [audit_candidate(candidate, corpus, path.parent / mode) for candidate in result['candidates']]
            audit_path = path.parent / (mode + '_independent_source_audit.json')
            write(audit_path, dict(candidates=audits, lookup=lookup, source_reference_checks=source_reference_checks,
                                  frontend_call_checks=frontend_call_checks, no_native_or_oracle_claim=True))
            variants[mode] = dict(output=freeze(path), independent_audit=freeze(audit_path),
                wall_seconds=time.monotonic()-t0, attempts=result['attempts'], candidates=len(audits),
                ast_novel=sum(row['ast_novel'] for row in audits),
                ast_ids=[(row['base_test_id'], row['generated_ast_sha256']) for row in audits],
                unique_ast_candidates=len({(row['base_test_id'], row['generated_ast_sha256']) for row in audits}),
                bank_count=result['full_source_bank_count'], bank_sha256=result['full_source_bank_sha256'],
                demand_count=result['indexed_demand_count'], demand_sha256=result['demand_population_sha256'],
                lookup=lookup, scheduled_pair_count=len(result['scheduled_pairs']),
                pair_schedule_sha256=result['pair_schedule_sha256'], pair_skipped=result['pair_skipped'],
                bank_skipped=result['bank_skipped'], demand_skipped=result['demand_skipped'],
                source_reference_checks=source_reference_checks, timings=result['timings'],
                lookup_and_schedule_seconds=result['timings']['preprocessing_seconds']
                    -sum(result['timings'][key] for key in ('index_seconds','bank_seconds','demand_seconds')),
                key_substitutions=sum(bool(row['key_substitution']) for row in audits))
            verify_modules(seals)
            seals.update(local_modules())
            snapshot_sources(seals, args.output)
        left, right = variants['receiver_only'], variants['address']
        for key in ('bank_count', 'bank_sha256', 'demand_count', 'demand_sha256'):
            require(left[key] == right[key], 'Mode domain mismatch: ' + key)
        lhs, rhs = set(map(tuple, left['ast_ids'])), set(map(tuple, right['ast_ids']))
        cases.append(dict(case=entry['case'], language=entry['language'], variants=variants,
            input_data_seals=inputs, input_data_unchanged=True, shared_domain_verified=True,
            shared_ast_candidates=len(lhs & rhs), address_only_ast_candidates=len(rhs-lhs),
            receiver_only_ast_candidates=len(lhs-rhs)))
        print(json.dumps(dict(case=entry['case'], bank=left['bank_count'], demands=left['demand_count'],
            control_raw_hits=left['lookup']['raw_retrieved_count'], treatment_raw_hits=right['lookup']['raw_retrieved_count'],
            control_candidates=left['candidates'], treatment_candidates=right['candidates'])), flush=True)
    verify_modules(seals)
    manifest = args.output / 'manifest.json'
    write(manifest, dict(version='independent-source-global-observation-address-census.v1',
        created_utc=datetime.now(timezone.utc).isoformat(), seconds=time.monotonic()-started,
        inventory=freeze(args.inventory), protocol=freeze(args.protocol), evaluator=freeze(__file__),
        source_seals=seals, source_snapshots=snapshot_sources(seals,args.output),
        fixed_case_denominator=17, budget=expected_budget, cases=cases, provider_calls=0,native_executions=0,
        timing_scope='Generator timings separate source preanalysis and pair rendering; independent wall_seconds also includes hash validation, source auditing and artifact writes. Modes are run once in fixed control-first order, not a repeated timing benchmark.',
        native_influence='not_measured',oracle_validity='unassessed',valid_gap_retention='not_measured',
        false_positive_reduction='not_measured'))
    print(json.dumps(dict(manifest=freeze(manifest))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    for name in ('inventory', 'protocol', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-sha', action='append', required=True, help='Frozen local path=sha256; repeat for dependencies')
    run(parser.parse_args())
