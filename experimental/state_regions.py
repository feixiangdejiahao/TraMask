"""Additional Python state contexts from independent straight-line regions.

Original source, scopes, with/async-with managers, and local declarations stay
in place. Only donor operations are transplanted. Region membership establishes
syntactic dominance inside one statement list, not alias, effect, or semantic
equivalence. The frozen state-context front end remains unchanged.
"""
from __future__ import annotations

import ast
import builtins
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import CALLS, Source, call_parts, child, walk
from experimental.semantic_transport import state_contexts as state
from generic_composition.corpus import span


@dataclass
class Region:
    parent: dict
    unit: object
    statements: list
    declarations: dict
    context: tuple
    expanded: bool


def _declaration(node):
    value = node
    if value.type == 'decorated_definition':
        value = next((n for n in value.named_children if n.type in {'class_definition', 'function_definition'}), value)
    return value if value.type in {'class_definition', 'function_definition'} else None


def _declaration_key(source, node):
    return (source.path, node.start_byte, node.end_byte, node.type) if node is not None else None


def _regions(unit, record, capsules):
    """Split at unsupported control; descend only into context-manager bodies."""
    source = unit.source
    expanded = any(n.type in state._CONTROL | state._NESTED for n in unit.body.named_children)
    if any(n.type == 'decorated_definition' for n in unit.body.named_children):
        expanded = True

    def visit(body, declarations, context):
        visible, selected = dict(declarations), []

        def flush():
            nonlocal selected
            if not selected:
                return None
            region = Region(record, unit, selected, dict(visible), context, expanded or bool(context))
            selected = []
            return region

        for statement in body.named_children:
            if statement.type == 'comment':
                continue
            declaration = _declaration(statement)
            if declaration is not None:
                region = flush()
                if region is not None:
                    yield region
                visible[source.text(child(declaration, 'name'))] = declaration
                continue
            if statement.type == 'with_statement':
                region = flush()
                if region is not None:
                    yield region
                nested = child(statement, 'body')
                if nested is not None:
                    yield from visit(nested, visible, (*context, span(source, statement)))
                continue
            if statement.type in {'return_statement', 'raise_statement'}:
                region = flush()
                if region is not None:
                    yield region
                break
            blocked = any(n.type in state._NESTED | state._CONTROL for n in walk(statement))
            if blocked:
                region = flush()
                if region is not None:
                    yield region
                continue
            selected.append(statement)
        region = flush()
        if region is not None:
            yield region

    yield from visit(unit.body, {}, ())


def _producer(index, region, rhs, environment):
    if rhs.type not in CALLS:
        return None
    fn, _ = call_parts(rhs)
    if fn is not None and fn.type == 'identifier':
        name = region.unit.source.text(fn)
        if name not in environment and name in region.declarations:
            declaration = region.declarations[name]
            return ('lexical_declaration', *_declaration_key(region.unit.source, declaration))
    return state._producer(index, region.unit, rhs, environment)


