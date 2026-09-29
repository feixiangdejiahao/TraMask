"""Source-owned Python neighbours for the relation-shape search.

This module constructs tests; it does not decide whether retained assertions are
correct in a new context.  The finite operators are constructor-coordinate
products, same-origin argument binding merges, and SQL predicate/write overlap.
All names, resources, values and source observations come from the input corpus.
No repository name, issue label, reference program or provider is consulted.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
import copy
from dataclasses import asdict, dataclass
import itertools
import json

from generic_composition.engine import stable_id
from relational_gap import exception_contexts as exceptions
from relational_gap.embedded_relations import _neutral_predicate, _tokens, parse_sql_program
from relational_gap.frontend import is_operation_argument


@dataclass(frozen=True)
class Budget:
    max_candidates: int = 128
    max_attempts: int = 4096
    max_per_domain: int = 128
    max_tests: int = 64
    max_sibling_coordinates: int = 2
    max_roles_per_call: int = 8
    max_sql_rows: int = 32
    include_exception_seeds: bool = True


def _position(span):
    return span['path'], span['start_byte'], span['end_byte']


def _overlap(left, right):
    return left['path'] == right['path'] and left['start_byte'] < right['end_byte'] and right['start_byte'] < left['end_byte']


def _syntax(node):
    return ast.dump(node, include_attributes=False)


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (TypeError, ValueError, SyntaxError, RecursionError):
        return ...


def _indent(kernel, span):
    data = kernel.sources[span['path']].data
    start = data.rfind(b'\n', 0, span['start_byte']) + 1
    prefix = data[start:span['start_byte']].decode()
    return prefix if not prefix.strip() else None


def _candidate(kernel, test_id, kind, edits, source_ids=(), relation=None, provenance=None):
    identifier = stable_id('relation-search-python-v1', test_id, kind, edits)
    observations = kernel.observations[test_id]
    return {'id': identifier, 'base_test_id': test_id, 'source_test_ids': sorted(set(source_ids)),
            'language': 'python', 'kind': kind, 'edits': edits, 'imports': [],
            'relation': {'domain': kind, 'status': 'statically_constructed_runtime_unconfirmed',
                         'applicability': 'unknown_requires_independent_admission', **(relation or {})},
            'oracle': {'mode': 'retain_all', 'assertion_ids': [q['id'] for q in observations],
                       'applicability': 'unknown_requires_independent_admission'},
            'provenance': provenance or {},
            'selection': {'base_retrieval_rank': kernel.corpus['tests'][test_id].get('retrieval_rank')}}


def _preserve_inline_assert(kernel, candidate):
    """An exception can interrupt an assert expression without erasing it."""
    candidate = copy.deepcopy(candidate)
    original_id = candidate['id']
    for edit in candidate['edits']:
        if edit.get('role') != 'source_exception_context':
            continue
        source = kernel.node(edit['span'], ast.Assert)
        if source is None:
            continue
        indent = _indent(kernel, edit['span'])
        if indent is None:
            continue
        lines = edit['after'].splitlines()
        normalized = '\n'.join([lines[0], *[line[len(indent):] if line.startswith(indent) else line for line in lines[1:]]])
        tree = ast.parse(normalized)
        invocation = candidate['provenance']['recipient_invocation_span']
        original_call = kernel.node(invocation)
        if original_call is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.With, ast.Try)) or not node.body or not isinstance(node.body[0], ast.Expr):
                continue
            if _syntax(node.body[0].value) != _syntax(original_call):
                continue
            node.body[0] = copy.deepcopy(source)
            edit['after'] = ast.unparse(ast.fix_missing_locations(tree)).replace('\n', '\n' + indent)
            candidate['provenance']['inline_source_assertion_retained'] = True
            break
    if candidate['provenance'].get('inline_source_assertion_retained'):
        candidate['id'] = stable_id('exception-assertion-preservation-v1', original_id, candidate['edits'])
        candidate['parent_candidate_id'] = original_id
    return candidate


def _exception_products(kernel, frontend, budget, skipped):
    result = exceptions.generate_exception_contexts(kernel.corpus, frontend, exceptions.ExceptionBudget(
        max_candidates=budget.max_per_domain, max_attempts=budget.max_attempts))
    skipped.update({'exception_seed:' + key: value for key, value in result['skipped'].items()})
    products, seeds = [], []
    for raw in result['candidates']:
        seed = _preserve_inline_assert(kernel, raw)
        seed['relation']['search_operator'] = 'source_exception_input_and_observation_phase'
        seeds.append(seed)
        if seed['relation']['input_route'] != 'receiver_constructor':
            continue
        donor_id, target_id = seed['source_test_ids'][0], seed['base_test_id']
        source_call = kernel.node(seed['provenance']['source_receiver_call_span'], ast.Call)
        if source_call is None or not isinstance(source_call.func, ast.Attribute) or not isinstance(source_call.func.value, ast.Name):
            continue
        donor_origin = kernel.origin(donor_id, source_call.func.value.id,
                                     seed['provenance']['source_receiver_call_span']['start_byte'])
        target_constructor = kernel.call_at(target_id, seed['provenance']['recipient_constructor_span'])
        if donor_origin is None or target_constructor is None:
            continue
        siblings = []
        for donor_arg, target_arg, binding in exceptions._argument_pairs(donor_origin['constructor'], target_constructor):
            if any(_overlap(target_arg['span'], edit['span']) for edit in seed['edits']):
                continue
            try:
                left = kernel.closed(donor_id, donor_arg['span'])
                right = kernel.closed(target_id, target_arg['span'])
                lv = _literal(exceptions._expression_node(left['text']))
                rv = _literal(exceptions._expression_node(right['text']))
                if lv is ... or rv is ... or type(lv) is not type(rv) or lv == rv:
                    continue
            except exceptions.Unsupported:
                continue
            siblings.append(({'span': target_arg['span'], 'before': kernel.text(target_arg['span']),
                              'after': repr(lv), 'role': 'source_constructor_coordinate'},
                             {'source_span': left['span'], 'target_span': target_arg['span'],
                              'binding': binding, 'source_binding_path': left['binding_path']}))
        for size in range(1, min(len(siblings), budget.max_sibling_coordinates) + 1):
            for selected in itertools.combinations(siblings, size):
                row = copy.deepcopy(seed)
                row['edits'].extend(item[0] for item in selected)
                row['id'] = stable_id('constructor-coordinate-product-v1', target_id, row['edits'])
                row['kind'] = 'constructor_coordinate_product'
                row['parent_candidate_id'] = seed['id']
                row['relation'].update(domain='constructor_coordinate_product',
                    search_operator='extend_one_source_input_binding_by_aligned_constructor_coordinates',
                    joint_coordinate_count=1 + size,
                    input_origin=donor_origin['constructor']['span'],
                    resource_origin=target_constructor['span'])
                row['provenance']['sibling_coordinates'] = [item[1] for item in selected]
                products.append(row)
                if len(products) >= budget.max_per_domain:
                    return products, seeds if budget.include_exception_seeds else []
    return products, seeds if budget.include_exception_seeds else []


def _constructor_family(kernel, test_id, name, at):
    """Comparable construction sites, not a claim that strings are paths."""
    binding = kernel.binding(test_id, name, at)
    if binding is None:
        return None
    rhs = kernel.node(binding['value']['span'])
    if isinstance(rhs, ast.BinOp) and isinstance(rhs.left, ast.Name) and _literal(rhs.right) is not ...:
        return ('binary_constructor', type(rhs.op).__name__, rhs.left.id), binding
    if isinstance(rhs, ast.Call):
        constants = [i for i, value in enumerate(rhs.args) if _literal(value) is not ...]
        if len(constants) != 1 or rhs.keywords:
            return None
        shape = copy.deepcopy(rhs)
        shape.args[constants[0]] = ast.Constant(None)
        return ('call_constructor', _syntax(shape)), binding
    return None


def _argument_references(node, depth=0):
    if depth > 4:
        return
    if isinstance(node, ast.Name):
        yield node, ()
    elif isinstance(node, (ast.List, ast.Tuple)):
        for index, item in enumerate(node.elts):
            for reference, path in _argument_references(item, depth + 1):
                yield reference, ('item', index, *path)
    elif isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        # Preserve an existing source adapter, such as str(path).  It is not
        # executed during generation and is not assumed to preserve identity.
        for reference, path in _argument_references(node.args[0], depth + 1):
            yield reference, ('adapter', _syntax(node.func), *path)


def _binding_merges(kernel, ordered, budget, skipped):
    plans, seen, attempts = defaultdict(list), set(), 0
    for test_id in ordered:
        for call in sorted(kernel.calls[test_id], key=lambda row: row['span']['start_byte']):
            roles = []
            markers = []
            for arg in call.get('arguments', ()):
                node = kernel.node(arg['span'])
                elements = node.elts if isinstance(node, (ast.List, ast.Tuple)) else [node]
                for element in elements:
                    if isinstance(element, ast.Constant) and isinstance(element.value, str) and element.value.startswith('--'):
                        markers.append((kernel.span(call['span']['path'], element)['start_byte'], element.value))
            markers.sort()
            for arg in call.get('arguments', ()):
                if not is_operation_argument(call, arg['slot']):
                    continue
                node = kernel.node(arg['span'])
                if node is None:
                    continue
                for reference, access in _argument_references(node):
                    family = _constructor_family(kernel, test_id, reference.id, call['span']['start_byte'])
                    if family is not None:
                        start = kernel.span(call['span']['path'], reference)['start_byte']
                        earlier = [marker for offset, marker in markers if offset < start]
                        # Literal option delimiters give a reproducible source
                        # role partition.  This is a priority restriction, not
                        # a complete parser for arbitrary command line grammars.
                        group = earlier[-1] if earlier else None
                        roles.append((reference, arg, access, family, group))
            roles = roles[:budget.max_roles_per_call]
            for left, right in itertools.permutations(roles, 2):
                attempts += 1
                if attempts > budget.max_attempts:
                    skipped['binding_merge_attempt_budget'] += 1
                    break
                if left[0].id == right[0].id or left[3][0] != right[3][0] or left[4] != right[4]:
                    continue
                position = kernel.span(call['span']['path'], right[0])
                key = test_id, _position(position), left[0].id
                if key in seen:
                    continue
                seen.add(key)
                edit = {'span': position, 'before': right[0].id, 'after': left[0].id, 'role': 'source_binding_merge'}
                candidate = _candidate(kernel, test_id, 'argument_binding_merge', [edit],
                    relation={'cell': 'two_source_constructed_arguments_share_one_binding',
                              'phase': 'before_source_call', 'call_span': call['span'],
                              'roles': [{'slot': role[1]['slot'], 'access': list(role[2]),
                                         'source_span': role[3][1]['span'],
                                         'actual_span': kernel.span(call['span']['path'], role[0])} for role in (left, right)],
                              'expected_binding_partition': [0, 0],
                              'source_marker_group': left[4],
                              'construction_family': list(left[3][0]),
                              'runtime_value_equality': 'unmeasured'},
                    provenance={'source_bindings': [left[3][1]['span'], right[3][1]['span']],
                                'preexisting_prefix_and_all_assertions_retained': True,
                                'unproved': ['adapter_semantics', 'argument_contract_compatibility', 'oracle_applicability']})
                plans[test_id].append(candidate)
            if attempts > budget.max_attempts:
                break
        if attempts > budget.max_attempts:
            break
    result = []
    pending = deque(iter(plans[key]) for key in ordered if plans[key])
    while pending and len(result) < budget.max_per_domain:
        stream = pending.popleft()
        row = next(stream, None)
        if row is not None:
            result.append(row)
            pending.append(stream)
    return result


def _sql_quote(value):
    if type(value) is str:
        return "'" + value.replace("'", "''") + "'"
    if type(value) in {int, float}:
        return repr(value)
    return None


def _string_literals(node):
    for part in ast.walk(node):
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            yield part


def _json_rows(node):
    for literal in _string_literals(node):
        try:
            value = json.loads(literal.value)
        except (TypeError, ValueError):
            continue
        rows = value if isinstance(value, list) else [value]
        if rows and all(isinstance(row, dict) for row in rows):
            yield literal, rows


def _list_carrier(kernel, node):
    parent = kernel.parents.get(id(node))
    if isinstance(parent, (ast.List, ast.Tuple)):
        return parent
    return None


def _same_resource_token(left, right):
    """Source equality is only a binding hypothesis; it is not runtime aliasing."""
    names = lambda node: {_syntax(part) for part in node.elts if isinstance(part, ast.Name)}
    return bool(names(left) & names(right))


def _containing_statement(kernel, node):
    while node is not None and not isinstance(node, ast.stmt):
        node = kernel.parents.get(id(node))
    return node


def _sql_overlap(kernel, ordered, budget, skipped):
    """Add a field-sensitive source-data equality to a source SQL predicate.

    MIN is a fixed constructor in this SQL expression grammar.  It is not an
    inferred invariant: the new test deliberately registers a stronger input
    predicate.  Its value comes from an earlier literal fixture on the same
    source resource/table; current program outputs never become expectations.
    """
    result = []
    for test_id in ordered:
        record = kernel.corpus['tests'][test_id]
        path = record['span']['path']
        test = kernel.node(record.get('definition_span', record['span']), (ast.FunctionDef, ast.AsyncFunctionDef))
        if test is None:
            continue
        strings = list(_string_literals(test))
        writes = []
        for literal in strings:
            program = parse_sql_program(literal.value)
            carrier = _list_carrier(kernel, literal)
            if program and program.kind == 'update' and carrier is not None:
                writes.append((literal, program, carrier))
        for write, program, carrier in writes:
            table = program.table.tokens[-1].text.strip('"`[]')
            write_statement = _containing_statement(kernel, write)
            if write_statement is None:
                continue
            write_rows = list(_json_rows(write_statement))
            for predicate in strings:
                if predicate.lineno >= write.lineno or not _neutral_predicate(_tokens(predicate.value, 512) or []):
                    continue
                owner = _list_carrier(kernel, predicate)
                if owner is None or not _same_resource_token(owner, carrier):
                    continue
                if not any(isinstance(part, ast.Constant) and part.value == table for part in owner.elts):
                    continue
                prior = []
                for call in ast.walk(test):
                    if not isinstance(call, ast.Call) or not predicate.lineno < call.lineno < write.lineno:
                        continue
                    matched = [arg for arg in call.args if isinstance(arg, (ast.List, ast.Tuple))
                               and _same_resource_token(arg, carrier)
                               and any(isinstance(part, ast.Constant) and part.value == table for part in arg.elts)]
                    if matched:
                        prior.extend(_json_rows(call))
                for assignment in program.assignments:
                    field = assignment.field.tokens[-1].text.strip('"`[]')
                    # Distinguish both values before using a fixture boundary.
                    # A parameter with no recoverable JSON actual is unsupported.
                    update_value = program.text[assignment.value_start:assignment.value_end]
                    updated = [row.get(update_value[1:], ...) for _, rows in write_rows for row in rows
                               if update_value.startswith((':', '@', '$'))]
                    if assignment.numeric is not None:
                        updated.append(float(assignment.numeric))
                    for literal, rows in prior[:budget.max_sql_rows]:
                        values = [row[field] for row in rows if field in row]
                        if len(values) != len(rows) or not values or any(value != values[0] for value in values):
                            continue
                        initial = values[0]
                        quoted = _sql_quote(initial)
                        if quoted is None or not any(value is not ... and value != initial for value in updated):
                            continue
                        tokens = _tokens(predicate.value, 512) or []
                        if any(token.kind in {'word', 'identifier'} and token.text.strip('"`[]').lower() == field.lower() for token in tokens):
                            continue  # This neighbour changes disjoint to overlap.
                        field_sql = '"' + field.replace('"', '""') + '"'
                        refined = '(' + predicate.value + ') AND MIN(' + field_sql + ') = ' + quoted
                        position = kernel.span(path, predicate)
                        edit = {'span': position, 'before': kernel.text(position), 'after': repr(refined),
                                'role': 'source_predicate_write_overlap'}
                        result.append(_candidate(kernel, test_id, 'sql_predicate_write_overlap', [edit],
                            relation={'cell': 'source_predicate_disjoint_to_write_field_overlap',
                                      'phase': 'source_write_return', 'table': table, 'field': field,
                                      'read_before': sorted({token.text for token in tokens if token.kind == 'word'}),
                                      'read_after_field': field, 'write_fields': [field],
                                      'source_initial_value': initial, 'source_update_values': [v for v in updated if v is not ...],
                                      'runtime_precondition': 'initial_predicate_true_and_selected_rows_exist',
                                      'runtime_status': 'unmeasured'},
                            provenance={'predicate_span': position, 'write_span': kernel.span(path, write),
                                        'initial_rows_span': kernel.span(path, literal),
                                        'json_bindings': [kernel.span(path, item) for item, _ in write_rows],
                                        'resource_evidence': 'same_source_name_in_operation_argument_lists',
                                        'grammar_constructor': 'conjunction_with_MIN_field_source_literal_equality',
                                        'preexisting_prefix_and_all_assertions_retained': True,
                                        'unproved': ['fixture_insert_succeeded', 'row_filter_overlap', 'oracle_applicability']}))
                        if len(result) >= budget.max_per_domain:
                            return result
    return result


def _pure_read(node):
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _pure_read(node.value)
    if isinstance(node, ast.Subscript):
        key = _literal(node.slice)
        return type(key) in {str, int} and _pure_read(node.value)
    return False


def _observation_reads(node):
    """Read existing paths, not a re-evaluation of getters or predicates."""
    if _pure_read(node):
        yield node
    elif isinstance(node, ast.Call):
        for child in [*node.args, *[keyword.value for keyword in node.keywords]]:
            yield from _observation_reads(child)
    else:
        for child in ast.iter_child_nodes(node):
            yield from _observation_reads(child)


def _probe(kernel, span, phase, roles):
    if _indent(kernel, span) is None or not roles:
        return None
    return {'phase': phase, 'insert_before': span, 'roles': roles}


def _attach_probes(kernel, candidate):
    """Expose exact source cuts to relation_search.runtime's pure-read logger.

    The logger is responsible for descriptors and unknown values.  Here a path
    is only syntactically readonly.  SQL truth cannot be obtained by reading a
    Python variable; this limitation is explicit instead of reporting a static
    SQL rewrite as an observed database transition.
    """
    test_id = candidate['base_test_id']
    path = kernel.corpus['tests'][test_id]['span']['path']
    kind, provenance = candidate['kind'], candidate.get('provenance', {})
    changed, control, origin_roles = [], [], []
    call_span = candidate['relation'].get('call_span') or provenance.get('recipient_invocation_span') or provenance.get('write_span')
    if call_span is None:
        return candidate
    node = kernel.node(call_span)
    statement = _containing_statement(kernel, node)
    if statement is None:
        return candidate
    statement_span = kernel.span(path, statement)
    end = statement_span['end_byte']
    candidate['source_window'] = stable_id('python-source-window', test_id, statement_span)
    if kind == 'argument_binding_merge':
        edit = candidate['edits'][0]
        left, right = edit['after'], edit['before']
        origins = provenance['source_bindings']
        actuals = candidate['relation']['roles']
        origin_roles = [{'name': 'input:0', 'expression': left, 'origin_span': origins[0],
                         'input_span': actuals[0]['actual_span']},
                        {'name': 'input:1', 'expression': right, 'origin_span': origins[1],
                         'input_span': actuals[1]['actual_span']}]
        new_roles = [origin_roles[0], {**origin_roles[1], 'expression': left}]
        changed.append(_probe(kernel, statement_span, 'before_operation', new_roles))
        control.append(_probe(kernel, statement_span, 'before_operation', origin_roles))
    q_rows = [q for q in kernel.observations[test_id] if q.get('observed')
              and q['assertion_span']['start_byte'] > end]
    if candidate.get('target_capsule_id'):
        q_rows = [q for q in q_rows if q['id'] == candidate['target_capsule_id']]
    for q in q_rows[:4]:
        observed = kernel.node(q['observed']['span'])
        if observed is None:
            continue
        reads = list(_observation_reads(observed))[:8]
        roles = [dict(role) for role in origin_roles]
        for index, read in enumerate(reads):
            roles.append({'name': 'observation:' + str(index), 'expression': ast.unparse(read),
                          'origin_span': kernel.span(path, read)})
        if not roles:
            continue
        shifted = copy.deepcopy(roles)
        if kind == 'argument_binding_merge':
            shifted[1]['expression'] = shifted[0]['expression']
        phase = 'after_expected_exception' if provenance.get('source_exception_context_kind') else 'source_observation'
        changed.append(_probe(kernel, q['assertion_span'], phase, shifted))
        control.append(_probe(kernel, q['assertion_span'], 'source_observation', roles))
    candidate['runtime_probes'] = [row for row in changed if row is not None]
    candidate['control_runtime_probes'] = [row for row in control if row is not None]
    if kind == 'sql_predicate_write_overlap':
        candidate['oracle_revision_sites'] = [
            {'assertion_id': q['id'], 'span': q['assertion_span'],
             'observed': q.get('observed'), 'expected': q.get('expected')}
            for q in q_rows[:4]]
        candidate['runtime_profile_limitations'] = ['SQL predicate truth and row-filter overlap require a database read adapter; Python paths alone do not measure them']
    return candidate


def analyze(corpus, frontend, budget=None):
    budget = budget or Budget()
    if corpus.get('language') != 'python':
        return {'candidates': [], 'skipped': {'language_not_python': 1}, 'budget': asdict(budget)}
    kernel = exceptions._Kernel(corpus, frontend)
    skipped = Counter()
    ordered = sorted(corpus['tests'], key=lambda key: (corpus['tests'][key].get('retrieval_rank') or 10**9,
                                                      _position(corpus['tests'][key]['span'])))[:budget.max_tests]
    products, exceptions_only = _exception_products(kernel, frontend, budget, skipped)
    domains = {'constructor_coordinate_product': products,
               'argument_binding_merge': _binding_merges(kernel, ordered, budget, skipped),
               'sql_predicate_write_overlap': _sql_overlap(kernel, ordered, budget, skipped),
               'source_exception_phase': exceptions_only}
    pending = deque(iter(rows) for rows in domains.values() if rows)
    candidates, seen = [], set()
    while pending and len(candidates) < budget.max_candidates:
        stream = pending.popleft()
        row = next(stream, None)
        if row is None:
            continue
        pending.append(stream)
        key = stable_id(row['base_test_id'], row['edits'])
        if key not in seen:
            seen.add(key)
            candidates.append(_attach_probes(kernel, row))
    return {'candidates': candidates, 'skipped': dict(skipped), 'budget': asdict(budget),
            'domain_counts': {key: len(rows) for key, rows in domains.items()},
            'provider_calls': 0, 'source_only': True}


def generate(corpus, frontend, budget=None):
    """Return old-emitter-compatible candidates, without mutating either input."""
    return analyze(corpus, frontend, budget)['candidates']
