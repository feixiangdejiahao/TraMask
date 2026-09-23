"""Bounded automatic A:B :: C:D search over an existing test corpus.

Whole bodies are transported within one file and enclosing scope. No project,
API spelling, issue keyword, execution outcome or reference implementation
selects a rule. Syntactic binding correspondences are hypotheses, not a general
scope/type/effect proof. Literal parameter rows use a separate framework adapter.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import difflib
import hashlib
import json

from anchor_retrieval.syntax import Source, child, walk
from generic_composition.corpus import source_text
from generic_composition.engine import gate_evidence as _v1_evidence
from generic_composition.terms import BudgetExceeded, Hole, Term, from_source, render, subterms
from .analogy import analogy
from .bindings import analyze_bindings
from .literals import refine_strings
from .parameter_rows import instantiate


@dataclass(frozen=True)
class Budget:
    max_candidates: int = 128
    top_k: int = 10
    max_group_tests: int = 64
    target_neighbors: int = 8
    edit_neighbors: int = 12
    max_attempts: int = 2000
    max_nodes: int = 1500
    max_holes: int = 32
    max_body_bytes: int = 8000


def _id(*values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def _inside(a, b):
    return a['path'] == b['path'] and b['start_byte'] <= a['start_byte'] and a['end_byte'] <= b['end_byte']


def _scope(test):
    span = test['enclosing_scope_span']
    return test['span']['path'], span['start_byte'], span['end_byte'], tuple(test['parameters'])


def _callee(call):
    identity = call.get('callee_identity') or {}
    return identity.get('canonical') or identity.get('scope_key') or call['span']['path'] + '::' + call['callee']


def _producers(capsules):
    result = set()
    for capsule in capsules:
        observed = capsule.get('observation_value_sources', [])
        for call in capsule['calls']:
            if any(_inside(call['span'], span) for span in observed):
                result.add(_callee(call))
    return result


_DECLARATIONS = {'assignment', 'short_var_declaration', 'variable_declarator', 'var_spec'}
_NESTED_BINDERS = {'function_definition', 'function_declaration', 'func_literal', 'lambda',
                   'arrow_function', 'function_expression', 'class_definition'}


def _declared_names(source, target):
    if target.type == 'identifier':
        return [source.text(target)]
    if target.type in {'tuple', 'list', 'pattern_list', 'expression_list', 'tuple_pattern', 'list_pattern'}:
        return [name for node in target.named_children for name in _declared_names(source, node)]
    return []  # Attribute/subscript writes and unimplemented binding patterns.


def _binding_labels(source, node, converted, parameters):
    """Single-scope, uniquely declared locals; no spelling-based global rename.

    A local's ordinal is a structural correspondence proposal across tests,
    not a claim that their runtime values are equal. Nested binders disable
    local correspondence inference. Property and global names keep their names.
    """
    nodes = list(walk(node))
    declarations = []
    if not any(n.type in _NESTED_BINDERS for n in nodes if n != node):
        for current in nodes:
            if current.type in _DECLARATIONS:
                target = child(current, 'left', 'name')
                if target is not None:
                    declarations.extend(_declared_names(source, target))
    counts = Counter(declarations)
    locals_ = {name: i for i, name in enumerate(dict.fromkeys(declarations)) if counts[name] == 1}
    by_span = {(n.start_byte, n.end_byte): n for n in nodes}
    labels = {}
    for path, term in subterms(converted.term):
        if not isinstance(term, Term) or not term.kind.endswith('identifier'):
            continue
        span = converted.spans[path]
        original = by_span.get((span.start_byte, span.end_byte))
        parent = original.parent if original is not None else None
        field = None
        if parent is not None:
            field = next((parent.field_name_for_child(i) for i, n in enumerate(parent.children)
                          if n == original), None)
        name = str(term.atom)
        if field in {'attribute', 'property', 'field'} or term.kind in {'field_identifier', 'property_identifier'}:
            role = ('property', name)
        elif name in locals_:
            role = ('single_scope_local', locals_[name])
        elif name in parameters:
            role = ('parameter', parameters.index(name))
        else:
            role = ('global_or_unresolved', name)
        labels[path] = role
    return labels


def _literal_roles(record, corpus, capsules):
    """Ports and expected-side positions disambiguate repeated equal atoms."""
    inputs, expected = [], []
    for capsule_index, capsule in enumerate(capsules):
        for call in capsule['calls']:
            if _callee(call) in record['producers']:
                for argument in call['arguments']:
                    inputs.append((argument['span'], ('input_port', _callee(call), argument['slot'])))
        if capsule.get('expected'):
            expected.append((capsule['expected']['span'], ('expected', capsule_index)))
        for helper in capsule.get('helper_assertions', []):
            for binding in helper.get('expected_parameter_origins', []):
                expected.append((binding['actual']['span'], ('expected', capsule_index)))
    result = {}
    for path, term in subterms(record['tree'].term):
        if not isinstance(term, Term) or term.children or term.kind in {'#trivia', 'identifier'}:
            continue
        span = record['tree'].spans[path]
        position = {'path': record['test']['span']['path'], 'start_byte': span.start_byte, 'end_byte': span.end_byte}
        found = [role for region, role in expected if _inside(position, region)]
        if not found:
            found = [role for region, role in inputs if _inside(position, region)]
        if found:
            result[path] = tuple(sorted(set(found), key=repr))
    return result


def _roles(A, B, C):
    maps = [dict(record['bindings']) for record in (A, B, C)]
    repeated = {term for term, count in Counter(n for _, n in subterms(A['tree'].term)).items()
                if count > 1 and isinstance(term, Term) and not term.children}
    available = defaultdict(set)
    for path, term in subterms(A['tree'].term):
        if term in repeated and path in A['literal_roles']:
            available[term].add(A['literal_roles'][path])
    for i, record in enumerate((A, B, C)):
        for path, term in subterms(record['tree'].term):
            role = record['literal_roles'].get(path)
            if term in repeated and role is not None and (i != 1 or role in available[term]):
                maps[i][path] = role
    return maps


def _skeleton(term):
    return tuple(n.kind if isinstance(n, Term) else 'hole' for _, n in subterms(term)
                 if not isinstance(n, Term) or n.kind != '#trivia')


def _source(record):
    result = {'test_id': record['test']['id'], 'instance_id': record['instance_id'],
              'span': record['test']['body_span'],
              'sha256': hashlib.sha256(record['text'].encode()).hexdigest(), 'text': record['text']}
    if 'instantiation' in record:
        result.update(instantiation=record['instantiation'], original_body=record['original_text'])
    return result


def _diverse_neighbors(neighbors):
    """Visit each syntax shape before taking its second nearest example."""
    groups = {}
    for record in neighbors:
        groups.setdefault(record['skeleton'], deque()).append(record)
    result = []
    while groups:
        for shape in list(groups):
            result.append(groups[shape].popleft())
            if not groups[shape]:
                del groups[shape]
    return result


def _canonical(term, labels, path=()):
    """Ignore trivia and only the explicitly supported unique-local spelling."""
    label = labels.get(path)
    atom = ('@local:' + str(label[1])) if label and label[0] == 'single_scope_local' else term.atom
    return Term(term.kind, atom, tuple(_canonical(c, labels, path + (i,))
                                     for i, c in enumerate(term.children) if c.kind != '#trivia'))


def _output_bindings(B, C, transfers):
    """Transport binding labels using the same exact subtree paths as the edit."""
    labels = dict(B['bindings'])
    for transfer in transfers:
        destination, origin = tuple(transfer['b_path']), tuple(transfer['c_paths'][0])
        labels = {path: label for path, label in labels.items() if path[:len(destination)] != destination}
        labels.update({destination + path[len(origin):]: label for path, label in C['bindings'].items()
                       if path[:len(origin)] == origin})
    return labels


def _refine(record, max_nodes):
    """New string-token children inherit the original source leaf's role."""
    refined = refine_strings(record['tree'])
    original_roles, roles = record['literal_roles'], {}
    for path, _ in subterms(refined.term, max_nodes=max_nodes):
        origin = path
        while origin and origin not in original_roles:
            origin = origin[:-1]
        if origin in original_roles:
            roles[path] = original_roles[origin]
    return dict(record, tree=refined, literal_roles=roles, skeleton=_skeleton(refined.term))