def _region_test(index, region, capsules):
    """Use the same small binding fragment with region-local statement indices."""
    unit, source = region.unit, region.unit.source
    record = dict(region.parent, id=state._id('state_region', region.parent['id'],
                                            [(node.start_byte, node.end_byte) for node in region.statements]))
    assertions = {i for i, statement in enumerate(region.statements) for capsule in capsules
                  if statement.start_byte <= capsule['assertion_span']['start_byte']
                  and capsule['assertion_span']['end_byte'] <= statement.end_byte}
    test = state.Test(record, unit, source, region.statements, assertions=assertions,
                      nodes={(n.start_byte, n.end_byte): n for statement in region.statements for n in walk(statement)})
    environment = {name: state.Binding(name, 'unknown', -1) for name in unit.params}
    for i, statement in enumerate(region.statements):
        test.snapshots.append(dict(environment))
        assignment = state._assignment(statement)
        if assignment and assignment[0].type == 'identifier':
            target, rhs = assignment
            name = source.text(target)
            previous = environment.get(source.text(rhs)) if rhs.type == 'identifier' else None
            producer = _producer(index, region, rhs, environment)
            if producer is not None and any(environment.get(source.text(reference)) is not None
                                           and environment[source.text(reference)].kind == 'receiver'
                                           for reference in state._reads(rhs)):
                producer = None
            if previous is not None and previous.kind == 'receiver':
                binding = state.Binding(name, 'receiver', i, expression=rhs,
                                        origin=previous.origin, producer=previous.producer)
            elif producer is not None:
                binding = state.Binding(name, 'receiver', i, expression=rhs,
                                        origin=state._id(record['id'], target.start_byte), producer=producer)
            else:
                try:
                    if any(n.type in CALLS and not state._inside(rhs, n) for n in walk(statement)):
                        raise state.Unsupported('nonliteral_declaration_metadata')
                    value, dependencies = state._constant(source, rhs, environment)
                    binding = state.Binding(name, 'literal', i, value, rhs, dependencies)
                except state.Unsupported:
                    binding = state.Binding(name, 'unknown', i, expression=rhs)
            environment[name] = binding
            test.assignments[i] = binding
            if any(n.type in CALLS for n in walk(rhs)):
                for reference in state._reads(rhs):
                    used = source.text(reference)
                    if used in environment and environment[used].kind == 'literal':
                        environment[used] = state.Binding(used, 'unknown', i)
            continue
        if assignment or any(n.type in CALLS for n in walk(statement)):
            for reference in state._reads(statement):
                name = source.text(reference)
                if name in environment and environment[name].kind == 'literal':
                    environment[name] = state.Binding(name, 'unknown', i)
    return test


