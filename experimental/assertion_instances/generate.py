"""Bounded v3 analogy search with the helper-call instance as its sole unit."""
from collections import Counter, defaultdict, deque
from dataclasses import asdict
import difflib

from anchor_retrieval.syntax import Source, walk
from experimental.generic_v2.generate import Budget, _binding_labels, _canonical, _diverse_neighbors, _refine
from generic_composition.corpus import source_text
from generic_composition.engine import gate_evidence as _source_evidence
from generic_composition.terms import BudgetExceeded
from .core import _id, _one_statement_tree, compose, extract


def _round_robin(rows, group, priority=lambda key: key):
    bins = defaultdict(deque)
    for row in rows:
        bins[group(row)].append(row)
    while bins:
        for key in sorted(list(bins), key=priority):
            yield bins[key].popleft()
            if not bins[key]:
                del bins[key]


def _statement_key(text, language, parameters, max_nodes):
    """Host AST novelty independent of flat/balanced literal representation."""
    code = 'package p\nfunc generated() {\n' + text + '\n}\n' if language == 'go' else text
    source = Source('novelty', code, language)
    if source.root.has_error:
        raise ValueError('novelty_statement_parse_error')
    node = next(n for n in walk(source.root) if n.type == 'expression_statement')
    tree, original = _one_statement_tree(source, node, max_nodes)
    labels = {(0,) + path: label for path, label in
              _binding_labels(source, node, original, parameters).items()}
    return _canonical(tree.term, labels)


def _json_provenance(value):
    # Kernels may keep Term/Hole-keyed substitutions for internal witnesses.
    # Reconstruction checks and source spans survive; syntax objects do not.
    if isinstance(value, dict):
        return {key: _json_provenance(item) for key, item in value.items()
                if key not in {'source_substitutions', 'target_substitutions'}}
    if isinstance(value, (list, tuple)):
        return [_json_provenance(item) for item in value]
    return value