def generate(corpus: dict, budget: Budget = Budget(), *, compose=analogy) -> dict:
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
            source_nodes[path] = {(n.start_byte, n.end_byte): n for n in walk(sources[path].root)}
        source = sources[path]
        body = test['body_span']
        if body['end_byte'] - body['start_byte'] > budget.max_body_bytes:
            skipped['body_byte_budget'] += 1
            continue
        node = source_nodes[path].get((body['start_byte'], body['end_byte']))
        if node is None:
            skipped['body_node_missing'] += 1
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
        record = {'test': test, 'instance_id': test['id'], 'tree': converted,
                  'text': render(converted.term), 'original_text': render(converted.term),
                  'producers': producers,
                  'skeleton': _skeleton(converted.term),
                  'bindings': _binding_labels(source, node, converted, test['parameters'])}
        record['literal_roles'] = _literal_roles(record, corpus, capsules[test['id']])
        if test.get('parameterization_status') == 'expanded_literal_rows':
            instances, omissions = instantiate(record, source, node, max_nodes=budget.max_nodes)
            skipped.update(omissions)
        else:
            instances = [record]
        for instance in instances:
            try:
                records[instance['instance_id']] = _refine(instance, budget.max_nodes)
            except BudgetExceeded:
                skipped['refined_body_node_budget'] += 1
    groups = defaultdict(list)
    existing = defaultdict(set)
    for record in records.values():
        existing[_scope(record['test'])].add(_canonical(record['tree'].term, record['bindings']))
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
            result = compose(A['tree'].term, B['tree'].term, C['tree'].term,
                             roles=_roles(A, B, C), max_nodes=budget.max_nodes, max_holes=budget.max_holes)
            known, mechanical = False, None
            if result.status == 'hypothesis':
                known = _canonical(result.output, _output_bindings(B, C, result.provenance['transfers'])) in existing[_scope(C['test'])]
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
                    rid = _id('test_edit_analogy', triple)
                    rule = {'id': rid, 'kind': 'test_edit_analogy', 'before_span': A['test']['body_span'],
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
    return {'algorithm': 'test_edit_analogy_v2', 'budget': asdict(budget), 'candidates': selected,
            'rules': [rules[key] for key in sorted(used)], 'skipped': dict(skipped),
            'counts': {'seed_tests': len(seeds), 'eligible_tests': len(records), 'groups': len(groups),
                       'attempted_triples': attempted, 'candidate_pool': len(pool), 'candidates': len(selected)},
            'binding_statuses': dict(binding_statuses),
            'coverage': corpus.get('coverage', {}), 'reference_inputs': False, 'execution_outcomes': False}


def gate_evidence(corpus, generated, issue):
    evidence, candidates = _v1_evidence(corpus, generated, issue)
    evidence['oracle_policy'] = ('Each proposal transports source edit A->B onto target C. '
        'Assertions may change: their syntax comes from B and substitutions come from C. '
        'Reconstruction does not prove binding, semantic applicability or oracle correctness. '
        'Judge the entire edited target test, including the changed assertions.')
    instances = {}
    evidence['analogy_sources'] = {}
    for candidate in candidates:
        # rule_id survives the gate's short request-local candidate ID mapping.
        evidence['analogy_sources'][candidate['rule_id']] = {}
        for name, source in candidate['provenance']['sources'].items():
            uid = source['instance_id']
            evidence['analogy_sources'][candidate['rule_id']][name] = uid
            instance = {'test_id': source['test_id'], 'body_span': source['span']}
            if 'instantiation' in source:
                row = source['instantiation']
                instance.update(body=source['text'], parameter_row={
                    'table': row['table'], 'row': row['row'], 'mode': row['mode'],
                    'row_span': row['row_span'], 'bindings': {
                        key: {'text': value['text'], 'span': value['span']}
                        for key, value in row['bindings'].items()}})
            instances[uid] = instance
    evidence['analogy_instances'] = instances
    return evidence, candidates
