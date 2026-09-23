"""Controlled v3 driver: v2 search budgets with explicit statement alignment.

The shared corpus, parameter-row adapter, lexical refinement, emitter contract
and semantic gate are unchanged. Both gap orders share one triple/output budget.
"""
from collections import Counter, defaultdict, deque
from dataclasses import asdict
import difflib
import re
import textwrap

from anchor_retrieval.syntax import Source, child, walk
from generic_composition.terms import BudgetExceeded, from_source, render
from experimental.generic_v2.bindings import analyze_bindings
from experimental.generic_v2.parameter_rows import instantiate
from experimental.generic_v2.generate import (
    Budget, _binding_labels, _canonical, _diverse_neighbors, _id, _literal_roles,
    _producers, _refine, _roles, _scope, _skeleton, _source,
    gate_evidence as _v2_evidence,
)
from .alignment import align_analogy


def _novelty(term, language, parameters, indentation=''):
    """Reindex actual declarations after inserting setup, not old B ordinals."""
    text = render(term)
    if language == 'python':
        code = textwrap.dedent(indentation + text)
        source = Source('body.py', code, language)
        node = source.root
    else:
        prefix = 'package p\nfunc generated() ' if language == 'go' else 'function generated() '
        source = Source('body', prefix + text, language)
        node = next(n for n in walk(source.root) if n.type in {'block', 'statement_block'})
    converted = from_source(source, node)
    labels = _binding_labels(source, node, converted, parameters)
    # Whitespace changes preserve tree paths. The original, refined token tree
    # remains the novelty representation; only declaration labels are refreshed.
    return _canonical(term, labels)