def _external_shadowed(index, region, test, name):
    """Python binders apply across regions, including for/with/import targets."""
    cache = getattr(index, '_state_region_python_bindings', None)
    if cache is None:
        cache = index._state_region_python_bindings = {}
    path = test.source.path
    if path not in cache:
        module = ast.parse(test.source.code)
        offsets, total = [], 0
        for line in test.source.data.splitlines(keepends=True):
            offsets.append(total)
            total += len(line)
        def position(node):
            return offsets[node.lineno - 1] + node.col_offset
        global_writes, stack = set(), list(module.body)
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                global_writes.add(node.id)
            stack.extend(ast.iter_child_nodes(node))
        functions = {position(node): node for node in ast.walk(module)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        cache[path] = position, global_writes, functions, {}
    position, global_writes, functions, locals_by_function = cache[path]
    if name in global_writes:
        return True
    start = test.unit.node.start_byte
    if start not in locals_by_function:
        function = functions.get(start)
        if function is None:
            return True
        bindings = defaultdict(list)
        for node in ast.walk(function):
            bound = None
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                bound = node.id
            elif isinstance(node, ast.arg):
                bound = node.arg
            elif node is not function and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound = node.name
            elif isinstance(node, ast.alias):
                bound = node.asname or node.name.split('.')[0]
            elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
                bound = node.name
            elif isinstance(node, ast.MatchMapping):
                bound = node.rest
            if bound:
                bindings[bound].append(node)
        locals_by_function[start] = bindings
    declaration = region.declarations.get(name)
    return any(declaration is None or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               or position(node) != declaration.start_byte
               for node in locals_by_function[start].get(name, ()))


def _builtin_available(index, region, test, name):
    if (not callable(getattr(builtins, name, None)) or name in test.unit.params
            or name in test.source.imports or name in region.declarations
            or index.local_functions(test.unit, name) or name in index.classes):
        return False
    return not _external_shadowed(index, region, test, name)


def _operation(index, region, test, i, origin):
    """Also retain a call-valued assignment's entire RHS as an operation.

    Return values remain unknown in the binding scanner. A later operation
    requiring one therefore fails dependency closure, so a transferred slice
    cannot silently use a discarded result. No assignment alone proves an
    effect: the edited observation still needs its may-state witness.
    """
    assignment = state._assignment(test.statements[i])
    if (i in test.assertions or assignment is None or assignment[0].type != 'identifier'
            or state._unwrap(assignment[1]).type not in CALLS):
        return state._operation(index, test, i, origin)
    target, expression = assignment
    if any(node.type == 'string' and node.start_point.row != node.end_point.row for node in walk(expression)):
        raise state.Unsupported('rhs_multiline_literal_requires_byte_preserving_renderer')
    environment = test.snapshots[i]
    arguments, required, callees, builtin_names, has_receiver = [], [], set(), set(), False

    def receiver(node):
        binding = environment.get(test.source.text(node)) if node is not None else None
        return binding if binding is not None and binding.kind == 'receiver' and binding.origin == origin else None

    def visit(node):
        nonlocal has_receiver
        node = state._unwrap(node)
        if node.type not in CALLS:
            if node.type == 'identifier' and receiver(node) is not None:
                has_receiver = True
                return
            value, dependencies = state._constant(test.source, node, environment)
            arguments.append((value, node))
            required.extend(dependencies)
            return
        fn, values = call_parts(node)
        root = state._root(fn)
        if fn is not None and fn.type in state.ATTRS and receiver(root) is not None:
            has_receiver = True
        else:
            identity = _producer(index, region, node, environment)
            builtin = (fn is not None and fn.type == 'identifier'
                       and _builtin_available(index, region, test, test.source.text(fn)))
            if identity is None and not builtin:
                raise state.Unsupported('rhs_external_callee_unresolved')
            if any(_external_shadowed(index, region, test, test.source.text(ref)) for ref in state._reads(fn)):
                raise state.Unsupported('rhs_external_callee_shadowed_at_source')
            if identity is None and builtin:
                builtin_names.add(test.source.text(fn))
            callees.update((ref.start_byte, ref.end_byte) for ref in state._reads(fn))
        for argument in values:
            value = child(argument, 'value') if argument.type == 'keyword_argument' else argument
            if value is None:
                raise state.Unsupported('operation_argument_missing')
            visit(value)

    # Constructors and pure assignments without this receiver are not state
    # operations and must not become dependency barriers between real calls.
    if not any(receiver(ref) is not None for ref in state._reads(expression)):
        return None
    visit(expression)
    if not has_receiver:
        return None
    references = []
    for reference in state._reads(expression):
        if (reference.start_byte, reference.end_byte) in callees:
            continue
        binding = environment.get(test.source.text(reference))
        if binding is None or (binding.kind != 'literal' and receiver(reference) is None):
            raise state.Unsupported('operation_dependency_not_closed')
        references.append((reference, binding))
        if binding.kind == 'literal':
            required.append(binding)
    return {'statement': i, 'references': references, 'required': required, 'arguments': arguments,
            'external_names': {test.source.data[lo:hi].decode() for lo, hi in callees},
            'builtin_names': builtin_names, 'expression': expression, 'discarded_binding': test.source.text(target)}


def _render(donor, operations, *args):
    # Keep original AST byte positions for substitutions/provenance. The
    # frozen renderer receives RHS nodes in place of just these assignments.
    statements = list(donor.statements)
    constants = state._closure(binding for operation in operations for binding in operation['required'])
    if any(node.type == 'string' and node.start_point.row != node.end_point.row
           for binding in constants for node in walk(binding.expression)):
        raise state.Unsupported('literal_closure_multiline_string_requires_byte_preserving_renderer')
    for operation in operations:
        if 'expression' in operation:
            statements[operation['statement']] = operation['expression']
    return state._render(replace(donor, statements=statements), operations, *args)


def _external_declarations_match(donor, recipient, operations):
    for operation in operations:
        for name in operation['external_names']:
            left = _declaration_key(donor.unit.source, donor.declarations.get(name))
            right = _declaration_key(recipient.unit.source, recipient.declarations.get(name))
            if left != right:
                raise state.Unsupported('region_external_declaration_mismatch')


def generate_state_regions(corpus, *, top_k=10, max_candidates=128, max_attempts=2000):
    """Generate additional contexts involving an expanded Python region.

    Plain-to-plain pairs are additional only for discarded call RHSs. Parameters, helper
    oracles, loop/branch internals, and other languages are not expanded here.
    Every returned edit and capsule ID refers to the original corpus.
    """
    if any(type(value) is not int or value < 1 for value in (top_k, max_candidates, max_attempts)):
        raise ValueError('State-region budgets must be positive integers')
    skipped, candidates, seen, attempts = Counter(), [], set(), 0

    def result(exhausted=False):
        return {'candidates': candidates, 'skipped': dict(skipped), 'attempts': attempts,
                'budget_exhausted': exhausted}

    if corpus['language'] != 'python':
        skipped['language_region_expansion_not_enabled'] += 1
        return result()
    sources = [Source(path, metadata['code'], metadata.get('language', corpus['language']))
               for path, metadata in sorted(corpus['sources'].items())
               if metadata.get('complete_file', True) and not metadata.get('parse_error')]
    index = Index(sources, '')
    capsules = defaultdict(list)
    for capsule in corpus['capsules']:
        capsules[capsule['test_id']].append(capsule)
    ordered = sorted(corpus['tests'].values(), key=lambda row: (row.get('retrieval_rank') or 99999, row['id']))
    seeds = {row['id'] for row in ordered if row.get('retrieval_rank') and row['retrieval_rank'] <= top_k}
    if not seeds:
        seeds = {row['id'] for row in ordered[:top_k]}
    groups = defaultdict(list)
    for record in ordered:
        if record.get('parameterization_status', 'none_detected') != 'none_detected':
            skipped['parameter_rows_require_instantiation'] += 1
            continue
        unit = index.units.get(record['id'])
        scope = record.get('enclosing_scope_span')
        if unit is None or not scope:
            skipped['missing_source_or_enclosing_scope'] += 1
            continue
        for region in _regions(unit, record, capsules[record['id']]):
            local_capsules = [capsule for capsule in capsules[record['id']] if any(
                statement.start_byte <= capsule['assertion_span']['start_byte']
                and capsule['assertion_span']['end_byte'] <= statement.end_byte for statement in region.statements)]
            if not local_capsules:
                continue
            try:
                test = _region_test(index, region, local_capsules)
            except state.Unsupported as exc:
                skipped[str(exc)] += 1
                continue
            for capsule in local_capsules:
                try:
                    observations = state._observations(test, capsule)
                except state.Unsupported as exc:
                    skipped[str(exc)] += 1
                    continue
                if not observations:
                    skipped['region_receiver_dependency_not_closed'] += 1
                for insertion, receiver, binding in observations:
                    key = (unit.source.path, scope['start_byte'], scope['end_byte'], binding.producer)
                    groups[key].append((region, test, capsule, insertion, receiver, binding))
    plans = defaultdict(list)
    for group in groups.values():
        contexts = []
        for observation in group:
            donor_region, donor, _, stop, _, binding = observation
            operations = []
            for i in range(stop):
                try:
                    operation = _operation(index, donor_region, donor, i, binding.origin)
                    if operation is not None:
                        operations.append(operation)
                except state.Unsupported as exc:
                    skipped[str(exc)] += 1
                    operations.append(None)
            for start in range(len(operations)):
                if operations[start] is None:
                    continue
                for count in range(1, min(3, len(operations) - start) + 1):
                    selected = operations[start:start + count]
                    if any(operation is None for operation in selected):
                        break
                    contexts.append((observation, selected))
        for recipient in group:
            plans[recipient[0].parent['id']].append((recipient, contexts))

    def proposals(recipient_plans):
        for recipient, contexts in recipient_plans:
            region, test, *_ = recipient
            for donor, operations in contexts:
                donor_region, donor_test, *_ = donor
                additional = region.expanded or donor_region.expanded or any('expression' in operation for operation in operations)
                if test.record['id'] == donor_test.record['id'] or not additional:
                    continue
                if region.parent['id'] not in seeds and donor_region.parent['id'] not in seeds:
                    continue
                yield recipient, donor, operations

    turns = deque(proposals(plans[row['id']]) for row in sorted(
        ordered, key=lambda row: (row['id'] not in seeds, row.get('retrieval_rank') or 99999, row['id']))
        if row['id'] in plans)
    while turns:
        stream = turns.popleft()
        proposal = next(stream, None)
        if proposal is None:
            continue
        turns.append(stream)
        if attempts >= max_attempts:
            skipped['attempt_budget'] += 1
            return result(True)
        attempts += 1
        recipient_data, donor_data, operations = proposal
        region, recipient, capsule, insertion, receiver, _ = recipient_data
        donor_region, donor, donor_capsule, _, _, binding = donor_data
        identifier = state._id('state_region_context', donor.record['id'],
                               [operation['statement'] for operation in operations], capsule['id'], receiver)
        try:
            _external_declarations_match(donor_region, region, operations)
            if any(not _builtin_available(index, region, recipient, name) for operation in operations
                   for name in operation.get('builtin_names', ())):
                raise state.Unsupported('rhs_builtin_shadowed_at_target')
            if any(_external_shadowed(index, region, recipient, name) for operation in operations
                   if 'expression' in operation for name in operation['external_names']):
                raise state.Unsupported('rhs_external_callee_shadowed_at_target')
            text, positions, arguments, argument_sources, alpha = _render(
                donor, operations, recipient, insertion, receiver, identifier)
            position = recipient.statements[insertion].start_byte
            key = (region.parent['id'], capsule['id'], position, text)
            if key in seen:
                continue
            witnesses = state._witness(sources, recipient, capsule, insertion, text, positions, receiver)
        except state.Unsupported as exc:
            skipped[str(exc)] += 1
            continue
        seen.add(key)
        location = dict(span(recipient.source, recipient.statements[insertion]), end_byte=position)
        location['end_line'] = location['line']
        aliases = sorted({bound.name for operation in operations for _, bound in operation['references']
                          if bound.kind == 'receiver'})
        candidates.append({'id': identifier, 'base_test_id': region.parent['id'],
            'source_test_ids': [donor_region.parent['id']], 'language': 'python', 'kind': 'state_context',
            'rule_id': state._id('state_region_rule', donor.record['id'], [operation['statement'] for operation in operations]),
            'imports': [], 'edits': [{'span': location, 'before': '', 'after': text}],
            'target_capsule_id': capsule['id'], 'arg_values': arguments,
            'provenance': {'frontend': 'state_regions', 'donor_capsule_id': donor_capsule['id'],
                'producer_identity': binding.producer, 'receiver_mapping': {name: receiver for name in aliases},
                'operation_spans': [span(donor.source, donor.statements[operation['statement']]) for operation in operations],
                'operation_count': len(operations), 'argument_sources': argument_sources,
                'discarded_result_bindings': [operation['discarded_binding'] for operation in operations
                                              if 'discarded_binding' in operation],
                'literal_binding_renames': {bound.name: name for bound, name in alpha.items()},
                'insertion_statement': span(recipient.source, recipient.statements[insertion]),
                'observation_state_witnesses': witnesses,
                'donor_region': {'id': donor.record['id'], 'context': donor_region.context,
                                 'statements': [span(donor.source, n) for n in donor.statements]},
                'recipient_region': {'id': recipient.record['id'], 'context': region.context,
                                     'statements': [span(recipient.source, n) for n in recipient.statements]},
                'dependency_precision': 'same_straight_line_region_with_original_source_may_state_witness',
                'unproved': ['full_aliasing', 'global_and_fixture_effects', 'context_manager_effects',
                             'local_class_capture_state', 'call_effects', 'oracle_transport'],
                'oracle_status': 'requires_observation_completion'}})
        if len(candidates) >= max_candidates:
            skipped['candidate_budget'] += 1
            return result(True)
    return result()