def generate(corpus, budget=Budget(), *, refine=_refine):
    if any(type(value) is not int or value < 1 for value in asdict(budget).values()):
        raise ValueError('Generation budgets must be positive integers')
    ordered = sorted(corpus['tests'].values(), key=lambda test: (test.get('retrieval_rank') or 99999, test['id']))
    seeds = {t['id'] for t in ordered if t.get('retrieval_rank') and t['retrieval_rank'] <= budget.top_k}
    if not seeds:
        seeds = {t['id'] for t in ordered[:budget.top_k]}
    priority = lambda tid: (tid not in seeds, corpus['tests'][tid].get('retrieval_rank') or 99999, tid)
    # Corpus construction already bounds source material. Group truncation is
    # parent-fair below; a long first test cannot consume a global instance cap.
    extracted = extract(corpus, max_instances=max(1, len(corpus['capsules'])), max_nodes=budget.max_nodes)
    skipped, records, groups, existing = Counter(extracted['skipped']), {}, defaultdict(list), defaultdict(set)
    for record in extracted['instances']:
        if len(record['text'].encode()) > budget.max_body_bytes:
            skipped['instance_byte_budget'] += 1
            continue
        existing[record['group_key']].add(_canonical(record['tree'].term, record['bindings']))
        try:
            refined = refine(record, budget.max_nodes)  # Cached once per input.
        except BudgetExceeded:
            skipped['refined_instance_node_budget'] += 1
            continue
        records[record['instance_id']] = refined
        groups[record['group_key']].append(refined)
    queues, group_evidence = [], []
    for group, members in sorted(groups.items(), key=lambda row: repr(row[0])):
        if not any(row['parent_test_id'] in seeds for row in members):
            continue
        members = sorted(members, key=lambda r: (priority(r['parent_test_id']), r['span']['start_byte'], r['instance_id']))
        members = list(_round_robin(members, lambda r: r['parent_test_id'], priority))
        skipped['group_instance_budget'] += max(0, len(members) - budget.max_group_tests)
        members = members[:budget.max_group_tests]
        group_evidence.append({'instances': [r['instance_id'] for r in members],
                               'parent_test_counts': dict(Counter(r['parent_test_id'] for r in members))})
        if len(members) < 3:
            skipped['fewer_than_three_instances'] += 1
            continue
        for A in members:
            neighbors = sorted((r for r in members if r is not A), key=lambda r: (
                -difflib.SequenceMatcher(a=A['skeleton'], b=r['skeleton'], autojunk=False).ratio(), r['instance_id']))
            edits = _diverse_neighbors(neighbors)[:budget.edit_neighbors]
            proposals = deque((A, B, C) for C in neighbors[:budget.target_neighbors] for B in edits
                              if B is not C and seeds.intersection(r['parent_test_id'] for r in (A, B, C)))
            if proposals:
                queues.append(proposals)
    attempts, pool, rules, seen = 0, {}, {}, set()
    mechanical_cache, source_cache, novelty_cache = {}, {}, {}
    # One proposal from each A focus per pass, just as in the body driver.
    while queues and attempts < budget.max_attempts:
        active = []
        for index, queue in enumerate(queues):
            A, B, C = queue.popleft()
            if queue:
                active.append(queue)
            triple = tuple(r['instance_id'] for r in (A, B, C))
            if triple in seen:
                continue
            seen.add(triple)
            attempts += 1
            result = compose(corpus, A, B, C, max_nodes=budget.max_nodes, max_holes=budget.max_holes,
                             refine=lambda record, _: record, mechanical_cache=mechanical_cache,
                             source_cache=source_cache)
            if result['status'] != 'hypothesis':
                skipped[result['reason']] += 1
            else:
                candidate, rule = result['candidate'], result['rule']
                after = candidate['edits'][0]['after']
                novelty_key = (corpus['language'], tuple(C['test']['parameters']), after)
                if novelty_key not in novelty_cache:
                    novelty_cache[novelty_key] = _statement_key(after, corpus['language'], C['test']['parameters'], budget.max_nodes)
                key = _id('assertion_instance_output', C['parent_test_id'], C['span'], after)
                if novelty_cache[novelty_key] in existing[C['group_key']]:
                    skipped['existing_combination'] += 1
                elif key in pool:
                    skipped['duplicate_target_edit'] += 1
                else:
                    candidate.update(id=key, focus_instance_id=C['instance_id'], source_instance_ids=list(triple))
                    mechanical = candidate['provenance']['binding_analysis']
                    candidate['binding_check'] = {k: mechanical[k] for k in ('status', 'errors', 'unknowns')}
                    pool[key], rules[rule['id']] = candidate, rule
            if attempts >= budget.max_attempts:
                active.extend(queues[index + 1:])
                break
        queues = active
    skipped['attempt_budget_remaining_triples'] += sum(len(queue) for queue in queues)
    # Rotate parents, and within each parent rotate C call locations.
    parent_rows = defaultdict(list)
    for candidate in sorted(pool.values(), key=lambda c: (len(c['edits'][0]['after']), c['id'])):
        parent_rows[candidate['base_test_id']].append(candidate)
    fair = [c for tid in sorted(parent_rows, key=priority) for c in
            _round_robin(parent_rows[tid], lambda c: c['focus_instance_id'])]
    selected = list(_round_robin(fair, lambda c: c['base_test_id'], priority))[:budget.max_candidates]
    used = {c['rule_id'] for c in selected}
    result = {'algorithm': 'test_edit_analogy_assertion_instances', 'unit': 'source_backed_oracle_helper_call',
              'budget': asdict(budget), 'candidates': selected, 'rules': [rules[r] for r in sorted(used)],
              'counts': {'seed_tests': len(seeds), 'eligible_tests': len({r['parent_test_id'] for r in records.values()}),
                         'eligible_instances': len(records), 'groups': len(groups), 'attempted_triples': attempts,
                         'candidate_pool': len(pool), 'candidates': len(selected)},
              'binding_statuses': dict(Counter(m['status'] for m in mechanical_cache.values())),
              'group_selection': group_evidence, 'skipped': dict(skipped), 'extraction_unsupported': extracted['unsupported'],
              'novelty_precision': 'host_ast_trivia_ignored_restricted_unique_local_alpha',
              'coverage': corpus.get('coverage', {}), 'reference_inputs': False, 'execution_outcomes': False}
    return _json_provenance(result)


def gate_evidence(corpus, generated, issue):
    evidence, candidates = _source_evidence(corpus, generated, issue)
    instances, sources = {}, {}
    for candidate in candidates:
        sources[candidate['rule_id']] = {}
        for role, source in candidate['provenance']['sources'].items():
            uid = source['instance_id']
            sources[candidate['rule_id']][role] = uid
            ports = [dict({k: port[k] for k in ('helper_id', 'helper_assertion_span', 'parameter', 'slot', 'keyword', 'roles')},
                          actual={k: port['actual'][k] for k in ('text', 'span')})
                     for port in candidate['provenance']['source_assertion_ports'][role]]
            instances[uid] = {'parent_test_id': source['test_id'], 'statement_span': source['span'],
                              'statement': source['text'], 'ports': ports}
    # Include full definitions rather than silently omitting a large helper.
    definitions = {}
    for tid in evidence['source_tests']:
        for helper in corpus['tests'][tid]['support']['helpers']:
            definitions[helper['id']] = {'span': helper['span'], 'code': source_text(corpus, helper['span'])}
    evidence.update(assertion_instances=instances, analogy_sources=sources, helper_definitions=definitions,
                    unit_policy='A/B/C are call instances and may occur in the SAME parent test. They are not three independent tests.',
                    oracle_policy='The helper-call input and expected arguments are jointly transported. Source reconstruction is not oracle validity.',
                    composition_policy='Only the C call is replaced in a full parent clone; all other parent statements remain. '
                    'Judge the entire edited parent and helper, including global/parameter effects, aliasing and later assertions. '
                    'Literal/parameter argument closure does not establish independence or purity.')
    evidence.pop('test_helpers', None)  # Full helper_definitions supersedes the truncated legacy view.
    return evidence, candidates
