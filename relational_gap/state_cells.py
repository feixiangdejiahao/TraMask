"""Bounded source action sequences before an existing receiver observation.

This adapter uses the state-region binding and byte renderer, but deliberately
does not require an effect edge in the current implementation. Such an edge can
be absent because of the defect under investigation. Constructor identity and
straight-line aliases align source actions; they do not establish a contract
for the retained oracle or the runtime feasibility of a sequence.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Source
from experimental import state_regions as regions
from experimental.semantic_transport.oracle import OracleError, Unknown, encode_value
from experimental.semantic_transport import state_contexts as state
from generic_composition.corpus import span


@dataclass(frozen=True)
class StateBudget:
    max_candidates: int = 128
    max_attempts: int = 2048
    max_steps: int = 2
    max_actions_per_group: int = 32
    top_k: int | None = None


def _round_robin(streams):
    queue = deque(iter(stream) for stream in streams)
    while queue:
        stream = queue.popleft()
        item = next(stream, None)
        if item is not None:
            queue.append(stream)
            yield item


def _rank(record):
    return record.get('retrieval_rank') or 999999, record['id']


def _encode_argument(value):
    try:
        return encode_value(value)
    except OracleError as exc:
        # Metadata limits do not invalidate an executable source expression.
        return encode_value(Unknown(f'static_argument_{exc.code}: {exc.reason}'))


def _phase_capsule(test, capsule):
    """Recover snapshot expressions omitted from a compact emitter corpus.

    Snapshots are lexical environments at each statement. Following their
    binding expressions uses the definition that existed at q's evaluation,
    including aliases, rather than the last later write to the same spelling.
    Receiver construction itself is not an observation evaluation.
    """
    observed = capsule.get('observed')
    if not observed:
        return capsule
    location = observed['span']
    node = test.nodes.get((location['start_byte'], location['end_byte']))
    if node is None:
        return capsule
    index = state._statement(test, node.start_byte, node.end_byte)
    if index is None:
        return capsule
    sources = list(capsule.get('observation_value_sources', ()))
    pending, seen = [(node, index)], set()
    while pending:
        expression, at = pending.pop()
        for reference in state._reads(expression):
            binding = test.snapshots[at].get(test.source.text(reference))
            if (binding is None or binding in seen or binding.kind == 'receiver'
                    or binding.expression is None or binding.statement < 0):
                continue
            seen.add(binding)
            sources.append(span(test.source, binding.expression))
            pending.append((binding.expression, binding.statement))
    unique = {(p['path'], p['start_byte'], p['end_byte']): p for p in sources}
    return dict(capsule, observation_value_sources=list(unique.values()))


def _action_key(action):
    region, test, operation, origin = action
    statement = test.statements[operation['statement']]
    return region.parent['id'], statement.start_byte, statement.end_byte, origin


def _action_bank(observations, index, limit, skipped):
    """Keep operation coordinates balanced across their original parent tests."""
    parents, seen = defaultdict(list), set()
    for region, test, _, stop, _, binding in observations:
        for at in range(stop):
            try:
                operation = regions._operation(index, region, test, at, binding.origin)
            except state.Unsupported as exc:
                skipped[str(exc)] += 1
                continue
            if operation is None:
                continue
            action = region, test, operation, binding.origin
            key = _action_key(action)
            if key not in seen:
                seen.add(key)
                parents[region.parent['id']].append(action)
    ordered = sorted(parents, key=lambda pid: _rank(parents[pid][0][0].parent))
    bank = []
    for action in _round_robin(parents[pid] for pid in ordered):
        if len(bank) >= limit:
            skipped['action_group_budget'] += 1
            break
        bank.append(action)
    return bank


def _sequences(actions, max_steps):
    singles = ((action,) for action in actions)
    if max_steps == 1:
        yield from singles
        return
    # Each source action gets a turn in the first position before its successor
    # changes. This avoids exhausting the pair budget on one action's partners.
    pairs = ((actions[first], actions[(first + offset) % len(actions)])
             for offset in range(1, len(actions) + 1) for first in range(len(actions)))
    yield from _round_robin((singles, pairs))


def _render_sequence(index, recipient_data, sequence, identifier):
    region, recipient, _, insertion, receiver, _ = recipient_data
    fragments, details, argument_values = [], [], []
    for number, (donor_region, donor, operation, origin) in enumerate(sequence):
        operations = [operation]
        regions._external_declarations_match(donor_region, region, operations)
        if any(not regions._builtin_available(index, region, recipient, name)
               for name in operation.get('builtin_names', ())):
            raise state.Unsupported('rhs_builtin_shadowed_at_target')
        if any(regions._external_shadowed(index, region, recipient, name)
               for name in operation['external_names']):
            raise state.Unsupported('external_callee_shadowed_at_target')
        text, _, arguments, argument_sources, alpha = regions._render(
            donor, operations, recipient, insertion, receiver,
            state._id(identifier, number))
        fragments.append(text)
        argument_values.extend(arguments)
        aliases = sorted({binding.name for _, binding in operation['references']
                          if binding.kind == 'receiver'})
        details.append({
            'source_test_id': donor_region.parent['id'],
            'source_region_id': donor.record['id'],
            'statement_span': span(donor.source, donor.statements[operation['statement']]),
            'expression_span': span(donor.source, operation['expression']) if 'expression' in operation else None,
            'source_receiver_origin': origin,
            'receiver_mapping': {name: receiver for name in aliases},
            'argument_sources': argument_sources,
            'literal_binding_renames': {bound.name: name for bound, name in alpha.items()},
            'discarded_result_binding': operation.get('discarded_binding'),
            'source_context': list(donor_region.context),
        })
    return ''.join(fragments), argument_values, details


def _validate_render(source, position, text):
    """Syntax validity is distinct from the optional current-program effect slice."""
    changed = Source(source.path,
                     (source.data[:position] + text.encode() + source.data[position:]).decode(),
                     source.language)
    if changed.root.has_error:
        raise state.Unsupported('inserted_context_parse_error')
    if source.language == 'python':
        import ast
        try:
            ast.parse(changed.code)
        except SyntaxError:
            raise state.Unsupported('inserted_context_python_parse_error') from None


def generate_state_cells(corpus, *, budget: StateBudget | None = None):
    """Return emitter candidates; never execute a subject or infer an oracle.

    Supported receivers are constructed and observed in one straight-line
    region (including an existing Python with body). Actions take source
    literals, closed literal dependencies, and aliases of that receiver.
    General branch/loop bodies, cross-region live-ins, and arbitrary call-result
    dependencies remain explicit unsupported cases in the shared scanner.
    """
    budget = budget or StateBudget()
    if (any(type(value) is not int or value < 1 for value in (
            budget.max_candidates, budget.max_attempts, budget.max_actions_per_group))
            or type(budget.max_steps) is not int or budget.max_steps not in {1, 2}
            or (budget.top_k is not None and (type(budget.top_k) is not int or budget.top_k < 1))):
        raise ValueError('State budgets must be positive integers, with max_steps at most two')
    skipped, candidates, seen, attempts = Counter(), [], set(), 0

    def result(exhausted=False):
        return {'candidates': candidates, 'skipped': dict(sorted(skipped.items())),
                'attempts': attempts, 'budget_exhausted': exhausted,
                'budget': asdict(budget), 'domain': 'scoped_state_context'}

    if corpus['language'] not in {'python', 'typescript', 'go'}:
        skipped['language_not_supported'] += 1
        return result()
    sources = [Source(path, metadata['code'], metadata.get('language', corpus['language']))
               for path, metadata in sorted(corpus['sources'].items())
               if metadata.get('complete_file', True) and not metadata.get('parse_error')]
    index = Index(sources, '')
    capsules, groups = defaultdict(list), defaultdict(list)
    for capsule in corpus.get('capsules', ()):
        if capsule.get('assertion_span'):
            capsules[capsule['test_id']].append(capsule)
    ordered = sorted(corpus['tests'].values(), key=_rank)
    seeds = {record['id'] for record in ordered[:budget.top_k]} if budget.top_k else set(corpus['tests'])
    for record in ordered:
        if record.get('parameterization_status', 'none_detected') != 'none_detected':
            skipped['parameter_rows_require_instantiation'] += 1
            continue
        unit, scope = index.units.get(record['id']), record.get('enclosing_scope_span')
        if unit is None or not scope:
            skipped['missing_source_or_enclosing_scope'] += 1
            continue
        if not capsules[record['id']]:
            skipped['no_observation_capsule'] += 1
            continue
        for region in regions._regions(unit, record, capsules[record['id']]):
            local = [q for q in capsules[record['id']] if any(
                statement.start_byte <= q['assertion_span']['start_byte']
                and q['assertion_span']['end_byte'] <= statement.end_byte for statement in region.statements)]
            if not local:
                continue
            try:
                test = regions._region_test(index, region, local)
            except state.Unsupported as exc:
                skipped[str(exc)] += 1
                continue
            for original in local:
                capsule = _phase_capsule(test, original)
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
    for observations in groups.values():
        actions = _action_bank(observations, index, budget.max_actions_per_group, skipped)
        if not actions:
            continue
        for recipient in observations:
            # A source test may donate an operation for repetition on its own
            # receiver. No runtime distinctness is inferred from test identity.
            plans[recipient[0].parent['id']].append((recipient, actions))

    def recipient_stream(recipient, actions):
        for sequence in _sequences(actions, budget.max_steps):
            if recipient[0].parent['id'] not in seeds and not any(a[0].parent['id'] in seeds for a in sequence):
                continue
            yield recipient, sequence

    streams = [_round_robin(recipient_stream(recipient, actions) for recipient, actions in plans[row['id']])
               for row in sorted(ordered, key=lambda record: (record['id'] not in seeds, *_rank(record)))
               if row['id'] in plans]
    for recipient_data, sequence in _round_robin(streams):
        if attempts >= budget.max_attempts:
            skipped['attempt_budget'] += 1
            return result(True)
        attempts += 1
        region, recipient, capsule, insertion, receiver, binding = recipient_data
        identifier = state._id('relational_state_cell', capsule['id'], receiver,
                               [_action_key(action) for action in sequence])
        try:
            text, arguments, actions = _render_sequence(index, recipient_data, sequence, identifier)
            position = recipient.statements[insertion].start_byte
            key = region.parent['id'], capsule['id'], position, text
            if key in seen:
                continue
            _validate_render(recipient.source, position, text)
        except state.Unsupported as exc:
            skipped[str(exc)] += 1
            continue
        seen.add(key)
        location = dict(span(recipient.source, recipient.statements[insertion]), end_byte=position)
        location['end_line'] = location['line']
        source_ids = sorted({action['source_test_id'] for action in actions})
        candidates.append({
            'id': identifier, 'base_test_id': region.parent['id'], 'source_test_ids': source_ids,
            'language': corpus['language'], 'kind': 'scoped_state_context', 'imports': [],
            'edits': [{'span': location, 'before': '', 'after': text}],
            'target_capsule_id': capsule['id'], 'arg_values': [_encode_argument(value) for value in arguments],
            'relation': {
                'domain': 'scoped_state_context',
                'cell': {'receiver_identity': 'same_existing_receiver', 'operation_count': len(actions),
                         'operation_order': [action['statement_span'] for action in actions],
                         'phase': 'before_existing_observation_evaluation', 'observation_id': capsule['id']},
                'status': 'statically_constructed_runtime_unconfirmed',
                'binding_precision': 'same_source_producer_and_lexical_scope_with_straight_line_aliases',
                'type_status': 'source_producer_alignment_runtime_type_unconfirmed',
                'state_effect_status': 'unknown_not_required_for_materialization',
                'applicability': 'unknown_requires_independent_admission',
            },
            'oracle': {'mode': 'retain_all', 'source_test_id': region.parent['id'],
                       'assertion_ids': [q['id'] for q in capsules[region.parent['id']]],
                       'target_assertion_id': capsule['id'],
                       'applicability': 'requires_independent_admission',
                       'basis': 'existing_observer_preserved_contract_for_composed_state_unknown'},
            'provenance': {
                'frontend': 'state_regions_binding_and_renderer',
                'source_spans': [action['statement_span'] for action in actions],
                'producer_identity': binding.producer, 'recipient_receiver_origin': binding.origin,
                'recipient_receiver': receiver, 'actions': actions,
                'operation_count': len(actions),
                'insertion_statement': span(recipient.source, recipient.statements[insertion]),
                'observation_span': capsule['observed']['span'],
                'assertion_span': capsule['assertion_span'],
                'recipient_region': {'id': recipient.record['id'], 'context': list(region.context)},
                'phase_precision': 'source_expression_and_straight_line_definition_chain',
                'dependency_precision': 'closed_source_literals_replayed_per_action',
                'observation_state_witnesses': [],
                'unproved': ['call_effects', 'runtime_types', 'external_aliases', 'context_manager_effects',
                             'action_preconditions', 'literal_mutability', 'oracle_transport'],
            },
            'selection': {'base_retrieval_rank': region.parent.get('retrieval_rank'),
                          'schedule': 'parent_then_observation_then_sequence_length_round_robin'},
        })
        if len(candidates) >= budget.max_candidates:
            skipped['candidate_budget'] += 1
            return result(True)
    return result()