def generate(corpus: dict, budget: Budget = Budget(), *, refine=_refine) -> dict:
    """Return JSON-serializable candidates compatible with the existing emitter."""
    if any(type(v) is not int or v < 1 for v in asdict(budget).values()):
        raise ValueError('Generation budgets must be positive integers')
    skipped, capsules, records, sources, source_nodes = Counter(), defaultdict(list), {}, {}, {}
    for capsule in corpus['capsules']:
        capsules[capsule['test_id']].append(capsule)
    ordered = sorted(corpus['tests'].values(), key=lambda t: (t['retrieval_rank'] or 99999, t['id']))
    seeds = {t['id'] for t in ordered if t['retrieval_rank'] and t['retrieval_rank'] <= budget.top_k}
    if not seeds:
        seeds = {t['id'] for t in ordered[:budget.top_k]}
    for test in ordered:
        path = test['span']['path']
        metadata = corpus['sources'][path]
        if not metadata.get('complete_file', True) or metadata.get('parse_error'):
            skipped['incomplete_or_unparseable_source'] += 1
            continue
        if test.get('parameterization_status', 'none_detected') not in {'none_detected', 'expanded_literal_rows'}:
            skipped['parameterized_body_not_instantiated'] += 1
            continue
        if not capsules[test['id']] or not test.get('enclosing_scope_span'):
            skipped['missing_observation_or_scope'] += 1
            continue
        if path not in sources:
            sources[path] = Source(path, metadata['code'], corpus['language'])
            source_nodes[path] = {}
            for n in walk(sources[path].root):
                position = (n.start_byte, n.end_byte)
                # A one-statement Python block and its statement share a span.
                # Alignment needs the actual statement-list grammar node.
                if position not in source_nodes[path] or n.type in {'block', 'statement_block'}:
                    source_nodes[path][position] = n
        source = sources[path]
        body = test['body_span']
        if body['end_byte'] - body['start_byte'] > budget.max_body_bytes:
            skipped['body_byte_budget'] += 1
            continue
        node = source_nodes[path].get((body['start_byte'], body['end_byte']))
        if node is None:
            skipped['body_node_missing'] += 1
            continue
        if node.type not in {'block', 'statement_block'}:
            skipped['body_statement_list_unsupported'] += 1
            continue
        try:
            converted = from_source(source, node, max_nodes=budget.max_nodes)
        except BudgetExceeded:
            skipped['body_node_budget'] += 1
            continue
        producers = _producers(capsules[test['id']])
        if not producers:
            skipped['no_observed_producer'] += 1
            continue
        line_prefix = source.data[source.data.rfind(b'\n', 0, body['start_byte']) + 1:body['start_byte']].decode()
        record = {'test': test, 'instance_id': test['id'], 'tree': converted,
                  'text': render(converted.term), 'original_text': render(converted.term),
                  'producers': producers,
                  'skeleton': _skeleton(converted.term),
                  'indentation': re.match(r'[ \t]*', line_prefix).group(),
                  'bindings': _binding_labels(source, node, converted, test['parameters'])}
        record['literal_roles'] = _literal_roles(record, corpus, capsules[test['id']])
        if test.get('parameterization_status') == 'expanded_literal_rows':
            instances, omissions = instantiate(record, source, node, max_nodes=budget.max_nodes)
            skipped.update(omissions)
        else:
            instances = [record]
        for instance in instances:
            try:
                records[instance['instance_id']] = refine(instance, budget.max_nodes)
            except BudgetExceeded:
                skipped['refined_body_node_budget'] += 1
    groups = defaultdict(list)
    existing = defaultdict(set)
    for record in records.values():
        existing[_scope(record['test'])].add(_novelty(record['tree'].term, corpus['language'], record['test']['parameters'], record['indentation']))
        for producer in record['producers']:
            groups[(_scope(record['test']), producer)].append(record)
    queues = []
    for group, members in sorted(groups.items(), key=lambda row: repr(row[0])):
        if not any(row['test']['id'] in seeds for row in members):
            continue
        members = sorted(members, key=lambda r: (r['test']['id'] not in seeds, r['instance_id']))
        skipped['group_test_budget'] += max(0, len(members) - budget.max_group_tests)
        members = members[:budget.max_group_tests]
        if len(members) < 3:
            skipped['fewer_than_three_tests'] += 1
            continue
        for A in members:
            proposals = deque()
            neighbors = sorted((r for r in members if r is not A), key=lambda r: (
                -difflib.SequenceMatcher(a=A['skeleton'], b=r['skeleton'], autojunk=False).ratio(),
                r['instance_id']))
            edit_neighbors = _diverse_neighbors(neighbors)[:budget.edit_neighbors]
            for C in neighbors[:budget.target_neighbors]:
                for B in edit_neighbors:
                    ids = (A['test']['id'], B['test']['id'], C['test']['id'])
                    if B is not C and seeds.intersection(ids):
                        proposals.append((group, A, B, C))
            if proposals:
                queues.append(proposals)
    attempted, pool, rules, seen = 0, {}, {}, set()
    mechanical_cache, binding_statuses = {}, Counter()
    attempted_orders = 0
    while queues and attempted < budget.max_attempts:
        active = []
        for queue_index, queue in enumerate(queues):
            group, A, B, C = queue.popleft()
            triple = tuple(r['instance_id'] for r in (A, B, C))
            if queue:
                active.append(queue)
            if triple in seen:
                continue
            seen.add(triple)
            attempted += 1
            options = dict(roles=_roles(A, B, C), max_nodes=budget.max_nodes, max_holes=budget.max_holes)
            first = align_analogy(A['tree'], B['tree'], C['tree'], **options)
            variants = [first]
            if first.provenance.get('has_shared_gap'):
                variants.append(align_analogy(A['tree'], B['tree'], C['tree'], order='edit_first', **options))
            attempted_orders += len(variants)
            for result in variants:
                known, mechanical = False, None
                if result.status == 'hypothesis':
                    known = _novelty(result.output, corpus['language'], C['test']['parameters'], C['indentation']) in existing[_scope(C['test'])]
                    if not known:
                        after = render(result.output)
                        key = _id(C['instance_id'], after)
                        if key not in mechanical_cache:
                            position = C['test']['body_span']
                            mechanical_cache[key] = analyze_bindings(sources[position['path']], corpus['language'],
                                position['start_byte'], after, end_byte=position['end_byte'])
                            binding_statuses[mechanical_cache[key]['status']] += 1
                        mechanical = mechanical_cache[key]
                if result.status != 'hypothesis':
                    skipped['analogy:' + result.reason] += 1
                elif known:
                    skipped['existing_combination'] += 1
                elif mechanical['status'] == 'invalid':
                    skipped['mechanically_invalid_proposal'] += 1
                else:
                    if key not in pool:
                        rid = _id('test_edit_analogy_v3', triple, result.provenance['gap_order'])
                        rule = {'id': rid, 'kind': 'statement_aligned_test_edit_analogy', 'before_span': A['test']['body_span'],
                                'after_span': B['test']['body_span'], 'semantic_status': 'hypothesis_from_test_edit',
                                'source_test_ids': list(dict.fromkeys(r['test']['id'] for r in (A, B, C))),
                                'source_instance_ids': list(triple), 'producer': group[1]}
                        provenance = {k: v for k, v in result.provenance.items()
                                      if k not in {'source_substitutions', 'target_substitutions'}}
                        provenance.update(sources={name: _source(record) for name, record in zip('ABC', (A, B, C))},
                                          binding_precision='single_scope_unique_declarations; correspondence_hypothesis',
                                          binding_analysis=mechanical)
                        pool[key] = {'id': key, 'base_test_id': C['test']['id'],
                                     'source_test_ids': list(dict.fromkeys(r['test']['id'] for r in (A, B))),
                                     'language': corpus['language'], 'kind': rule['kind'], 'rule_id': rid, 'imports': [],
                                     'binding_check': {k: mechanical[k] for k in ('status', 'errors', 'unknowns')},
                                     'alignment': {k: result.provenance[k] for k in ('alignment', 'gap_order', 'has_shared_gap', 'unproved')},
                                     'edits': [{'span': C['test']['body_span'], 'before': C['original_text'], 'after': after},
                                               *C.get('extra_edits', [])],
                                     'oracle': {'mode': 'transport_from_source', 'source_test_id': B['test']['id'],
                                                'binding_source_test_id': C['test']['id'],
                                                'assertion_ids': [a['id'] for a in capsules[B['test']['id']]],
                                                'semantic_status': 'requires_admission'}, 'provenance': provenance}
                        rules[rid] = rule
            if attempted >= budget.max_attempts:
                active.extend(queues[queue_index + 1:])
                break
        queues = active
    skipped['attempt_budget_remaining_triples'] += sum(len(q) for q in queues)
    bins = defaultdict(deque)
    for candidate in sorted(pool.values(), key=lambda p: (len(p['edits'][0]['after']), p['id'])):
        bins[candidate['base_test_id']].append(candidate)
    selected = []
    while bins and len(selected) < budget.max_candidates:
        for tid in sorted(list(bins), key=lambda tid: (tid not in seeds, tid)):
            selected.append(bins[tid].popleft())
            if not bins[tid]:
                del bins[tid]
            if len(selected) >= budget.max_candidates:
                break
    used = {c['rule_id'] for c in selected}
    return {'algorithm': 'test_edit_analogy_v3_statement_alignment_erasing', 'budget': asdict(budget), 'candidates': selected,
            'rules': [rules[key] for key in sorted(used)], 'skipped': dict(skipped),
            'counts': {'seed_tests': len(seeds), 'eligible_tests': len(records), 'groups': len(groups),
                       'attempted_triples': attempted, 'attempted_orders': attempted_orders, 'candidate_pool': len(pool), 'candidates': len(selected)},
            'binding_statuses': dict(binding_statuses),
            'novelty_precision': 'trivia_ignored_single_scope_local_reindexed_after_composition',
            'coverage': corpus.get('coverage', {}), 'reference_inputs': False, 'execution_outcomes': False}



def gate_evidence(corpus, generated, issue):
    evidence, candidates = _v2_evidence(corpus, generated, issue)
    evidence['composition_policy'] = (
        'Direct statement lists were aligned by statement shape and call-head spelling. '
        'Unmatched C setup remains once in source order; B additions use the displayed gap order. '
        'This does not prove bindings, effect order, absence of duplicated inline effects, or the oracle. '
        'Erasing source parameters is allowed only as an explicit reconstruction hypothesis.')
    return evidence, candidates
