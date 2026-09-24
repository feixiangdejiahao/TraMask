"""Transfer short, source-backed receiver operations between existing tests.

This front end proposes local may-state contexts. Constructor identity and
lexical closure are mechanical filters, not an effect, alias, or oracle proof.
No subject API vocabulary, execution, model call, or guest-language parser is
used. General callbacks, control-flow regions, and returned receivers remain
outside this deliberately small straight-line fragment.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
import hashlib
import json

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import ATTRS, CALLS, FUNCTIONS, Source, attr_parts, call_parts, child, literal, walk
from generic_composition.corpus import _callee_identity, span


_CONTROL = {'if_statement', 'for_statement', 'for_in_statement', 'while_statement',
            'try_statement', 'with_statement', 'switch_statement', 'expression_switch_statement',
            'select_statement', 'go_statement', 'defer_statement', 'global_statement', 'nonlocal_statement'}
_NESTED = FUNCTIONS | {'class_definition', 'class_declaration', 'lambda', 'arrow_function',
                       'function_expression', 'func_literal'}
_ASSIGN = {'assignment', 'assignment_expression', 'assignment_statement', 'short_var_declaration',
           'variable_declarator', 'var_spec', 'const_spec'}
_DECLARATIONS = {'lexical_declaration', 'variable_declaration', 'var_declaration', 'const_declaration'}
_INDEX = {'subscript', 'subscript_expression', 'index_expression'}


class Unsupported(ValueError):
    pass


def _id(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _inside(outer, inner):
    return outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def _unwrap(node):
    while node is not None and node.type in {'expression_list', 'parenthesized_expression'} and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


def _root(node):
    node = _unwrap(node)
    while node is not None:
        if node.type == 'identifier':
            return node
        if node.type in ATTRS:
            node = attr_parts(node)[0]
        elif node.type in _INDEX:
            node = child(node, 'value', 'object', 'operand')
        else:
            return None
        node = _unwrap(node)
    return None


def _reads(node):
    """Value references only; member/keyword/record keys are not binders."""
    for value in walk(node):
        if value.type == 'shorthand_property_identifier':
            yield value
            continue
        if value.type != 'identifier':
            continue
        parent = value.parent
        if parent is not None:
            if parent.type in ATTRS and value == attr_parts(parent)[1]:
                continue
            if parent.type == 'keyword_argument' and value == child(parent, 'name'):
                continue
            if parent.type in {'pair', 'keyed_element'} and value == child(parent, 'key'):
                continue
        yield value


def _assignment(statement):
    node = statement
    if node.type == 'expression_statement' and len(node.named_children) == 1:
        node = node.named_children[0]
    if node.type in _DECLARATIONS:
        declarations = [n for n in walk(node) if n.type in {'variable_declarator', 'var_spec', 'const_spec'}]
        if len(declarations) != 1:
            return None
        node = declarations[0]
    if node.type not in _ASSIGN:
        return None
    if node.type in {'var_spec', 'const_spec'} and len(node.children_by_field_name('name')) != 1:
        return None
    target, value = _unwrap(child(node, 'left', 'name')), _unwrap(child(node, 'right', 'value'))
    return (target, value) if target is not None and value is not None else None


@dataclass(eq=False)
class Binding:
    name: str
    kind: str
    statement: int
    value: object = None
    expression: object = None
    dependencies: tuple = ()
    origin: str | None = None
    producer: tuple | None = None


@dataclass
class Test:
    record: dict
    unit: object
    source: Source
    statements: list
    snapshots: list = field(default_factory=list)
    assignments: dict = field(default_factory=dict)
    assertions: set = field(default_factory=set)
    nodes: dict = field(default_factory=dict)


def _constant(source, node, environment):
    node = _unwrap(node)
    if node is None:
        raise Unsupported('missing_literal_dependency')
    if node.type == 'identifier':
        binding = environment.get(source.text(node))
        if binding is None or binding.kind != 'literal':
            raise Unsupported('missing_literal_dependency')
        return binding.value, (binding,)
    # The standard literal parser never evaluates identifiers or calls.
    if not (source.language == 'typescript' and node.type == 'object'):
        try:
            return literal(source.text(node)), ()
        except ValueError:
            pass
    sequences = {'list', 'tuple', 'array', 'literal_value'}
    if source.language == 'typescript' and node.type == 'object':
        values, dependencies = {}, []
        for entry in node.named_children:
            if entry.type == 'comment':
                continue
            if entry.type == 'shorthand_property_identifier':
                key = source.text(entry)
                binding = environment.get(key)
                if binding is None or binding.kind != 'literal':
                    raise Unsupported('missing_literal_dependency')
                value, refs = binding.value, (binding,)
            elif entry.type == 'pair':
                key_node, value_node = child(entry, 'key'), child(entry, 'value')
                if key_node is None or value_node is None or key_node.type == 'computed_property_name':
                    raise Unsupported('nonliteral_object_key')
                try:
                    key = source.text(key_node) if key_node.type in {'identifier', 'property_identifier'} else literal(source.text(key_node))
                except ValueError:
                    raise Unsupported('nonliteral_object_key') from None
                if type(key) not in {str, int}:
                    raise Unsupported('nonliteral_object_key')
                key = str(key)
                value, refs = _constant(source, value_node, environment)
            else:
                raise Unsupported('nonliteral_object_entry')
            if key == '__proto__':
                raise Unsupported('object_prototype_entry_requires_semantic_analysis')
            values[key] = value
            dependencies.extend(refs)
        return values, tuple(dependencies)
    if node.type in sequences:
        values, dependencies = [], []
        for nested in node.named_children:
            if nested.type == 'comment':
                continue
            value, refs = _constant(source, nested, environment)
            values.append(value)
            dependencies.extend(refs)
        return (tuple(values) if node.type == 'tuple' else values), tuple(dependencies)
    raise Unsupported('nonliteral_operation_argument')


def _producer(index, unit, node, environment):
    if node.type not in CALLS:
        return None
    fn, _ = call_parts(node)
    root = _root(fn)
    if root is not None and unit.source.text(root) in environment:
        return None  # A local shadow is not the file's imported/global callee.
    identity = _callee_identity(index, unit, node)
    if identity.get('canonical') and identity.get('resolution') in {
            'import_alias', 'local_symbol', 'import_symbol', 'package_symbol'}:
        return ('callee', identity['canonical'])
    name = unit.source.text(fn)
    candidates = [(uid, reason) for uid, reason in index.resolve(unit, name) if reason == 'constructor']
    if len(candidates) == 1:
        target = index.units[candidates[0][0]]
        return ('class', target.source.path, target.owner)
    # Classes without explicit constructors are still resolved source symbols.
    classes = [n for n in unit.source.root.named_children
               if n.type in {'class_definition', 'class_declaration'} and unit.source.text(child(n, 'name')) == name]
    if len(classes) == 1:
        return ('class', unit.source.path, name)
    return None


def _test(index, record, capsules):
    unit = index.units.get(record['id'])
    if unit is None:
        raise Unsupported('test_unit_missing')
    source = unit.source
    if record.get('parameterization_status', 'none_detected') != 'none_detected':
        raise Unsupported('parameter_rows_require_instantiation')
    container = next((n for n in unit.body.named_children if n.type == 'statement_list'), unit.body)
    statements = [n for n in container.named_children if n.type != 'comment']
    assertions = {i for i, statement in enumerate(statements) for capsule in capsules
                  if statement.start_byte <= capsule['assertion_span']['start_byte']
                  and capsule['assertion_span']['end_byte'] <= statement.end_byte}
    result = Test(record, unit, source, statements, assertions=assertions,
                  nodes={(n.start_byte, n.end_byte): n for n in walk(unit.body)})
    environment = {name: Binding(name, 'unknown', -1) for name in unit.params}
    for i, statement in enumerate(statements):
        result.snapshots.append(dict(environment))
        if (any(n.type in _NESTED for n in walk(statement))
                or i not in assertions and any(n.type in _CONTROL for n in walk(statement))):
            raise Unsupported('control_or_nested_scope_requires_region_analysis')
        assignment = _assignment(statement)
        if assignment:
            target, rhs = assignment
            if target.type == 'identifier':
                name = source.text(target)
                previous = environment.get(source.text(rhs)) if rhs.type == 'identifier' else None
                producer = _producer(index, unit, rhs, environment)
                if producer is not None and any(
                        environment.get(source.text(reference)) is not None
                        and environment[source.text(reference)].kind == 'receiver'
                        for reference in _reads(rhs)):
                    # A call consuming an existing object is an observation (or
                    # a returned-receiver transformation, which is unsupported),
                    # not a fresh constructor merely because it resolves.
                    producer = None
                if previous is not None and previous.kind == 'receiver':
                    binding = Binding(name, 'receiver', i, expression=rhs,
                                      origin=previous.origin, producer=previous.producer)
                elif producer is not None:
                    binding = Binding(name, 'receiver', i, expression=rhs,
                                      origin=_id(record['id'], target.start_byte), producer=producer)
                else:
                    try:
                        if any(n.type in CALLS and not _inside(rhs, n) for n in walk(statement)):
                            raise Unsupported('nonliteral_declaration_metadata')
                        value, dependencies = _constant(source, rhs, environment)
                        binding = Binding(name, 'literal', i, value, rhs, dependencies)
                    except Unsupported:
                        binding = Binding(name, 'unknown', i, expression=rhs)
                environment[name] = binding
                result.assignments[i] = binding
                if any(n.type in CALLS for n in walk(rhs)):
                    for reference in _reads(rhs):
                        used = source.text(reference)
                        if used in environment and environment[used].kind == 'literal':
                            environment[used] = Binding(used, 'unknown', i)
                continue
            if target.type not in ATTRS | _INDEX:
                for assigned in walk(target):
                    if assigned.type in {'identifier', 'shorthand_property_identifier_pattern'}:
                        name = source.text(assigned)
                        environment[name] = Binding(name, 'unknown', i)
        # A literal container passed to unknown code may no longer be static.
        # This loses some contexts but never silently exports its initial value.
        try:
            references = {source.text(n) for n in _reads(statement)}
        except Unsupported:
            references = set()
        if any(n.type in CALLS for n in walk(statement)) or assignment:
            for name in references:
                if name in environment and environment[name].kind == 'literal':
                    environment[name] = Binding(name, 'unknown', i)
    return result


def _statement(test, start, end):
    return next((i for i, node in enumerate(test.statements)
                 if node.start_byte <= start and end <= node.end_byte), None)


def _observations(test, capsule):
    if capsule.get('helper_assertions'):
        raise Unsupported('helper_observation_requires_port_expansion')
    observed = capsule.get('observed')
    if not observed:
        raise Unsupported('observation_expression_missing')
    spans = [observed['span'], *capsule.get('observation_value_sources', [])]
    found = {}
    for position in spans:
        node = test.nodes.get((position['start_byte'], position['end_byte']))
        if node is None:
            continue
        i = _statement(test, node.start_byte, node.end_byte)
        if i is None:
            continue
        # Initialization and a direct alias preserve the receiver identity; they
        # are not the final observation evaluation to precede.
        if i in test.assignments and test.assignments[i].kind == 'receiver':
            continue
        assignment = _assignment(test.statements[i])
        if assignment is not None and assignment[0].type in ATTRS | _INDEX:
            continue  # Address reads belong to an earlier heap update.
        if i not in test.assertions and assignment is None:
            continue  # Discarded call results are preceding operations.
        for reference in _reads(node):
            binding = test.snapshots[i].get(test.source.text(reference))
            if binding is not None and binding.kind == 'receiver':
                old = found.get(binding.origin)
                if old is None or i < old[0]:
                    # Use the actual observation's receiver name. Choosing an
                    # arbitrary alias would require Flow to prove points-to
                    # equivalence that its local may analysis does not supply.
                    found[binding.origin] = (i, test.source.text(reference), binding)
    return list(found.values())


def _operation(index, test, i, origin):
    statement = test.statements[i]
    if i in test.assertions or i in test.assignments:
        return None
    node = statement.named_children[0] if statement.type == 'expression_statement' and len(statement.named_children) == 1 else statement
    assignment = _assignment(statement)
    values, required = [], []
    callees = set()
    if node.type in CALLS:
        fn, arguments = call_parts(node)
        root = _root(attr_parts(fn)[0]) if fn is not None and fn.type in ATTRS else None
        receiver = test.snapshots[i].get(test.source.text(root)) if root is not None else None
        receiver_matches = receiver is not None and receiver.kind == 'receiver' and receiver.origin == origin
        if not receiver_matches:
            identity = _producer(index, test.unit, node, test.snapshots[i])
            if identity is None:
                return None
            callees = {(ref.start_byte, ref.end_byte) for ref in _reads(fn)}
        has_receiver = receiver_matches
        for argument in arguments:
            value_node = child(argument, 'value') if argument.type == 'keyword_argument' else argument
            if value_node is None:
                raise Unsupported('operation_argument_missing')
            binding = test.snapshots[i].get(test.source.text(value_node)) if value_node.type == 'identifier' else None
            if binding is not None and binding.kind == 'receiver' and binding.origin == origin:
                has_receiver = True
                continue
            value, dependencies = _constant(test.source, value_node, test.snapshots[i])
            values.append((value, value_node))
            required.extend(dependencies)
        if not has_receiver:
            return None
    elif assignment:
        target, rhs = assignment
        root = _root(target)
        receiver = test.snapshots[i].get(test.source.text(root)) if root is not None else None
        if target.type not in ATTRS | _INDEX or receiver is None or receiver.kind != 'receiver' or receiver.origin != origin:
            return None
        value, dependencies = _constant(test.source, rhs, test.snapshots[i])
        values.append((value, rhs))
        required.extend(dependencies)
        for nested in walk(target):
            if nested.type in _INDEX:
                index_node = child(nested, 'subscript', 'index')
                _, dependencies = _constant(test.source, index_node, test.snapshots[i])
                required.extend(dependencies)
    else:
        return None
    references = []
    for reference in _reads(statement):
        if (reference.start_byte, reference.end_byte) in callees:
            continue
        binding = test.snapshots[i].get(test.source.text(reference))
        if binding is None or (binding.kind != 'literal' and not (binding.kind == 'receiver' and binding.origin == origin)):
            raise Unsupported('operation_dependency_not_closed')
        references.append((reference, binding))
        if binding.kind == 'literal':
            required.append(binding)
    external_names = {test.source.data[lo:hi].decode() for lo, hi in callees}
    return {'statement': i, 'references': references, 'required': required,
            'arguments': values, 'external_names': external_names}


def _closure(bindings):
    found = set()
    def visit(binding):
        if binding in found:
            return
        if binding.kind != 'literal':
            raise Unsupported('operation_dependency_not_literal')
        for dependency in binding.dependencies:
            visit(dependency)
        found.add(binding)
    for binding in bindings:
        visit(binding)
    return sorted(found, key=lambda binding: binding.statement)


def _replace(source, node, substitutions):
    raw = source.data[node.start_byte:node.end_byte]
    for lo, hi, replacement in sorted(substitutions, reverse=True):
        raw = raw[:lo - node.start_byte] + replacement.encode() + raw[hi - node.start_byte:]
    return raw.decode()


def _binding_replacement(source, node, replacement):
    # A shorthand property's name is both a key and a variable reference.
    # Alpha-renaming the value must keep the original property key.
    if node.type == 'shorthand_property_identifier':
        return source.text(node) + ': ' + replacement
    return replacement


def _render(donor, operations, recipient, insertion, receiver, identifier):
    # Python locals and JS lexical declarations shadow the whole block,
    # including occurrences before their initializer. The all-declaration
    # check is also a conservative restriction for Go's narrower scopes.
    occupied_external = set(recipient.snapshots[insertion]) | {b.name for b in recipient.assignments.values()}
    if any(operation['external_names'] & occupied_external for operation in operations):
        raise Unsupported('external_callee_shadowed_at_target')
    constants = _closure(binding for operation in operations for binding in operation['required'])
    occupied = {recipient.source.text(n) for n in walk(recipient.unit.node) if n.type == 'identifier'}
    names = {}
    for i, binding in enumerate(constants):
        fresh = 'gc_ctx_' + identifier[:8] + '_' + str(i)
        while fresh in occupied:
            fresh += '_'
        occupied.add(fresh)
        names[binding] = fresh
    rows, argument_values, argument_sources = [], [], []
    for binding in constants:
        statement = donor.statements[binding.statement]
        assignment = _assignment(statement)
        target, rhs = assignment
        if any(donor.source.text(n) in occupied_external for n in walk(statement)
               if n.type == 'identifier' and not _inside(rhs, n) and not _inside(target, n)):
            raise Unsupported('declaration_type_shadowed_at_target')
        substitutions = [(target.start_byte, target.end_byte, names[binding])]
        environment = donor.snapshots[binding.statement]
        for reference in _reads(rhs):
            dependency = environment.get(donor.source.text(reference))
            if dependency not in names:
                raise Unsupported('literal_closure_not_closed')
            substitutions.append((reference.start_byte, reference.end_byte,
                                  _binding_replacement(donor.source, reference, names[dependency])))
        rows.append((_replace(donor.source, statement, substitutions), False, binding.statement))
    for operation_index, operation in enumerate(operations):
        statement = donor.statements[operation['statement']]
        substitutions = [(node.start_byte, node.end_byte, _binding_replacement(donor.source, node,
                           receiver if binding.kind == 'receiver' else names[binding]))
                         for node, binding in operation['references']]
        rendered = _replace(donor.source, statement, substitutions)
        if donor.source.language == 'typescript' and 'discarded_binding' in operation:
            rendered += ';'  # Keep a discarded RHS independent of the next expression.
        rows.append((rendered, True, operation['statement']))
        for value, node in operation['arguments']:
            argument_sources.append({'operation': operation_index, 'index': len(argument_values),
                                     'span': span(donor.source, node)})
            argument_values.append(value)
    position = recipient.statements[insertion].start_byte
    line_start = recipient.source.data.rfind(b'\n', 0, position) + 1
    before = recipient.source.data[line_start:position].decode()
    if before.strip():
        # Python semicolon suites need special indentation/scoping treatment.
        if recipient.source.language == 'python':
            raise Unsupported('inline_python_insertion_requires_suite_rewrite')
        indent = ' ' * (recipient.statements[insertion].start_point.column or 1)
    else:
        indent = before
    pieces, operation_spans, offset = [], [], position
    for text, is_operation, source_statement in rows:
        # Multi-line simple expressions retain their relative continuation
        # indentation. Blocks/callbacks were rejected before this stage.
        original = donor.statements[source_statement]
        original_indent = original.start_point.column
        lines = text.splitlines()
        normalized = lines[0] + ''.join('\n' + indent + line[min(original_indent, len(line) - len(line.lstrip())):]
                                      for line in lines[1:])
        if is_operation:
            operation_spans.append({'start_byte': offset, 'end_byte': offset + len(normalized.encode())})
        part = normalized + '\n' + indent
        pieces.append(part)
        offset += len(part.encode())
    return ''.join(pieces), operation_spans, argument_values, argument_sources, names


def _witness(sources, recipient, capsule, insertion, text, operations, receiver):
    source = recipient.source
    position = recipient.statements[insertion].start_byte
    replacement = text.encode()
    edited = Source(source.path, (source.data[:position] + replacement + source.data[position:]).decode(), source.language)
    if edited.root.has_error:
        raise Unsupported('inserted_context_parse_error')
    if source.language == 'python':
        try:
            ast.parse(edited.code)
        except SyntaxError:
            raise Unsupported('inserted_context_python_parse_error') from None
    # Parsed unchanged files are immutable inputs shared by every attempt.
    index = Index([edited if original.path == source.path else original for original in sources], '')
    unit = index.units.get(recipient.unit.id)
    if unit is None:
        raise Unsupported('edited_test_unit_missing')
    flow = index.flow(unit.id)
    observed = capsule['observed']['span']
    lo, hi = observed['start_byte'] + len(replacement), observed['end_byte'] + len(replacement)
    roots = [node['id'] for node in flow.nodes if node['start_byte'] == lo and node['end_byte'] == hi
             and node['kind'] not in {'assertion', 'may_effect', 'definition'}]
    if not roots:
        raise Unsupported('edited_observation_flow_missing')
    cone = flow.slice(roots)
    witnesses = [node for node in flow.nodes if node['id'] in cone and node['kind'] == 'may_effect'
                 and node.get('variable') == receiver and any(
                     operation['start_byte'] <= node['start_byte'] <= node['end_byte'] <= operation['end_byte']
                     for operation in operations)]
    if not witnesses:
        raise Unsupported('inserted_operation_outside_observation_state_cone')
    return [{'node': node['id'], 'start_byte': node['start_byte'], 'end_byte': node['end_byte']}
            for node in witnesses]


def generate_state_contexts(corpus, *, top_k=10, max_candidates=128, max_attempts=2000):
    """Propose emitter-compatible insertions; callers must supply the oracle."""
    if any(type(value) is not int or value < 1 for value in (top_k, max_candidates, max_attempts)):
        raise ValueError('State-context budgets must be positive integers')
    skipped, candidates, seen = Counter(), [], set()
    attempts = 0

    def result(exhausted=False):
        return {'candidates': candidates, 'skipped': dict(skipped),
                'attempts': attempts, 'budget_exhausted': exhausted}
    sources = [Source(path, metadata['code'], metadata.get('language', corpus['language']))
               for path, metadata in sorted(corpus['sources'].items())
               if metadata.get('complete_file', True) and not metadata.get('parse_error')]
    index = Index(sources, '')
    capsules = defaultdict(list)
    for capsule in corpus['capsules']:
        capsules[capsule['test_id']].append(capsule)
    tests, observations = {}, []
    ordered = sorted(corpus['tests'].values(), key=lambda row: (row.get('retrieval_rank') or 99999, row['id']))
    seeds = {row['id'] for row in ordered if row.get('retrieval_rank') and row['retrieval_rank'] <= top_k}
    if not seeds:
        seeds = {row['id'] for row in ordered[:top_k]}
    for record in ordered:
        try:
            test = _test(index, record, capsules[record['id']])
            tests[record['id']] = test
            for capsule in capsules[record['id']]:
                for insertion, receiver, binding in _observations(test, capsule):
                    observations.append((test, capsule, insertion, receiver, binding))
        except Unsupported as exc:
            skipped[str(exc)] += 1
    groups = defaultdict(list)
    for observation in observations:
        test, _, _, _, binding = observation
        scope = test.record.get('enclosing_scope_span')
        if not scope:
            skipped['missing_enclosing_scope'] += 1
            continue
        key = (test.source.path, scope['start_byte'], scope['end_byte'], binding.producer)
        groups[key].append(observation)
    recipient_plans = defaultdict(list)
    for group in groups.values():
        contexts = []
        for donor_observation in group:
            donor, donor_capsule, stop, _, binding = donor_observation
            operations = []
            for i in range(stop):
                try:
                    operation = _operation(index, donor, i, binding.origin)
                    if operation is not None:
                        operations.append(operation)
                except Unsupported as exc:
                    skipped[str(exc)] += 1
                    # Do not turn operations on opposite sides of an unknown
                    # dependency into an apparently contiguous source context.
                    operations.append(None)
            for start in range(len(operations)):
                if operations[start] is None:
                    continue
                for count in range(1, min(3, len(operations) - start) + 1):
                    selected = operations[start:start + count]
                    if any(operation is None for operation in selected):
                        break
                    contexts.append((donor_observation, selected))
        for recipient_observation in group:
            recipient_plans[recipient_observation[0].record['id']].append((recipient_observation, contexts))

    def proposals(plans):
        for recipient_observation, contexts in plans:
            recipient_id = recipient_observation[0].record['id']
            for donor_observation, selected in contexts:
                donor_id = donor_observation[0].record['id']
                if donor_id != recipient_id and (recipient_id in seeds or donor_id in seeds):
                    yield donor_observation, selected, recipient_observation

    # One attempt per recipient per round, starting with ranked seed tests.
    # Donor contexts are shared rather than materializing their cross product.
    turns = deque(proposals(recipient_plans[row['id']]) for row in sorted(
        ordered, key=lambda row: (row['id'] not in seeds, row.get('retrieval_rank') or 99999, row['id']))
        if row['id'] in recipient_plans)
    while turns:
        stream = turns.popleft()
        proposal = next(stream, None)
        if proposal is None:
            continue
        turns.append(stream)
        if attempts >= max_attempts:
            skipped['attempt_budget'] += 1
            return result(True)
        attempts += 1  # Count before closure rendering, deduplication, or validation.
        (donor, donor_capsule, _, _, binding), selected, (recipient, capsule, insertion, receiver, _) = proposal
        identifier = _id('state_context', donor.record['id'], [op['statement'] for op in selected],
                         capsule['id'], receiver)
        try:
            text, positions, arguments, argument_sources, alpha = _render(
                donor, selected, recipient, insertion, receiver, identifier)
            position = recipient.statements[insertion].start_byte
            key = (recipient.record['id'], capsule['id'], position, text)
            if key in seen:
                continue
            witnesses = _witness(sources, recipient, capsule, insertion, text, positions, receiver)
        except Unsupported as exc:
            skipped[str(exc)] += 1
            continue
        seen.add(key)
        source_position = dict(span(recipient.source, recipient.statements[insertion]), end_byte=position)
        source_position['end_line'] = source_position['line']
        aliases = sorted({bound.name for op in selected for _, bound in op['references'] if bound.kind == 'receiver'})
        candidates.append({'id': identifier, 'base_test_id': recipient.record['id'],
            'source_test_ids': [donor.record['id']], 'language': corpus['language'],
            'kind': 'state_context', 'rule_id': _id('state_context_rule', binding.producer,
                                                 donor.record['id'], [op['statement'] for op in selected]),
            'imports': [], 'edits': [{'span': source_position, 'before': '', 'after': text}],
            'target_capsule_id': capsule['id'], 'arg_values': arguments,
            'provenance': {'donor_capsule_id': donor_capsule['id'], 'producer_identity': binding.producer,
                'receiver_mapping': {name: receiver for name in aliases},
                'operation_spans': [span(donor.source, donor.statements[op['statement']]) for op in selected],
                'operation_count': len(selected), 'literal_binding_renames': {b.name: name for b, name in alpha.items()},
                'argument_sources': argument_sources, 'insertion_statement': span(recipient.source, recipient.statements[insertion]),
                'observation_state_witnesses': witnesses,
                'dependency_precision': 'local_may_state_with_direct_alias_mapping',
                'unproved': ['full_aliasing', 'global_and_fixture_effects', 'call_effects', 'oracle_transport'],
                'oracle_status': 'requires_observation_completion'}})
        if len(candidates) >= max_candidates:
            skipped['candidate_budget'] += 1
            return result(True)
    return result()
