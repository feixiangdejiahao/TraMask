"""Mine compositional edits from tests, with no subject-specific operators.

The executable proposal is (an existing test, a source-backed edit). Its oracle
is the original test's assertions, unchanged. A proposal is not a semantic
claim: admission is separate. Both directions matter: a retrieved test can
provide the edited observation OR the context applied to another observation.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import difflib
import hashlib
import json

from .corpus import source_text
from .edits import encode_literal, learn_literal_edits, tokens
from .terms import BudgetExceeded


@dataclass(frozen=True)
class Budget:
    max_candidates: int = 128
    top_k: int = 10
    max_group_values: int = 96
    pair_neighbors: int = 8
    max_rules_per_slot: int = 32
    max_targets_per_rule: int = 64
    max_test_bytes: int = 14000
    max_pool: int = 16000


def stable_id(*values) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def contained(inner: dict, outer: dict) -> bool:
    return (inner['path'] == outer['path'] and outer['start_byte'] <= inner['start_byte']
            and inner['end_byte'] <= outer['end_byte'])


def slot_key(context: dict) -> tuple:
    identity = context.get('callee_identity') or {}
    callee = identity.get('canonical') or identity.get('scope_key')
    if not callee:
        callee = context['call_span']['path'] + '::' + context['callee']
    return (callee, context.get('keyword') or context['argument_slot'])


def input_ports(donor: dict) -> list[dict]:
    ports = list(donor.get('input_slots', []))
    if donor.get('call_context'):
        ports.append(donor['call_context'])
    unique = {}
    for port in ports:
        unique.setdefault(slot_key(port), port)
    return list(unique.values())


def expected_only(donor: dict) -> bool:
    return bool(donor.get('oracle_dependency') and not donor.get('observation_dependency'))


def expanded_donors(corpus: dict) -> list[dict]:
    """Expose literal parameter cells at their actual call ports, keeping rows.

    Editing a cell does not take its expected value from a different row: the
    complete decorated test and every other cell are retained exactly.
    """
    result = [d for d in corpus['donors'] if d['kind'] != 'parameter_row']
    identifier_ports = defaultdict(list)
    observed_names = defaultdict(set)
    expected_names = defaultdict(set)
    for capsule in corpus['capsules']:
        if capsule.get('expected'):
            expected_names[capsule['test_id']].update(capsule['expected']['free_identifiers'])
        for helper in capsule.get('helper_assertions', []):
            for binding in helper.get('expected_parameter_origins', []):
                expected_names[capsule['test_id']].update(binding['actual']['free_identifiers'])
    for donor in result:
        if donor['kind'] == 'identifier' and donor.get('observation_dependency'):
            observed_names[donor['test_id']].add(donor['text'])
        if donor['kind'] == 'identifier' and donor.get('role') != 'expected' and not expected_only(donor):
            identifier_ports[(donor['test_id'], donor['text'])].extend(input_ports(donor))
    for row in corpus['donors']:
        if row['kind'] != 'parameter_row':
            continue
        for name, cell in row['binding_sources'].items():
            if cell is None or (name in expected_names[row['test_id']] and name not in observed_names[row['test_id']]):
                continue
            ports = identifier_ports.get((row['test_id'], name), [])
            if not ports:
                continue
            result.append(dict(cell, id=stable_id(row['id'], name), test_id=row['test_id'],
                               retrieval_rank=row['retrieval_rank'], role='test_expression',
                               input_slots=ports, call_context=None, context_parent=None,
                               oracle_dependency=name in expected_names[row['test_id']],
                               observation_dependency=name in observed_names[row['test_id']],
                               parameter_row={'table': row['table'], 'row': row['row'], 'name': name,
                                              'bindings': row['parameter_bindings']}))
    return result


def _assertion_intersects(corpus: dict, donor: dict) -> bool:
    """Do not treat assertion framework calls as transferable contexts."""
    for a in corpus['capsules']:
        if a['test_id'] != donor['test_id'] or not contained(donor['span'], a['assertion_span']):
            continue
        observed = a.get('observed')
        if observed is None or not contained(donor['span'], observed['span']):
            return True
    return False


def _capsules_by_test(corpus: dict) -> dict:
    result = defaultdict(list)
    for capsule in corpus['capsules']:
        result[capsule['test_id']].append(capsule)
    return result


def _imports_for(corpus: dict, origin: dict, recipient: dict, names: set[str]) -> tuple[list, list]:
    """Transfer only explicit imported bindings, not guessed local variables."""
    source_test = corpus['tests'][origin['test_id']]
    target_test = corpus['tests'][recipient['test_id']]
    if source_test['span']['path'] == target_test['span']['path']:
        # Scope locals still cannot be borrowed from a different test.
        locals_only = set(source_test['scope_bindings']) - set(origin.get('bound_identifiers', []))
        unresolved = names & locals_only - set(target_test['scope_bindings'])
        imported = {i['name'] for i in source_test['support']['imports']}
        unresolved |= names & imported & set(target_test['scope_bindings'])
        if source_test.get('enclosing_scope_span') != target_test.get('enclosing_scope_span'):
            unresolved |= names - imported
        return [], sorted(unresolved)
    provided = {i['name']: i for i in target_test['support']['imports']}
    available = set(target_test['scope_bindings']) | set(provided)
    source_imports = {i['name']: i for i in source_test['support']['imports']}
    additions, unknown = [], []
    for name in sorted(names):
        if name in available:
            if name in source_imports and name in target_test['scope_bindings']:
                unknown.append(name)
                continue
            if name in source_imports and name in provided and source_imports[name] != provided[name]:
                unknown.append(name)  # No silent alias collision.
            continue
        if name in source_imports:
            additions.append(dict(source_imports[name], source_path=source_test['span']['path']))
        else:
            unknown.append(name)
    return additions, unknown


def producer_key(corpus: dict, donor: dict) -> tuple | None:
    """A carrier must come from the same producer, not merely be a call AST."""
    if donor['kind'] not in {'call', 'call_expression', 'new_expression'}:
        ports = sorted({slot_key(p) for p in input_ports(donor)}, key=repr)
        return ('input_ports', donor['kind'], tuple(ports)) if ports else None
    ast = donor.get('ast') or {}
    fn = next((n for n in ast.get('children', []) if n.get('field') in {'function', 'constructor'}), None)
    if not fn:
        return None
    span = dict(donor['span'], start_byte=fn['start_byte'], end_byte=fn['end_byte'])
    name = source_text(corpus, span)
    first, *tail = name.split('.')
    imports = {i['name']: i for i in corpus['tests'][donor['test_id']]['support']['imports']}
    imported = imports.get(first)
    if imported:
        import posixpath
        module = imported['module']
        if module.startswith('.') and corpus['language'] == 'typescript':
            module = posixpath.normpath(posixpath.join(posixpath.dirname(span['path']), module))
        return ('import', module, imported['imported_name'] or '', *tail)
    # Unknown receiver types are only compared within their source file.
    return ('local', span['path'], name)


def generate(corpus: dict, budget: Budget = Budget()) -> dict:
    tests = corpus['tests']
    capsules = _capsules_by_test(corpus)
    ranked = sorted(tests.values(), key=lambda t: (t['retrieval_rank'] or 99999, t['id']))
    seeds = {t['id'] for t in ranked if t['retrieval_rank'] and t['retrieval_rank'] <= budget.top_k}
    if not seeds:
        seeds = {t['id'] for t in ranked[:budget.top_k]}
    seed_order = {t['id']: i for i, t in enumerate(ranked) if t['id'] in seeds}
    skipped = defaultdict(int)
    eligible = set()
    for test in ranked:
        source = corpus['sources'][test['span']['path']]
        if not source.get('complete_file', True):
            skipped['incomplete_source'] += 1
        elif source['parse_error']:
            skipped['source_parse_error'] += 1
        elif test['span']['end_byte'] - test['span']['start_byte'] > budget.max_test_bytes:
            skipped['test_size_budget'] += 1
        elif not capsules.get(test['id']):
            skipped['no_observation'] += 1
        elif any('helper_argument_binding_unknown' in a['unknowns'] for a in capsules[test['id']]):
            skipped['helper_argument_binding_unknown'] += 1
        else:
            eligible.add(test['id'])
    donors = [d for d in expanded_donors(corpus)
              if d['test_id'] in eligible and d.get('role') != 'expected' and not expected_only(d)]
    pool, rules = {}, {}
    pool_allocations = defaultdict(int)

    def propose(target, replacement, rule, origins, imports=(), binding_unknowns=()):
        base_id = target['test_id']
        focus = sorted(({base_id} | {d['test_id'] for d in origins}) & seeds,
                       key=lambda x: seed_order[x])
        if (not focus or base_id not in eligible or replacement == target['text']
                or not contained(target['span'], tests[base_id]['span'])):
            return
        if binding_unknowns:
            skipped['unbound_transplanted_names'] += 1
            return
        edit = {'span': target['span'], 'before': target['text'], 'after': replacement}
        key = stable_id(base_id, edit, list(imports))
        if key in pool:
            return
        if len(pool) >= budget.max_pool:
            skipped['pool_global_budget'] += 1
            return
        allocation = (focus[0], rule['kind'])
        if pool_allocations[allocation] >= max(1, budget.max_pool // (2 * max(1, len(seeds)))):
            skipped['pool_diversity_budget'] += 1
            return
        source_ids = sorted({d['test_id'] for d in origins})
        proposal = {'id': key, 'base_test_id': base_id, 'focus_test_id': focus[0],
                    'language': corpus['language'], 'kind': rule['kind'],
                    'rule_id': rule['id'], 'source_test_ids': source_ids,
                    'edits': [edit], 'imports': list(imports),
                    'oracle': {'mode': 'retain_all', 'source_test_id': base_id,
                               'assertion_ids': [a['id'] for a in capsules[base_id]],
                               'shared_input_expected_dependency': bool(target.get('oracle_dependency'))},
                    'provenance': {'target_donor_id': target['id'],
                                   'source_donor_ids': [d['id'] for d in origins],
                                   'input_ports': input_ports(target),
                                   'binding_precision': 'syntactic; effects_and_aliases_unproved'},
                    'selection': {'focus_order': seed_order[focus[0]],
                                  'edit_size': abs(len(target['text']) - len(replacement)) + 1,
                                  'base_retrieval_rank': tests[base_id]['retrieval_rank']}}
        pool[key] = proposal
        pool_allocations[allocation] += 1
        rules[rule['id']] = rule

    # String edits: learn from neighboring observations at the same call port.
    groups = defaultdict(list)
    for donor in donors:
        if donor.get('literal_known') and isinstance(donor.get('literal_value'), str):
            for port in input_ports(donor):
                groups[slot_key(port)].append(donor)
    for slot, members in sorted(groups.items(), key=lambda p: repr(p[0])):
        if not any(d['test_id'] in seeds for d in members):
            continue
        unique = {}
        for donor in sorted(members, key=lambda d: (d['test_id'] not in seeds, d['id'])):
            unique.setdefault(donor['literal_value'], donor)
        values = list(unique.values())[:budget.max_group_values]
        learned = {}
        for before in values:
            seq = tokens(before['literal_value'])
            nearest = sorted((d for d in values if d['id'] != before['id']), key=lambda d: (
                -difflib.SequenceMatcher(a=seq, b=tokens(d['literal_value']), autojunk=False).ratio(), d['id']))
            for after in nearest[:budget.pair_neighbors]:
                for edit in learn_literal_edits(before['literal_value'], after['literal_value']):
                    learned.setdefault(edit.fingerprint, (edit, before, after))
        # Budget only rules capable of crossing a retrieved observation. Without
        # this step unrelated grammar fragments consume the whole rule budget.
        relevant = [item for item in learned.values() if any(
            (d['test_id'] in seeds or item[1]['test_id'] in seeds or item[2]['test_id'] in seeds)
            and d['id'] not in {item[1]['id'], item[2]['id']}
            and item[0].apply(d['literal_value']) is not None for d in members)]
        ordered = sorted(relevant, key=lambda x: (x[0].edit_size, x[0].fingerprint))
        for edit, before, after in ordered[:budget.max_rules_per_slot]:
            rule = {'id': stable_id('literal', slot, edit.fingerprint), 'kind': 'literal_difference',
                    'slot': slot, 'edit': edit.as_dict(),
                    'before_span': before['span'], 'after_span': after['span'],
                    'semantic_status': 'hypothesis_from_examples'}
            targets = sorted(members, key=lambda d: (d['test_id'] not in seeds, d['retrieval_rank'] or 99999, d['id']))
            for target in targets[:budget.max_targets_per_rule]:
                if target['id'] in {before['id'], after['id']}:
                    continue
                output = edit.apply(target['literal_value'])
                if output is not None:
                    propose(target, encode_literal(output, corpus['language'], target['text']), rule, [before, after])

    # AST contexts: C[E] is an observed expression. Replacing E by another
    # expression is purely syntactic until the unchanged oracle is admitted.
    from .context_edits import learn_context_edits
    by_producer = defaultdict(list)
    for donor in donors:
        if not _assertion_intersects(corpus, donor):
            key = producer_key(corpus, donor)
            if key is not None:
                by_producer[key].append(donor)
    learned_contexts = {}
    for donor in donors:
        parent = donor.get('context_parent')
        if not parent or donor['kind'] not in {'call', 'call_expression', 'new_expression', 'binary_operator',
                                               'binary_expression', 'list', 'array', 'object', 'dictionary'}:
            continue
        if _assertion_intersects(corpus, dict(parent, test_id=donor['test_id'])):
            continue
        if len(parent['text']) > 1500 or len(donor['text']) > 1000:
            continue
        try:
            edits = learn_context_edits(donor, parent, max_candidates=2)
        except BudgetExceeded:
            skipped['context_term_budget'] += 1
            continue
        for edit in edits:
            key = (edit.fingerprint, producer_key(corpus, donor), donor['test_id'] in seeds)
            learned_contexts.setdefault(key, (edit, donor, parent))
    for edit, origin, parent in sorted(learned_contexts.values(), key=lambda p: (
            p[1]['test_id'] not in seeds, p[1]['retrieval_rank'] or 99999, p[0].fingerprint)):
        candidates = by_producer[producer_key(corpus, origin)]
        if origin['test_id'] not in seeds:
            candidates = [d for d in candidates if d['test_id'] in seeds]
        # Prefer the same carrier producer, then retrieval proximity. This is
        # an observable AST relation, not a keyword or issue-specific rule.
        prefix = origin['text'].split('(', 1)[0].strip()
        candidates = sorted(candidates, key=lambda d: (
            d['text'].split('(', 1)[0].strip() != prefix,
            d['retrieval_rank'] or 99999, d['id']))[:budget.max_targets_per_rule]
        rule = {'id': stable_id('context', edit.fingerprint, origin['id']), 'kind': 'ast_context',
                'edit': edit.as_dict(), 'before_span': origin['span'], 'after_span': parent['span'],
                'semantic_status': 'syntactic_containment_only'}
        for target in candidates:
            if target['test_id'] == origin['test_id'] or target['text'] == origin['text']:
                continue
            try:
                applied = edit.apply(target)
            except (ValueError, BudgetExceeded):
                continue
            if applied is None:
                continue
            names = set(applied.introduced_names)
            imports, unknown = _imports_for(corpus, origin, target, names)
            propose(target, applied.text, rule, [origin], imports, unknown)

    # Fair deterministic allocation across retrieved observations and edit
    # sources. A large test/API cannot consume all 128 proposal positions.
    bins = defaultdict(lambda: defaultdict(deque))
    for proposal in sorted(pool.values(), key=lambda p: (
            p['selection']['focus_order'], p['selection']['edit_size'], p['id'])):
        bins[proposal['focus_test_id']][proposal['rule_id']].append(proposal)
    selected = []
    rule_turns = {focus: deque(sorted(rows)) for focus, rows in bins.items()}
    while bins and len(selected) < budget.max_candidates:
        for focus in sorted(list(bins), key=lambda x: seed_order[x]):
            rules_here = bins[focus]
            rid = rule_turns[focus].popleft()
            selected.append(rules_here[rid].popleft())
            if not rules_here[rid]:
                del rules_here[rid]
            else:
                rule_turns[focus].append(rid)
            if not rules_here:
                del bins[focus]
            if len(selected) >= budget.max_candidates:
                break
    used_rules = {p['rule_id'] for p in selected}
    return {'algorithm': 'test_derived_context_exchange_v1', 'budget': asdict(budget),
            'candidates': selected, 'rules': [rules[k] for k in sorted(used_rules)],
            'counts': {'seed_tests': len(seeds), 'eligible_tests': len(eligible),
                       'donors': len(donors), 'candidate_pool': len(pool),
                       'pool_by_kind': {kind: sum(p['kind'] == kind for p in pool.values())
                                        for kind in sorted({p['kind'] for p in pool.values()})},
                       'candidates': len(selected), 'rules': len(used_rules)},
            'skipped': dict(skipped), 'coverage': corpus['coverage'],
            'reference_inputs': False, 'execution_outcomes': False}


def gate_evidence(corpus: dict, generated: dict, issue: str) -> tuple[dict, list[dict]]:
    candidates = generated['candidates']
    ids = {p['base_test_id'] for p in candidates}
    ids.update(t for p in candidates for t in p['source_test_ids'])
    tests = {tid: {'code': source_text(corpus, corpus['tests'][tid]['span']),
                   'imports': corpus['tests'][tid]['support']['imports']}
             for tid in sorted(ids)}
    observations = {a['id']: {'test_id': a['test_id'], 'assertion': a['assertion'],
                             'observed': (a['observed'] or {}).get('text'),
                             'expected': (a['expected'] or {}).get('text')}
                    for a in corpus['capsules'] if a['test_id'] in ids}
    compact_rules = [{key: rule[key] for key in ('id', 'kind', 'semantic_status')}
                     | {'before': source_text(corpus, rule['before_span']),
                        'after': source_text(corpus, rule['after_span'])}
                     for rule in generated['rules']]
    helpers = {}
    for tid in sorted(ids):
        for helper in corpus['tests'][tid]['support']['helpers']:
            if helper['span']['end_byte'] - helper['span']['start_byte'] <= 14000:
                helpers[helper['id']] = source_text(corpus, helper['span'])
    return {'issue': issue, 'source_tests': tests, 'observations': observations,
            'rules': compact_rules, 'test_helpers': helpers,
            'oracle_policy': ('All assertions are retained verbatim. Expected-only definitions are frozen. '
                              'An edit may affect a shared actual/expected input, explicitly marked in the '
                              'proposal; its relational oracle requires separate semantic justification.')}, candidates
