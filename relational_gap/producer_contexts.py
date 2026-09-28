"""Source-owned producing slices for an existing receiver call argument.

The adapter copies bounded straight-line setup, including may-state operations
on derived locals. It does not invent calls, numeric coordinates or expected
values. Source receiver/type alignment is a hypothesis, not a state contract.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field

from anchor_retrieval.syntax import CALLS, Source, child, walk
from experimental.semantic_transport import state_contexts as syntax
from generic_composition.corpus import expression, span
from generic_composition.emitter import _unit_node
from generic_composition.engine import stable_id
from .frontend import is_operation_argument
from .resource_roots import ResourceRoots
from .sequence_cells import _observers
from .transforms import _transfer_bindings


@dataclass(frozen=True)
class ProducerBudget:
    max_candidates: int = 128
    max_attempts: int = 2048
    max_statements: int = 12
    max_slice_bytes: int = 5000
    max_donors_per_slot: int = 24
    max_observations: int = 2


class Unsupported(ValueError):
    pass


@dataclass(eq=False)
class Binding:
    name: str
    statement: int
    target: object = None
    value: object = None
    dependencies: tuple = ()
    roots: frozenset = frozenset()
    parameter: dict | None = None


@dataclass
class Test:
    record: dict
    source: Source
    node: object
    statements: list
    snapshots: list = field(default_factory=list)
    definitions: dict = field(default_factory=dict)
    root_bindings: dict = field(default_factory=dict)
    observations: dict = field(default_factory=dict)


def _pos(row):
    location = row.get('span', row)
    return location['path'], location['start_byte'], location['end_byte']


def _round_robin(streams):
    queue = deque(iter(stream) for stream in streams)
    while queue:
        stream = queue.popleft()
        item = next(stream, None)
        if item is not None:
            queue.append(stream)
            yield item


def _refs(test, node, environment, *, target=None):
    return [(reference, environment.get(test.source.text(reference))) for reference in syntax._reads(node)
            if target is None or not syntax._inside(target, reference)]


def _test(record, source, frontend_test, roots, observations):
    node = _unit_node(source, record)
    body = child(node, 'body')
    if body is None:
        raise Unsupported('producer_test_body_missing')
    container = next((n for n in body.named_children if n.type == 'statement_list'), body)
    statements = [n for n in container.named_children if n.type != 'comment']
    result = Test(record, source, node, statements)
    environment = {p['name']: Binding(p['name'], -1, parameter=p)
                   for p in frontend_test.get('parameters', ()) if p.get('name')}
    creator_targets = {_pos(binding['target']): (key, binding) for key, (binding, _) in roots.root_bindings.items()
                       if binding['test_id'] == record['id']}
    for index, statement in enumerate(statements):
        result.snapshots.append(dict(environment))
        result.observations[index] = [q for q in observations if q.get('assertion_span')
            and statement.start_byte <= q['assertion_span']['start_byte']
            and q['assertion_span']['end_byte'] <= statement.end_byte]
        assignment = syntax._assignment(statement)
        if not assignment or assignment[0].type != 'identifier':
            continue
        target, value = assignment
        dependencies = tuple(dict.fromkeys(binding for _, binding in _refs(result, value, environment) if binding))
        root_ids = frozenset(root for binding in dependencies for root in binding.roots)
        creator = creator_targets.get((source.path, target.start_byte, target.end_byte))
        if not root_ids and creator:
            root_ids = frozenset({creator[0]})
        binding = Binding(source.text(target), index, target, value, dependencies, root_ids)
        result.definitions[index] = binding
        environment[binding.name] = binding
        if creator and root_ids == {creator[0]}:
            result.root_bindings[creator[0]] = binding
    return result


def _statement(test, call):
    location = call['span']
    return next((i for i, node in enumerate(test.statements)
                 if node.start_byte <= location['start_byte'] and location['end_byte'] <= node.end_byte), None)


def _identity(call):
    identity = call.get('callee_identity') or {}
    return identity.get('canonical') or identity.get('scope_key') or (call['span']['path'] + '::' + call['callee'])


def _port_key(call, argument, creator):
    targets = sorted(t['function_id'] for t in call.get('targets', ()) if t.get('resolved'))
    # The same source producer plus the same receiver member is a bounded
    # fallback when source dispatch is unresolved. It remains explicitly unknown.
    callee = ('resolved_source', tuple(targets)) if targets else ('source_receiver_member', call['callee'].rsplit('.', 1)[-1])
    formal = sorted({b['parameter'] for b in call.get('argument_bindings', ())
                     if b['slot'] == argument['slot'] and b.get('parameter')})
    slot = ('formal', tuple(formal)) if formal else ('source_slot', argument.get('keyword'), argument['slot'])
    return _identity(creator), callee, slot


def _ports(test, calls, roots):
    for call in calls:
        if call.get('contexts') or not call.get('receiver') or call['receiver'].get('kind') != 'identifier':
            continue
        associations = [fact for fact in roots.associations(call) if fact['relation'] == 'receiver_reference']
        if len(associations) != 1:
            continue
        fact = associations[0]
        root = test.root_bindings.get(fact['root_id'])
        index = _statement(test, call)
        if root is None or index is None or root.statement >= index:
            continue
        creator = roots.calls[fact['creator_call_id']]
        for argument in call.get('arguments', ()):
            if argument.get('spread') or not is_operation_argument(call, argument['slot']):
                continue
            yield {'test': test, 'call': call, 'argument': argument, 'statement': index,
                   'root': root, 'root_id': fact['root_id'], 'root_fact': fact,
                   'key': _port_key(call, argument, creator), 'creator': creator}


def _pure_assertion(test, statement, environment):
    if statement.type != 'assert_statement':
        return False
    # Absence of calls alone is not purity: a property, comparison or truth
    # conversion can execute user code. Limit omission to source-closed
    # primitive literal expressions and local aliases of such expressions.
    allowed = {'assert_statement', 'comparison_operator', 'boolean_operator', 'not_operator',
               'unary_operator', 'binary_operator', 'parenthesized_expression', 'identifier',
               'integer', 'float', 'string', 'string_start', 'string_content', 'string_end',
               'true', 'false', 'none'}
    if any(node.type not in allowed for node in walk(statement)):
        return False
    def closed(binding, seen):
        if binding is None or binding in seen or binding.value is None or binding.roots:
            return False
        try:
            value = ast.literal_eval(test.source.text(binding.value))
            return type(value) in {int, float, bool, str, type(None)}
        except (ValueError, SyntaxError):
            return (binding.value.type == 'identifier' and len(binding.dependencies) == 1
                    and closed(binding.dependencies[0], seen | {binding}))
    return all(closed(environment.get(test.source.text(reference)), set()) for reference in syntax._reads(statement))


def _slice(port, budget):
    test, root, stop = port['test'], port['root'], port['statement']
    argument = port['argument']
    if argument.get('kind') != 'identifier':
        raise Unsupported('producer_argument_not_local_identifier')
    produced = test.snapshots[stop].get(argument['text'])
    if produced is None or produced is root or produced.roots != {port['root_id']}:
        raise Unsupported('producer_argument_not_derived_from_single_root')
    selected, skipped_assertions, guards = set(), [], set()
    for index in range(root.statement + 1, stop):
        statement = test.statements[index]
        if any(n.type in syntax._CONTROL | syntax._NESTED | {'await', 'await_expression', 'yield'} for n in walk(statement)):
            raise Unsupported('producer_control_or_nested_scope_unknown')
        observations = test.observations[index]
        if observations and not all(q.get('predicate') == 'NoError' and q.get('adapter') == 'direct' for q in observations):
            if _pure_assertion(test, statement, test.snapshots[index]):
                skipped_assertions.append(index)
                continue
            raise Unsupported('producer_ordinary_assertion_effect_unknown')
        definition = test.definitions.get(index)
        refs = _refs(test, statement, test.snapshots[index], target=definition.target if definition else None)
        if any(binding and port['root_id'] in binding.roots for _, binding in refs):
            selected.add(index)
            if observations:
                guards.add(index)
    selected.add(produced.statement)
    required, externals, parameters = set(), set(), set()
    pending = list(selected)
    processed = set()
    while pending:
        index = pending.pop()
        if index in processed:
            continue
        processed.add(index)
        if index < 0 or index >= stop:
            raise Unsupported('producer_dependency_not_before_target_call')
        statement = test.statements[index]
        if any(n.type in syntax._CONTROL | syntax._NESTED for n in walk(statement)):
            raise Unsupported('producer_dependency_control_unknown')
        definition = test.definitions.get(index)
        if syntax._assignment(statement) and definition is None:
            target, _ = syntax._assignment(statement)
            if target.type not in syntax.ATTRS | syntax._INDEX:
                raise Unsupported('producer_multiple_assignment_unsupported')
        if definition:
            required.add(definition)
            # A Go assignment needs its original declaration in the copied
            # closure. Keep that initializer and reuse one hygienic variable
            # across source versions rather than inventing an undeclared name.
            if test.source.language == 'go' and statement.type == 'assignment_statement':
                previous = test.snapshots[index].get(definition.name)
                if previous is None or previous.parameter or previous is root:
                    raise Unsupported('producer_go_assignment_declaration_unknown')
                required.add(previous)
                if previous.statement not in selected:
                    selected.add(previous.statement)
                    pending.append(previous.statement)
        for reference, binding in _refs(test, statement, test.snapshots[index], target=definition.target if definition else None):
            if binding is root:
                continue
            if binding is None:
                externals.add(test.source.text(reference))
                continue
            if binding.parameter:
                if index not in guards:
                    raise Unsupported('producer_parameter_livein_outside_setup_guard')
                parameters.add(binding)
                continue
            if binding.roots - {port['root_id']}:
                raise Unsupported('producer_dependency_has_independent_resource_root')
            if binding.statement == root.statement:
                raise Unsupported('producer_root_binding_not_unique')
            required.add(binding)
            if binding.statement not in selected:
                selected.add(binding.statement)
                pending.append(binding.statement)
    if not selected or not any(any(n.type in CALLS for n in walk(test.statements[i])) for i in selected):
        raise Unsupported('producer_slice_has_no_source_operation')
    # Source operations on dependency locals may mutate their value without
    # creating a data-flow edge. Never silently omit an intervening such action.
    dependency_bindings = required | {root}
    for index in range(min(selected), stop):
        if index in selected or index in skipped_assertions:
            continue
        statement = test.statements[index]
        refs = _refs(test, statement, test.snapshots[index])
        if any(binding in dependency_bindings for _, binding in refs) and any(n.type in CALLS for n in walk(statement)):
            raise Unsupported('producer_dependency_state_action_outside_closed_slice')
    ordered = sorted(selected)
    if len(ordered) > budget.max_statements or sum(len(test.source.text(test.statements[i]).encode()) for i in ordered) > budget.max_slice_bytes:
        raise Unsupported('producer_slice_budget')
    return dict(port, selected=ordered, produced=produced, locals=required, externals=externals,
                parameters=parameters, guard_indices=sorted(guards), skipped_assertions=skipped_assertions)


def _replace(source, node, edits):
    data = source.data[node.start_byte:node.end_byte]
    for start, end, text in sorted(set(edits), reverse=True):
        data = data[:start-node.start_byte] + text.encode() + data[end-node.start_byte:]
    return data.decode()


def _render(corpus, sources, donor, recipient, identifier):
    source, target = donor['test'], recipient['test']
    position = target.statements[recipient['statement']].start_byte
    source_root, target_name = donor['root'], recipient['call']['receiver']['text']
    occupied = {target.source.text(n) for n in walk(target.node) if n.type == 'identifier'}
    names = {source_root: target_name}
    go_local_names = {}
    for number, local in enumerate(sorted(donor['locals'], key=lambda b: (b.statement, b.name))):
        if source.source.language == 'go' and local.name in go_local_names:
            names[local] = go_local_names[local.name]
            continue
        name = 'rg_producer_' + identifier[:8] + '_' + str(number)
        while name in occupied:
            name += '_'
        occupied.add(name)
        names[local] = name
        go_local_names[local.name] = name
    parameter_map = {}
    for parameter in donor['parameters']:
        annotation = parameter.parameter.get('type')
        candidates = [b for b in target.snapshots[recipient['statement']].values()
                      if b.parameter and annotation and b.parameter.get('type') == annotation]
        if len(candidates) != 1 or source.source.path != target.source.path:
            raise Unsupported('producer_setup_guard_parameter_binding_unknown')
        names[parameter] = candidates[0].name
        parameter_map[parameter.name] = candidates[0].name
    origin = {'test_id': source.record['id'], 'span': span(source.source, source.statements[donor['selected'][0]]),
              'free_identifiers': sorted(donor['externals'])}
    destination = {'test_id': target.record['id'], 'span': span(target.source, target.statements[recipient['statement']])}
    imports, unknowns = _transfer_bindings(corpus, sources, origin, destination)
    if unknowns:
        raise Unsupported('producer_external_binding_unknown:' + ','.join(unknowns))
    line_start = target.source.data.rfind(b'\n', 0, position) + 1
    prefix = target.source.data[line_start:position].decode()
    if prefix.strip() and target.source.language == 'python':
        raise Unsupported('producer_inline_python_suite_unknown')
    indent = prefix if not prefix.strip() else '\t'
    rendered = []
    for index in donor['selected']:
        statement = source.statements[index]
        definition = source.definitions.get(index)
        edits = []
        if definition:
            edits.append((definition.target.start_byte, definition.target.end_byte, names[definition]))
        for reference, binding in _refs(source, statement, source.snapshots[index], target=definition.target if definition else None):
            if binding:
                if binding not in names:
                    raise Unsupported('producer_local_binding_not_closed')
                edits.append((reference.start_byte, reference.end_byte, names[binding]))
        text = _replace(source.source, statement, edits)
        lines = text.splitlines()
        column = statement.start_point.column
        normalized = lines[0] + ''.join('\n' + indent + line[min(column, len(line)-len(line.lstrip())):] for line in lines[1:])
        rendered.append(normalized + '\n' + indent)
    insertion = ''.join(rendered)
    argument = recipient['argument']
    edits = [{'span': dict(span(target.source, target.statements[recipient['statement']]), end_byte=position),
              'before': '', 'after': insertion, 'role': 'source_producer_context'},
             {'span': argument['span'], 'before': argument['text'], 'after': names[donor['produced']],
              'role': 'source_produced_argument'}]
    data = target.source.data
    for edit in sorted(edits, key=lambda e: (e['span']['start_byte'], e['span']['end_byte']), reverse=True):
        a, b = edit['span']['start_byte'], edit['span']['end_byte']
        if data[a:b].decode() != edit['before']:
            raise Unsupported('producer_edit_source_mismatch')
        data = data[:a] + edit['after'].encode() + data[b:]
    changed = Source(target.source.path, data.decode(), target.source.language)
    if changed.root.has_error:
        raise Unsupported('producer_context_parse_error')
    if target.source.language == 'python':
        ast.parse(changed.code)
    return edits, imports, {b.name + ':' + str(b.statement): name for b, name in names.items()}, parameter_map


def generate_producer_contexts(corpus, frontend, *, budget: ProducerBudget | None = None):
    budget = budget or ProducerBudget()
    if any(type(value) is not int or value < 1 for value in asdict(budget).values()):
        raise ValueError('Producer budgets must be positive integers')
    skipped, candidates, attempts, seen = Counter(), [], 0, set()
    def result(exhausted=False):
        return {'domain': 'source_producer_context', 'candidates': candidates, 'attempts': attempts,
                'skipped': dict(sorted(skipped.items())), 'budget': asdict(budget), 'budget_exhausted': exhausted}
    if corpus['language'] not in {'python', 'go'}:
        skipped['producer_language_unsupported'] += 1
        return result()
    sources = {path: Source(path, row['code'], row.get('language', corpus['language']))
               for path, row in corpus['sources'].items() if row.get('complete_file', True) and not row.get('parse_error')}
    roots = ResourceRoots(frontend, sources)
    frontend_tests = {row['id']: row for row in frontend.get('tests', ())}
    calls, observations, capsules = defaultdict(list), defaultdict(list), defaultdict(list)
    for call in frontend.get('calls', ()):
        calls[call['test_id']].append(call)
    for row in frontend.get('observations', ()):
        observations[row['test_id']].append(row)
    for row in corpus.get('capsules', ()):
        if row.get('assertion_span'):
            capsules[row['test_id']].append(row)
    ports, donors = defaultdict(list), defaultdict(list)
    for record in sorted(corpus['tests'].values(), key=lambda r: (r.get('retrieval_rank') or 10**9, r['id'])):
        if record.get('parameterization_status', 'none_detected') != 'none_detected':
            skipped['producer_parameter_rows_unknown'] += 1
            continue
        if record['id'] not in frontend_tests or record['span']['path'] not in sources:
            continue
        try:
            test = _test(record, sources[record['span']['path']], frontend_tests[record['id']], roots, observations[record['id']])
        except (Unsupported, ValueError) as error:
            skipped[str(error)] += 1
            continue
        for port in _ports(test, calls[record['id']], roots):
            ports[port['key']].append(port)
            if port['argument'].get('kind') != 'identifier':
                continue
            try:
                donor = _slice(port, budget)
                if len(donors[port['key']]) < budget.max_donors_per_slot:
                    donors[port['key']].append(donor)
                else:
                    skipped['producer_donor_slot_budget'] += 1
            except Unsupported as error:
                skipped[str(error)] += 1
    parents = defaultdict(list)
    for key, donor_rows in donors.items():
        for recipient in ports[key]:
            # Replacing a closed actual preserves the original call's other
            # argument evaluations. Effectful actuals need a different adapter.
            if not recipient['argument'].get('literal_known'):
                continue
            triple = {'test_id': recipient['test'].record['id'], 'members': [{'call': recipient['call']}]}
            qs = _observers(triple, capsules, {b['id']: b for b in frontend.get('bindings', ())}, budget)
            for donor in donor_rows:
                for q in qs:
                    parents[recipient['test'].record['id']].append((donor, recipient, q))
    order = sorted(parents, key=lambda key: (corpus['tests'][key].get('retrieval_rank') or 10**9, key))
    for donor, recipient, q in _round_robin(parents[key] for key in order):
        if attempts >= budget.max_attempts:
            skipped['producer_attempt_budget'] += 1
            return result(True)
        attempts += 1
        identifier = stable_id('producer_context', donor['call']['id'], donor['argument']['slot'],
                               recipient['call']['id'], recipient['argument']['slot'], q['id'])
        if identifier in seen:
            continue
        try:
            edits, imports, renames, parameter_map = _render(corpus, sources, donor, recipient, identifier)
        except (Unsupported, SyntaxError) as error:
            skipped[str(error)] += 1
            continue
        seen.add(identifier)
        source, target = donor['test'], recipient['test']
        candidates.append({'id': identifier, 'base_test_id': target.record['id'],
            'source_test_ids': sorted({source.record['id'], target.record['id']}), 'language': corpus['language'],
            'kind': 'source_producer_context', 'edits': edits, 'imports': imports,
            'source_observation_id': q['id'], 'target_capsule_id': q['id'],
            'relation': {'domain': 'source_producer_context', 'cell': 'source_derived_value_on_existing_receiver',
                         'source_call_id': donor['call']['id'], 'recipient_call_id': recipient['call']['id'],
                         'argument_slot': recipient['argument']['slot'], 'alignment': list(recipient['key']),
                         'state_effect_status': 'unknown_source_may_state_prefix',
                         'applicability': 'unknown_requires_independent_admission',
                         'status': 'statically_constructed_runtime_unconfirmed'},
            'oracle': {'mode': 'retain_all', 'source_test_id': target.record['id'], 'assertion_ids': [q['id']],
                       'basis': None, 'applicability': 'requires_independent_admission'},
            'provenance': {'source_spans': [span(source.source, source.statements[i]) for i in donor['selected']],
                           'source_argument_span': donor['argument']['span'], 'recipient_argument_span': recipient['argument']['span'],
                           'source_root_span': span(source.source, source.statements[donor['root'].statement]),
                           'recipient_root_span': span(target.source, target.statements[recipient['root'].statement]),
                           'receiver_mapping': {donor['root'].name: recipient['call']['receiver']['text']},
                           'local_binding_renames': renames, 'setup_parameter_mapping': parameter_map,
                           'source_setup_guard_spans': [span(source.source, source.statements[i]) for i in donor['guard_indices']],
                           'source_setup_guard_count': len(donor['guard_indices']),
                           'omitted_pure_assertion_spans': [span(source.source, source.statements[i]) for i in donor['skipped_assertions']],
                           'source_observation_span': q['assertion_span'],
                           'phase': 'before_recipient_argument_evaluation; original_q_retained',
                           'unproved': ['runtime_receiver_types', 'call_effects', 'action_preconditions', 'oracle_transport']},
            'selection': {'base_retrieval_rank': target.record.get('retrieval_rank'),
                          'schedule': 'recipient_parent_then_source_slice_round_robin'}})
        if len(candidates) >= budget.max_candidates:
            skipped['producer_candidate_budget'] += 1
            return result(True)
    return result()
