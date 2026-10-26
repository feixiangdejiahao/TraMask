"""Deterministic source-backed witnesses for a small relational grammar.

This module proposes edits, not coverage or semantic verdicts. Every candidate
retains a seed's observation and records that its oracle still needs independent
admission. A shared call slot is a syntactic alignment; unresolved receiver types
are explicitly not evidence of semantic equivalence.

Supported initial cells are source argument alternatives, nonempty proper
record-field subsets, explicit immutable defaults versus omission, and bounded
integer comparison boundaries. No subject API names or issue text are used.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import difflib
import json

from anchor_retrieval.syntax import CALLS, FUNCTIONS, Source, call_parts, child, literal, walk
from generic_composition.corpus import ASSIGNMENTS, expression, source_text, span
from generic_composition.engine import contained, expanded_donors, expected_only, slot_key, stable_id


@dataclass(frozen=True)
class TransformBudget:
    max_candidates: int = 128
    max_pool: int = 4096
    max_donors_per_slot: int = 48
    max_sources_per_target: int = 16
    max_record_fields: int = 16
    max_test_bytes: int = 20000
    max_expression_bytes: int = 2000
    top_k: int = 10
    boundary_offsets: tuple[int, ...] = (0, -1, 1)
    string_neighbors: int = 4
    max_string_rules_per_slot: int = 64
    max_string_attempts: int = 8000
    max_string_tokens: int = 256


_NESTED_SCOPES = FUNCTIONS | {
    'arrow_function', 'function_expression', 'func_literal', 'lambda',
    'list_comprehension', 'set_comprehension', 'dictionary_comprehension',
    'generator_expression', 'named_expression',
}


def _position(item):
    value = item.get('span', item)
    return value['path'], value['start_byte'], value['end_byte']


def _same_span(left, right):
    return left is not None and right is not None and _position(left) == _position(right)


def _node_for(source, value):
    cache = getattr(source, '_relation_node_map', None)
    if cache is None:
        cache = defaultdict(list)
        for node in walk(source.root):
            cache[(node.start_byte, node.end_byte)].append(node)
        source._relation_node_map = cache
    s = value['span']
    choices = cache.get((s['start_byte'], s['end_byte']), [])
    if value.get('kind'):
        return next((node for node in choices if node.type == value['kind']), None)
    return choices[0] if choices else None


def _root_ports(source, donor):
    """Only an entire argument or an assigned value may change an input cell.

    Def-use edges alone do not align nested record fields or arithmetic operands.
    The direct root check prevents those leaves becoming independent slot values.
    """
    node = _node_for(source, donor)
    if node is None:
        return []
    ports = []
    if donor.get('call_context'):
        port = donor['call_context']
        arg_span = port.get('argument_span')
        arg = _node_for(source, {'span': arg_span}) if arg_span else None
        value = child(arg, 'value') if arg is not None and arg.type == 'keyword_argument' else arg
        if value == node:
            ports.append(port)
    parent = node.parent
    assigned_root = parent is not None and parent.type in ASSIGNMENTS and child(parent, 'right', 'value') == node
    if assigned_root or donor.get('parameter_row'):
        ports.extend(donor.get('input_slots', []))
    unique = {}
    for port in ports:
        unique.setdefault(slot_key(port), port)
    return list(unique.values())


def _local_definition(source, test, name, before):
    """Unique straight-line local definition, excluding nested scopes/branches."""
    body = _node_for(source, {'span': test['body_span']})
    if body is None:
        return None
    found = []
    for statement in body.named_children:
        if statement.end_byte > before:
            continue
        for node in walk(statement):
            if node.type not in ASSIGNMENTS:
                continue
            left = child(node, 'left', 'name')
            if left is None or left.type != 'identifier' or source.text(left) != name:
                continue
            parent = node.parent
            while parent is not None and parent != statement and parent.type in {
                    'expression_statement', 'lexical_declaration', 'variable_declaration'}:
                parent = parent.parent
            if node != statement and parent != statement:
                continue
            found.append(node)
    return found[-1] if found else None


def _transfer_bindings(corpus, sources, origin, target):
    """Never equate two test-local names just because their spelling matches."""
    names = set(origin.get('free_identifiers', []))
    node = _node_for(sources[origin['span']['path']], origin)
    if node is None or any(part.type in _NESTED_SCOPES for part in walk(node)):
        return [], ['nested_scope_binding_not_supported']
    if not names:
        return [], []
    original = corpus['tests'][origin['test_id']]
    recipient = corpus['tests'][target['test_id']]
    def declared_names(record):
        local_source = sources[record['span']['path']]
        body = _node_for(local_source, {'span': record['body_span']})
        return {local_source.text(child(part, 'name')) for part in walk(body)
                if part.type in FUNCTIONS | {'class_definition', 'class_declaration'} and child(part, 'name') is not None}
    original_locals = set(original.get('scope_bindings', [])) | declared_names(original)
    recipient_locals = set(recipient.get('scope_bindings', [])) | declared_names(recipient)
    original_imports = {item['name']: item for item in original['support']['imports']}
    recipient_imports = {item['name']: item for item in recipient['support']['imports']}
    same_test = origin['test_id'] == target['test_id']
    same_file = origin['span']['path'] == target['span']['path']
    same_enclosing = original.get('enclosing_scope_span') == recipient.get('enclosing_scope_span')
    additions, unknowns = [], []
    for name in sorted(names):
        if name in original_locals or name in recipient_locals:
            if not same_test:
                unknowns.append('distinct_test_local:' + name)
                continue
            if name in original.get('parameters', []):
                continue
            src = sources[origin['span']['path']]
            a = _local_definition(src, original, name, origin['span']['start_byte'])
            b = _local_definition(src, recipient, name, target['span']['start_byte'])
            if a is None or b is None or a != b:
                unknowns.append('different_or_unknown_local_definition:' + name)
            continue
        if name in original_imports:
            imported = original_imports[name]
            if name in recipient_imports and recipient_imports[name] != imported:
                unknowns.append('import_alias_collision:' + name)
            elif same_file or name in recipient_imports:
                continue
            else:
                additions.append(dict(imported, source_path=origin['span']['path']))
        elif not (same_file and same_enclosing):
            unknowns.append('unresolved_free_identifier:' + name)
    return additions, unknowns


def _record_fields(source, donor):
    node = _node_for(source, donor)
    if node is None or node.type not in {'dictionary', 'object'}:
        return None
    fields = []
    for part in node.named_children:
        if part.type == 'comment':
            continue
        # Spreads, computed keys, methods, and duplicate keys are unsupported.
        if part.type != 'pair':
            return None
        key = child(part, 'key')
        if key is None:
            return None
        if key.type in {'property_identifier', 'identifier'} and source.language == 'typescript':
            label = source.text(key)
        else:
            try:
                label = literal(source.text(key))
            except ValueError:
                return None
            if not isinstance(label, (str, int, float, bool)) and label is not None:
                return None
        if any(label == old['key'] for old in fields):
            return None
        fields.append({'key': label, 'text': source.text(part), 'span': span(source, part),
                       'value': expression(source, child(part, 'value'))})
    return fields


def _sort_family(donor):
    kind = donor.get('kind')
    if kind in {'string', 'raw_string_literal', 'interpreted_string_literal', 'template_string'}:
        return 'string'
    if kind in {'integer', 'float', 'int_literal', 'float_literal', 'number', 'unary_expression', 'unary_operator'}:
        return 'number'
    if kind in {'dictionary', 'object'}:
        return 'record'
    if kind in {'list', 'array', 'tuple'}:
        return 'sequence'
    return kind


def _immutable_literal(value):
    if not value or not value.get('literal_known'):
        return None
    v = value.get('literal_value')
    if v is None:
        return 'nullish_syntax', value.get('text', '').strip()
    if type(v) not in {str, int, float, bool, type(None)}:
        return None
    return type(v).__name__, json.dumps(v, ensure_ascii=True, sort_keys=True)


def enumerate_transforms(corpus: dict, frontend: dict | None = None,
                         budget: TransformBudget = TransformBudget()) -> dict:
    """Return bounded emitter-compatible proposals and explicit limitations.

    ``frontend`` is the JSON result of ``relational_gap.frontend.extract_frontend``.
    It is optional for source-aligned substitutions and record presence cells.
    No candidate is labelled a missing *executed* relation cell before replay.
    """
    sources = {path: Source(path, data['code'], corpus['language'])
               for path, data in corpus['sources'].items() if data.get('complete_file', True)
               and not data.get('parse_error')}
    capsules = defaultdict(list)
    for item in corpus['capsules']:
        capsules[item['test_id']].append(item)
    tests = corpus['tests']
    ranked = sorted(tests, key=lambda key: (tests[key].get('retrieval_rank') or 10**9,
                                           _position(tests[key]), key))
    seeds = set(ranked[:budget.top_k])
    rank_order = {test_id: index for index, test_id in enumerate(ranked)}
    exception_contexts = _exception_contexts(corpus, sources)
    eligible = {key for key in tests if (capsules[key] or exception_contexts.get(key)) and tests[key]['span']['path'] in sources
                and tests[key]['span']['end_byte'] - tests[key]['span']['start_byte'] <= budget.max_test_bytes
                and not any('helper_argument_binding_unknown' in c.get('unknowns', []) for c in capsules[key])}
    skipped = Counter()
    donors = []
    for donor in expanded_donors(corpus):
        if donor['test_id'] not in eligible or donor.get('role') == 'expected' or expected_only(donor):
            continue
        if len(donor.get('text', '').encode()) > budget.max_expression_bytes:
            skipped['expression_size_budget'] += 1
            continue
        ports = _root_ports(sources[donor['span']['path']], donor)
        if ports:
            donors.append(dict(donor, aligned_ports=ports))
    groups = defaultdict(list)
    for donor in donors:
        for port in donor['aligned_ports']:
            groups[slot_key(port)].append(donor)
    pool = {}
    pool_counts = Counter()
    # Freeze eight language-structural domains; reserve before enumerating so the
    # first prolific slot cannot consume later default/comparison/exit domains.
    domain_count = 8
    domain_limit = max(1, budget.max_pool // domain_count)
    focus_limit = max(1, domain_limit // max(1, len(seeds)))

    def propose(target, after, kind, origins, relation, *, edits=None, imports=(), oracle_basis=None):
        base = target['test_id']
        source_ids = sorted({origin['test_id'] for origin in origins if origin.get('test_id') in tests})
        if base not in eligible or not (seeds & {base, *source_ids}):
            return
        if edits is None:
            if after == target['text']:
                return
            edits = [{'span': target['span'], 'before': target['text'], 'after': after}]
        if any(not contained(edit['span'], tests[base]['span']) for edit in edits):
            skipped['edit_outside_test'] += 1
            return
        if any(source_text(corpus, edit['span']) != edit['before'] for edit in edits):
            skipped['source_edit_mismatch'] += 1
            return
        key = stable_id('relation-witness-v1', base, edits, list(imports))
        previous = pool.get(key)
        if previous is not None:
            # Identical executable edits can have stronger source justification
            # than their first raw slot-swap discovery. Preserve the stronger
            # relation, so a declared default is not hidden by duplicate syntax.
            evidence = {'record_syntax': 0, 'paired_presence_examples': 1, 'source_default': 2}
            old_strength = (previous['oracle'].get('basis') is not None, previous['kind'] != 'aligned_input_substitution',
                            evidence.get(previous['relation'].get('evidence_level'), 0))
            new_strength = (oracle_basis is not None, kind != 'aligned_input_substitution',
                            evidence.get(relation.get('evidence_level'), 0))
            if new_strength <= old_strength:
                return
        focus = base if base in seeds else min(seeds & set(source_ids), key=rank_order.__getitem__)
        previous_same_kind = previous is not None and previous['kind'] == kind
        previous_same_focus = previous_same_kind and previous['focus_test_id'] == focus
        if pool_counts[kind] - int(previous_same_kind) >= domain_limit:
            skipped['pool_domain_budget:' + kind] += 1
            return
        if pool_counts[(kind, focus)] - int(previous_same_focus) >= focus_limit:
            skipped['pool_focus_budget:' + kind] += 1
            return
        if previous is None and len(pool) >= budget.max_pool:
            skipped['pool_budget'] += 1
            return
        if previous is not None:
            pool_counts[previous['kind']] -= 1
            pool_counts[(previous['kind'], previous['focus_test_id'])] -= 1
        edit_size = sum(max(len(edit['before'].encode()), len(edit['after'].encode())) for edit in edits)
        pool[key] = {'id': key, 'base_test_id': base, 'source_test_ids': source_ids,
                     'focus_test_id': focus,
                     'language': corpus['language'], 'kind': kind, 'edits': edits, 'imports': list(imports),
                     'relation': dict(relation, status='statically_constructed_runtime_unconfirmed'),
                     'oracle': {'mode': 'retain_all', 'source_test_id': base,
                                'assertion_ids': [item['id'] for item in capsules[base]],
                                'applicability': 'requires_independent_admission',
                                'basis': oracle_basis,
                                'shared_input_expected_dependency': bool(target.get('oracle_dependency'))},
                     'provenance': {'target_span': target['span'],
                                    'source_spans': [origin['span'] for origin in origins if origin.get('span')],
                                    'source_donor_ids': [origin['id'] for origin in origins if origin.get('id')],
                                    'binding_precision': 'lexical_checks; effects_and_aliases_unproved'},
                     'selection': {'edit_size': edit_size, 'base_position': _position(tests[base]),
                                   'focus_order': rank_order[focus], 'base_order': rank_order[base],
                                   'evidence_order': {'source_default': 0, 'paired_presence_examples': 1, 'record_syntax': 2}.get(relation.get('evidence_level'), 0)}}
        pool_counts[kind] += 1
        pool_counts[(kind, focus)] += 1

    if frontend:
        _field_default_omissions(corpus, frontend, donors, sources, eligible, propose, skipped)
    record_plans = []
    for slot, members in sorted(groups.items(), key=lambda item: (
            min(rank_order[d['test_id']] for d in item[1]), repr(item[0]))):
        members = sorted(members, key=lambda d: (rank_order[d['test_id']], _position(d), d['id']))
        if len(members) > budget.max_donors_per_slot:
            skipped['slot_donor_budget'] += len(members) - budget.max_donors_per_slot
            members = members[:budget.max_donors_per_slot]
        # Substitute one source-backed entire slot value at a time.
        for target in members:
            alternatives = [origin for origin in members if origin['text'] != target['text']
                            and _sort_family(origin) == _sort_family(target)]
            seen = set()
            for origin in alternatives[:budget.max_sources_per_target]:
                if origin['text'] in seen:
                    continue
                seen.add(origin['text'])
                imports, unknowns = _transfer_bindings(corpus, sources, origin, target)
                if unknowns:
                    skipped['unresolved_transferred_bindings'] += 1
                    continue
                propose(target, origin['text'], 'aligned_input_substitution', [origin],
                        {'domain': 'input_slot', 'slot': list(slot), 'cell': 'source_alternative',
                         'alignment': 'same_callee_identity_and_argument_position'}, imports=imports)
        records = [(donor, _record_fields(sources[donor['span']['path']], donor)) for donor in members]
        empty = [donor for donor, fields in records if fields == []]
        observed_shapes = {tuple(sorted((repr(field['key']) for field in fields)))
                           for _, fields in records if fields is not None}
        for target, fields in records:
            if fields is not None and 2 <= len(fields) <= budget.max_record_fields:
                record_plans.append((target, fields, empty, observed_shapes, slot))
    for target, fields, empty, observed_shapes, slot in sorted(record_plans, key=lambda row: (
            not bool(row[2]), rank_order[row[0]['test_id']], _position(row[0]))):
        # Linear finite presence partition. A record's own syntax is enough to
        # construct a hypothesis; schema/default legality is admission work.
        subsets = {tuple([index]) for index in range(len(fields))}
        subsets |= {tuple(i for i in range(len(fields)) if i != missing) for missing in range(len(fields))}
        for indices in sorted(subsets, key=lambda value: (len(value), value)):
            keep = [fields[i] for i in indices]
            source_shape_seen = tuple(sorted(repr(field['key']) for field in keep)) in observed_shapes
            after = '{' + ', '.join(field['text'] for field in keep) + '}'
            evidence = 'paired_presence_examples' if empty else 'record_syntax'
            propose(target, after, 'partial_record_presence', [target, *empty[:1]],
                    {'domain': 'record_presence', 'slot': list(slot),
                     'cell': {'present': [field['key'] for field in keep],
                              'omitted': [field['key'] for i, field in enumerate(fields) if i not in indices]},
                     'field_universe_basis': 'source_record_keys; schema_and_default_contract_unknown',
                     'evidence_level': evidence, 'applicability': 'unknown; omitted_fields_may_be_required',
                     'source_shape_seen': source_shape_seen,
                     'source_field_spans': [field['span'] for field in fields]})

    from .identity import shared_identity_witnesses
    for witness in shared_identity_witnesses(corpus, donors, sources, frontend=frontend,
            max_references=budget.max_donors_per_slot, max_alternatives=budget.max_sources_per_target):
        propose(witness['target'], witness['after'], 'shared_identity_input', witness['origins'], witness['relation'])
    _source_string_contexts(corpus, frontend, donors, sources, seeds, rank_order, budget, propose, skipped)
    if frontend:
        _default_omissions(corpus, frontend, eligible, propose, skipped)
        _comparison_boundaries(corpus, frontend, eligible, budget, propose, skipped, sources)
    _exception_observation_transfers(corpus, sources, exception_contexts, eligible, budget, propose, skipped)

    # Domains are the outer allocation unit. Within each domain, prioritize
    # retrieval order and rotate tests before taking another row from one test.
    domain_bins = defaultdict(lambda: defaultdict(deque))
    for candidate in sorted(pool.values(), key=lambda item: (
            item['selection']['focus_order'], item['selection']['base_order'],
            item['selection'].get('evidence_order', 0), item['selection']['edit_size'], item['selection']['base_position'], item['id'])):
        domain_bins[candidate['kind']][candidate['focus_test_id']].append(candidate)
    active = {kind: deque(sorted(groups, key=rank_order.__getitem__)) for kind, groups in domain_bins.items()}
    candidates = []
    while len(candidates) < budget.max_candidates and active:
        for kind in sorted(list(active)):
            focus = active[kind].popleft()
            candidates.append(domain_bins[kind][focus].popleft())
            if domain_bins[kind][focus]:
                active[kind].append(focus)
            if not active[kind]:
                del active[kind]
            if len(candidates) >= budget.max_candidates:
                break
    return {'version': 1, 'budget': asdict(budget), 'candidates': candidates,
            'counts': {'candidate_pool': len(pool), 'candidates': len(candidates),
                       'eligible_tests': len(eligible), 'aligned_donors': len(donors),
                       'skipped': dict(sorted(skipped.items()))},
            'limitations': ['source syntax does not establish executed relation coverage',
                            'retained assertions need independent applicability admission',
                            'record keys do not prove schema fields or default contracts',
                            'call effects, receiver types, aliases, and temporal reachability are unproved']}


def _default_omissions(corpus, frontend, eligible, propose, skipped):
    functions = {value['id']: value for value in frontend.get('functions', [])}
    for call in sorted(frontend.get('calls', []), key=lambda item: (
            corpus['tests'].get(item.get('test_id'), {}).get('retrieval_rank') or 10**9, _position(item))):
        if call.get('test_id') not in eligible:
            continue
        arguments = call.get('arguments', [])
        bindings = call.get('argument_bindings', [])
        for argument in arguments:
            matches = [item for item in bindings if item.get('slot') == argument['slot']]
            if len(matches) != 1:
                continue
            binding = matches[0]
            if binding.get('binding_status', 'direct_actual_formal') != 'direct_actual_formal':
                skipped['unresolved_actual_formal_binding'] += 1
                continue
            function = functions.get(binding.get('function_id'))
            if function is None:
                continue
            parameter = next((value for value in function.get('parameters', [])
                              if value['index'] == binding.get('parameter_index')), None)
            default = parameter.get('default') if parameter else None
            if _immutable_literal(default) is None or _immutable_literal(default) != _immutable_literal(argument):
                continue
            # Removing a nonfinal positional argument shifts later bindings.
            if not argument.get('keyword') and any(
                    other['slot'] > argument['slot'] and not other.get('keyword') for other in arguments):
                skipped['nonfinal_positional_default'] += 1
                continue
            removal = argument.get('removal_span')
            if not removal:
                skipped['missing_argument_removal_span'] += 1
                continue
            target = dict(argument, test_id=call['test_id'])
            propose(target, '', 'explicit_default_omission', [default],
                    {'domain': 'default_argument', 'cell': 'omitted', 'call_span': call['span'],
                     'parameter': parameter['name'], 'declaration_span': parameter['span'],
                     'default_span': default['span'], 'binding': binding},
                    edits=[{'span': removal, 'before': source_text(corpus, removal), 'after': ''}],
                    oracle_basis={'kind': 'declared_immutable_default', 'span': default['span'],
                                  'limitation': 'omission may differ under reflection; admission still required'})



def _field_default_omissions(corpus, frontend, donors, sources, eligible, propose, skipped):
    """Omit explicit fields using actual source defaults and resolved forwarding.

    A wrapper's direct argument can reach a destructuring/default declaration
    along a bounded actual/formal path. That path is source provenance, not a
    requirement that the buggy candidate executes normalization on every path.
    """
    calls = {call['id']: call for call in frontend.get('calls', [])}
    by_test = defaultdict(list)
    for donor in donors:
        by_test[donor['test_id']].append(donor)
    entries = []
    for fact in frontend.get('field_defaults', []):
        if not fact.get('default') or not fact['default'].get('span'):
            continue
        for binding in fact.get('caller_bindings', []):
            if binding.get('test_id') in eligible:
                entries.append((fact, binding))
    entries.sort(key=lambda pair: (
        corpus['tests'][pair[1]['test_id']].get('retrieval_rank') or 10**9,
        _position(corpus['tests'][pair[1]['test_id']]), _position(pair[0]), repr(pair[0]['field_path'])))
    for fact, binding in entries:
        call = calls.get(binding.get('call_id'))
        if call is None or binding.get('resolution') != 'resolved_actual_formal_path':
            skipped['field_default_caller_binding_unknown'] += 1
            continue
        path = fact.get('field_path', [])
        if not path:
            continue
        for donor in sorted(by_test[binding['test_id']], key=_position):
            if not any(_same_span(port['call_span'], call['span']) and port['argument_slot'] == binding['slot']
                       for port in donor['aligned_ports']):
                continue
            source = sources[donor['span']['path']]
            current = donor
            fields = None
            for depth, key in enumerate(path):
                fields = _record_fields(source, current)
                matches = [field for field in fields or [] if field['key'] == key]
                if len(matches) != 1:
                    current = None
                    break
                selected = matches[0]
                if depth < len(path) - 1:
                    current = selected['value']
            if current is None or fields is None:
                continue
            same_immutable_default = (_immutable_literal(fact['default']) is not None
                                      and _immutable_literal(selected['value']) == _immutable_literal(fact['default']))
            remaining = [field for field in fields if field is not selected]
            if not same_immutable_default and not remaining:
                continue
            after = '{' + ', '.join(field['text'] for field in remaining) + '}'
            edited = dict(current, test_id=donor['test_id'], oracle_dependency=donor.get('oracle_dependency', False))
            if not same_immutable_default:
                propose(edited, after, 'partial_record_presence', [donor, fact['default']],
                        {'domain': 'record_presence', 'cell': {'present': [field['key'] for field in remaining],
                                                             'omitted': [selected['key']], 'omitted_path': path},
                         'call_span': call['span'], 'record_span': donor['span'], 'field_span': selected['span'],
                         'default_span': fact['default']['span'], 'default_declaration_span': fact['span'],
                         'mechanism': fact['mechanism'], 'binding_path': binding.get('path', []),
                         'field_universe_basis': 'source_record_keys_and_resolved_default_declaration',
                         'evidence_level': 'source_default',
                         'applicability': 'omission_changes_field_source; expected_value_unknown'})
                continue
            propose(edited, after, 'explicit_field_default_omission', [fact['default']],
                    {'domain': 'default_record_field', 'cell': {'omitted_path': path}, 'evidence_level': 'source_default',
                     'call_span': call['span'], 'record_span': donor['span'],
                     'field_span': selected['span'], 'default_span': fact['default']['span'],
                     'default_declaration_span': fact['span'], 'mechanism': fact['mechanism'],
                     'binding_path': binding.get('path', []),
                     'applicability': 'source_default_not_proved_on_all_paths'},
                    oracle_basis={'kind': 'source_field_default', 'span': fact['default']['span'],
                                  'limitation': 'field omission contract requires independent admission'})

def _comparison_boundaries(corpus, frontend, eligible, budget, propose, skipped, sources):
    """Instantiate source scalar comparisons through direct actual/formal edges.

    One side must be a scalar formal. The opposite side uses a finite syntax of
    integer literals, actual-bound symbols, fields, and +,-,* expressions. This
    is a witness hypothesis until runtime confirms the comparison's operands.
    """
    functions = {item['id']: item for item in frontend.get('functions', [])}
    by_function = defaultdict(list)
    for comparison in frontend.get('comparisons', []):
        if comparison['operator'] in {'<', '<=', '>', '>=', '==', '!=', '===', '!=='}:
            by_function[comparison['function_id']].append(comparison)

    def safe_actual(argument):
        source = sources.get(argument['span']['path'])
        node = _node_for(source, argument) if source is not None else None
        effectful = CALLS | _NESTED_SCOPES | ASSIGNMENTS | {
            'assignment_expression', 'augmented_assignment_expression', 'update_expression',
            'await', 'await_expression', 'yield', 'yield_expression', 'inc_statement', 'dec_statement'}
        return node is not None and not any(part.type in effectful for part in walk(node))

    def instantiate(ir, environment, seen):
        kind = ir.get('kind')
        if kind == 'literal' and type(ir.get('value')) is int:
            seen.append(ir['span'])
            return ir['text']
        if kind == 'symbol' and ir.get('name') in environment:
            actual = environment[ir['name']]
            if not safe_actual(actual):
                return None
            seen.append(actual['span'])
            return '(' + actual['text'] + ')'
        if kind == 'field':
            obj = instantiate(ir.get('object', {}), environment, seen)
            return obj + '.' + ir['field'] if obj is not None else None
        if kind == 'unary' and ir.get('operator') in {'+', '-'}:
            operand = instantiate(ir.get('operand', {}), environment, seen)
            return ir['operator'] + '(' + operand + ')' if operand is not None else None
        if kind == 'binary' and ir.get('operator') in {'+', '-', '*'}:
            left = instantiate(ir.get('left', {}), environment, seen)
            right = instantiate(ir.get('right', {}), environment, seen)
            if left is not None and right is not None:
                return '(' + left + ' ' + ir['operator'] + ' ' + right + ')'
        return None

    for call in sorted(frontend.get('calls', []), key=lambda item: (
            corpus['tests'].get(item.get('test_id'), {}).get('retrieval_rank') or 10**9, _position(item))):
        if call.get('test_id') not in eligible:
            continue
        args = {item['slot']: item for item in call.get('arguments', [])}
        bindings = [item for item in call.get('argument_bindings', [])
                    if item.get('binding_status', 'direct_actual_formal') == 'direct_actual_formal']
        targets = {item['function_id'] for item in bindings}
        if len(targets) != 1:
            continue
        function_id = next(iter(targets))
        function = functions.get(function_id, {})
        environment = {item['parameter']: args[item['slot']] for item in bindings if item['slot'] in args}
        # Receiver substitution is based on the resolved method declaration.
        params = function.get('parameters', [])
        if function.get('owner') and call.get('receiver') and params and corpus['language'] == 'python':
            environment.setdefault(params[0]['name'], call['receiver'])
        receiver = function.get('receiver')
        if isinstance(receiver, dict) and receiver.get('name') and call.get('receiver'):
            environment.setdefault(receiver['name'], call['receiver'])
        for comparison in by_function[function_id]:
            for side, other in [('left', 'right'), ('right', 'left')]:
                direct = comparison.get(side + '_ir', {})
                if direct.get('kind') != 'symbol':
                    continue
                name = direct['name']
                matched = [item for item in bindings if item['parameter'] == name]
                if len(matched) != 1:
                    continue
                argument = args[matched[0]['slot']]
                parameter = next((item for item in params if item.get('name') == name), {})
                scalar_type = parameter.get('type', '').strip()
                if not (argument.get('literal_known') and type(argument.get('literal_value')) is int
                        or scalar_type in {'int', 'int32', 'int64', 'uint', 'uint32', 'uint64', 'number'}):
                    skipped['comparison_scalar_type_unknown'] += 1
                    continue
                spans = []
                # The target cannot appear in its own constructed boundary.
                rhs = instantiate(comparison.get(other + '_ir', {}),
                                  {key: value for key, value in environment.items() if key != name}, spans)
                if rhs is None:
                    skipped['comparison_expression_unresolved'] += 1
                    continue
                for offset in budget.boundary_offsets:
                    replacement = rhs if offset == 0 else '(' + rhs + ') ' + ('+' if offset > 0 else '-') + ' ' + str(abs(offset))
                    target = dict(argument, test_id=call['test_id'])
                    cell = '=' if offset == 0 else '<' if offset < 0 else '>'
                    propose(target, replacement, 'scalar_comparison_boundary', [comparison[other]],
                            {'domain': 'scalar_comparison', 'cell': cell,
                             'comparison_span': comparison['span'], 'comparison_operator': comparison['operator'],
                             'target_operand': side, 'parameter': name, 'offset': offset,
                             'source_expression_span': comparison[other]['span'],
                             'actual_substitution_spans': spans, 'call_span': call['span'],
                             'binding': matched[0], 'integer_type_basis': 'source_literal_or_parameter_annotation',
                             'runtime_obligation': 'confirm_operands_and_observation_in_same_execution'})


def _exception_contexts(corpus, sources):
    """Recognize only existing language/test-framework exception syntax."""
    result = defaultdict(list)
    if corpus['language'] != 'python':
        return result
    for test_id, test in corpus['tests'].items():
        source = sources.get(test['span']['path'])
        if source is None:
            continue
        body = _node_for(source, {'span': test['body_span']})
        if body is None:
            continue
        for node in walk(body, stop_functions=True):
            if node.type == 'with_statement':
                nested = child(node, 'body')
                for header in node.named_children:
                    if header == nested:
                        continue
                    calls = [part for part in walk(header) if part.type in CALLS]
                    if any(source.text(call_parts(call)[0]).split('.')[-1] in {'raises', 'assertRaises', 'assertRaisesRegex'}
                           for call in calls):
                        result[test_id].append(node)
                        break
            elif node.type == 'try_statement' and any(part.type == 'except_clause' for part in node.named_children):
                result[test_id].append(node)
    return result


def _exception_observation_transfers(corpus, sources, contexts, eligible, budget, propose, skipped):
    """Append an existing observation after an existing handled-exception exit.

    Reuses the established typed observation projection binding analysis. One
    receiver root is aligned by constructor provenance/type and replaced with
    the *same lexical value* consumed inside the exception context. No exception
    input, handling code, resource setup, or expected value is invented.
    """
    if not contexts or not corpus['capsules']:
        return
    from anchor_retrieval.index import Index
    from prototypes import observation_projection as projection

    index = Index(list(sources.values()), '')
    templates = projection._bank(corpus, index, projection.Budget(max_templates=128, max_ports=1), skipped)
    for test_id in sorted(contexts, key=lambda key: (corpus['tests'][key].get('retrieval_rank') or 10**9, _position(corpus['tests'][key]))):
        if test_id not in eligible or test_id not in index.units:
            continue
        test, unit = corpus['tests'][test_id], index.units[test_id]
        source = unit.source
        count = 0
        for context in contexts[test_id]:
            body = child(context, 'body')
            if body is None:
                continue
            roots = []
            for node in walk(body, stop_functions=True):
                if node.type in CALLS:
                    roots.extend(projection._roots(index, unit, node))
            roots = projection._merge_aliases(roots)
            # Expressions would create a second evaluation; only existing local
            # receiver bindings are valid insertion ports.
            roots = [root for root in roots if root['nodes'] and root['nodes'][0].type == 'identifier']
            for template in templates:
                if template['record']['id'] == test_id or len(template['roots']) != 1:
                    continue
                if projection._scope(template['record']) != projection._scope(test):
                    continue
                for root in roots:
                    if not projection._match(template['roots'][0], root):
                        continue
                    replacement = source.text(root['nodes'][0])
                    if any(part.type in ASSIGNMENTS | {'assignment_expression', 'augmented_assignment', 'named_expression', 'as_pattern'}
                           and any(source.text(name) == replacement for name in walk(child(part, 'left', 'name', 'alias') or part))
                           for part in walk(context)):
                        skipped['exception_receiver_rebound_in_context'] += 1
                        continue
                    try:
                        # Close the whole source assertion, including expected
                        # local literals, using the same receiver renaming.
                        whole = dict(template, observed=template['statement'])
                        assertion = projection._close_observer(whole, test, unit, [replacement])
                    except (ValueError, KeyError, TypeError) as exc:
                        skipped['exception_observer_' + str(exc)] += 1
                        continue
                    if '\n' in assertion or template['statement'].type != 'assert_statement':
                        skipped['exception_observer_multiline_or_framework_statement'] += 1
                        continue
                    start = source.data.rfind(b'\n', 0, context.start_byte) + 1
                    indent = source.data[start:context.start_byte].decode()
                    if indent.strip():
                        skipped['exception_context_inline_insertion'] += 1
                        continue
                    after = '\n' + indent + assertion
                    insertion = dict(span(source, context), start_byte=context.end_byte, end_byte=context.end_byte)
                    donor = {'id': template['capsule']['id'], 'test_id': template['record']['id'],
                             'span': template['capsule']['assertion_span']}
                    target = {'test_id': test_id, 'span': span(source, context), 'text': source.text(context)}
                    propose(target, after, 'exception_exit_observation', [donor],
                            {'domain': 'resource_exit', 'cell': 'observation_after_handled_exception_context',
                             'context_span': span(source, context),
                             'source_observation_span': template['capsule']['assertion_span'],
                             'receiver_binding': {'source': template['source'].text(template['roots'][0]['nodes'][0]),
                                                  'target': replacement, 'target_span': span(source, root['nodes'][0]),
                                                  'types': sorted(set(template['roots'][0]['types']) & set(root['types'])),
                                                  'constructor_origins': sorted(set(template['roots'][0]['origins']) & set(root['origins']))},
                             'phase': 'immediately_after_existing_exception_context',
                             'runtime_obligation': 'confirm_exception_taken_and_same_receiver_observed'},
                            edits=[{'span': insertion, 'before': '', 'after': after}],
                            oracle_basis={'kind': 'existing_source_assertion', 'span': donor['span'],
                                          'limitation': 'applicability_at_exception_exit_requires_admission'})
                    count += 1
                    if count >= budget.max_sources_per_target:
                        break
                if count >= budget.max_sources_per_target:
                    break
            if count >= budget.max_sources_per_target:
                break


def _source_string_contexts(corpus, frontend, donors, sources, seeds, rank_order, budget, propose, skipped):
    """Learn source-fragment edits and transfer only uniquely anchored matches.

    Strings stay opaque token sequences. Sources are existing test slot values
    and literal comparisons linked to that slot by direct actual/formal binding.
    No protocol keys, parser method names, or regular-expression grammar is
    inferred from a string's contents.
    """
    from prototypes.local_literal_contexts import learn
    from generic_composition.edits import encode_literal, learn_literal_edits, tokens

    groups = defaultdict(list)
    tokenized = {}
    def eligible(donor):
        if not donor.get('literal_known') or not isinstance(donor.get('literal_value'), str):
            return False
        value = donor['literal_value']
        if len(value.encode()) > budget.max_expression_bytes:
            skipped['string_expression_size_budget'] += 1
            return False
        seq = tokens(value)
        if len(seq) > budget.max_string_tokens:
            skipped['string_token_budget'] += 1
            return False
        tokenized[value] = seq
        return True

    for donor in donors:
        if eligible(donor):
            for port in donor['aligned_ports']:
                groups[slot_key(port)].append(donor)
    if frontend and frontend.get('comparisons'):
        comparisons = defaultdict(list)
        for comparison in frontend.get('comparisons', []):
            if comparison['operator'] in {'==', '!=', '===', '!=='}:
                comparisons[comparison['function_id']].append(comparison)
        for call in frontend.get('calls', []):
            for binding in call.get('argument_bindings', []):
                if binding.get('binding_status', 'direct_actual_formal') != 'direct_actual_formal':
                    continue
                argument = next((arg for arg in call['arguments'] if arg['slot'] == binding['slot']), None)
                if argument is None:
                    continue
                port = {'callee': call['callee'], 'callee_identity': call['callee_identity'],
                        'argument_slot': binding['slot'], 'keyword': argument.get('keyword'), 'call_span': call['span']}
                slot = slot_key(port)
                if slot not in groups:
                    continue
                for comparison in comparisons[binding['function_id']]:
                    for parameter_side, value_side in [('left', 'right'), ('right', 'left')]:
                        ir = comparison.get(parameter_side + '_ir', {})
                        if ir.get('kind') != 'symbol' or ir.get('name') != binding['parameter']:
                            continue
                        value = comparison[value_side]
                        if eligible(value):
                            groups[slot].append(dict(value, id=stable_id('comparison-string-source', value['span']),
                                test_id=None, source_kind='production_comparison_literal',
                                comparison_span=comparison['span'], actual_formal_binding=binding))

    attempts = 0
    ordered = sorted(groups.items(), key=lambda pair: (
        min(rank_order[donor['test_id']] for donor in pair[1] if donor.get('test_id') in rank_order), repr(pair[0])))
    for slot, members in ordered:
        targets = sorted((donor for donor in members if donor.get('test_id') in rank_order),
                         key=lambda donor: (rank_order[donor['test_id']], _position(donor)))
        if not any(target['test_id'] in seeds for target in targets):
            continue
        # Literal identity deduplication is only for learning rules; target
        # contexts remain distinct and are never counted as covered by text.
        unique = {}
        for donor in sorted(members, key=lambda item: (rank_order.get(item.get('test_id'), 10**9), _position(item))):
            unique.setdefault(donor['literal_value'], donor)
        values = list(unique.values())[:budget.max_donors_per_slot]
        learned = {}
        for before in values:
            nearest = sorted((after for after in values if after['id'] != before['id']), key=lambda after: (
                -difflib.SequenceMatcher(a=tokenized[before['literal_value']], b=tokenized[after['literal_value']], autojunk=False).ratio(),
                _position(after)))[:budget.string_neighbors]
            for after in nearest:
                local_rules = [('unique_local_token_anchor', edit) for edit in learn(
                    before['literal_value'], after['literal_value'], max_tokens=budget.max_string_tokens)]
                full_rules = [('whole_token_pattern', edit) for edit in learn_literal_edits(
                    before['literal_value'], after['literal_value'], max_tokens=budget.max_string_tokens)]
                for scope, edit in local_rules + full_rules:
                    learned.setdefault((scope, edit.fingerprint), (scope, edit, before, after))
        rules = sorted(learned.values(), key=lambda item: (
            len(item[1].pattern) if item[0] == 'unique_local_token_anchor' else len(item[1].before),
            item[0], item[1].fingerprint))[:budget.max_string_rules_per_slot]
        for target in targets:
            for scope, edit, before, after in rules:
                if target['id'] in {before['id'], after['id']}:
                    continue
                if attempts >= budget.max_string_attempts:
                    skipped['string_attempt_budget'] += 1
                    return
                attempts += 1
                output = edit.apply(target['literal_value'])
                if output is None:
                    continue
                positions = edit.positions(target['literal_value']) if scope == 'unique_local_token_anchor' else [0]
                if len(positions) != 1:
                    skipped['string_context_ambiguous'] += 1
                    continue
                source_facts = [{'span': origin['span'], 'kind': origin.get('source_kind', 'test_slot_literal'),
                                 'comparison_span': origin.get('comparison_span'),
                                 'binding': origin.get('actual_formal_binding')} for origin in (before, after)]
                propose(target, encode_literal(output, corpus['language'], target['text']), 'source_string_context', [before, after],
                        {'domain': 'source_string_context', 'cell': 'source_fragment_in_target_context',
                         'slot': list(slot), 'source_before': before['span'], 'source_after': after['span'],
                         'source_facts': source_facts, 'edit': edit.as_dict(), 'anchoring': scope,
                         'target_token_anchor': positions[0], 'target_match_count': 1,
                         'source_literal_seen': output in unique,
                         'semantic_status': 'unique_syntactic_anchor; grammar_and_oracle_unknown'})
