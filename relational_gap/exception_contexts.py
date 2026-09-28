"""Borrow a source exception check while observing the recipient's resource.

The source supplies the exception type/matcher and one closed input. The
recipient supplies its constructor, invocation, and following observation q.
No exception behavior, cleanup effect, or oracle applicability is inferred from
the current implementation. This module never executes subject expressions.
"""
from __future__ import annotations

import ast
import builtins
from collections import Counter, defaultdict, deque
import copy
from dataclasses import asdict, dataclass

from anchor_retrieval.syntax import Source
from generic_composition.engine import stable_id


@dataclass(frozen=True)
class ExceptionBudget:
    max_candidates: int = 128
    max_attempts: int = 4096
    max_donors: int = 128
    max_inputs_per_pair: int = 12
    max_observations_per_call: int = 8


class Unsupported(ValueError):
    pass


def _pos(position):
    return position['path'], position['start_byte'], position['end_byte']


def _round_robin(streams):
    queue = deque(iter(stream) for stream in streams)
    while queue:
        stream = queue.popleft()
        item = next(stream, None)
        if item is not None:
            queue.append(stream)
            yield item


class _Kernel:
    def __init__(self, corpus, frontend):
        self.corpus, self.frontend = corpus, frontend
        self.sources, self.modules, self.nodes, self.parents, self.offsets = {}, {}, {}, {}, {}
        self.bindings, self.calls, self.observations = defaultdict(list), defaultdict(list), defaultdict(list)
        for path, metadata in corpus['sources'].items():
            if metadata.get('parse_error') or not metadata.get('complete_file', True):
                continue
            source = self.sources[path] = Source(path, metadata['code'], 'python')
            try:
                module = ast.parse(source.code)
            except SyntaxError:
                continue
            self.modules[path] = module
            offsets, total = [], 0
            for line in source.data.splitlines(keepends=True):
                offsets.append(total)
                total += len(line)
            self.offsets[path] = offsets
            lookup = defaultdict(list)
            for node in ast.walk(module):
                if hasattr(node, 'lineno'):
                    lookup[self.range(path, node)].append(node)
                for child in ast.iter_child_nodes(node):
                    self.parents[id(child)] = node
            self.nodes[path] = lookup
        for binding in frontend.get('bindings', ()):
            self.bindings[binding['test_id']].append(binding)
        for call in frontend.get('calls', ()):
            self.calls[call['test_id']].append(call)
        for observation in corpus.get('capsules', ()):
            self.observations[observation['test_id']].append(observation)

    def range(self, path, node):
        offsets = self.offsets[path]
        return offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset

    def span(self, path, node):
        start, end = self.range(path, node)
        return {'path': path, 'start_byte': start, 'end_byte': end,
                'line': node.lineno, 'end_line': node.end_lineno}

    def node(self, position, kinds=ast.AST):
        return next((node for node in self.nodes.get(position['path'], {}).get(
            (position['start_byte'], position['end_byte']), ()) if isinstance(node, kinds)), None)

    def text(self, position):
        return self.sources[position['path']].data[position['start_byte']:position['end_byte']].decode()

    def call_at(self, test_id, position):
        return next((call for call in self.calls[test_id] if _pos(call['span']) == _pos(position)), None)

    def binding(self, test_id, name, at):
        records = [b for b in self.bindings[test_id] if b.get('simple_name') and b['name'] == name
                   and b['definition_end'] <= at]
        if not records:
            return None
        binding = max(records, key=lambda b: b['definition_end'])
        # Conditional/loop writes do not identify one lexical value. A with
        # region is supported only when its declaration dominates the read.
        if any(c.get('kind') not in {'with_statement', 'with', 'async_with_statement'} for c in binding.get('contexts', ())):
            return None
        path = binding['span']['path']
        declaration = self.node(binding['span'], (ast.Assign, ast.AnnAssign))
        owner = self.parents.get(id(declaration))
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.With, ast.AsyncWith)):
            return None
        lo, hi = self.range(path, owner)
        if not lo <= at < hi:
            return None
        return binding

    def origin(self, test_id, name, at, seen=()):
        binding = self.binding(test_id, name, at)
        if binding is None or binding['id'] in seen or len(seen) >= 32:
            return None
        value = self.node(binding['value']['span'])
        if isinstance(value, ast.Name):
            return self.origin(test_id, value.id, binding['span']['start_byte'], (*seen, binding['id']))
        if isinstance(value, ast.Call):
            constructor = self.call_at(test_id, binding['value']['span'])
            if constructor is not None:
                return {'binding': binding, 'constructor': constructor,
                        'identity': _pos(constructor['span'])}
        return None

    def closed(self, test_id, position, seen=()):
        node = self.node(position)
        if node is None:
            raise Unsupported('closed_input_node_missing')
        try:
            ast.literal_eval(node)
            return {'text': self.text(position), 'span': position, 'binding_path': []}
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            pass
        if isinstance(node, ast.Name) and len(seen) < 32:
            binding = self.binding(test_id, node.id, position['start_byte'])
            if binding is not None and binding['id'] not in seen:
                result = self.closed(test_id, binding['value']['span'], (*seen, binding['id']))
                return dict(result, binding_path=[binding['span'], *result['binding_path']])
        raise Unsupported('input_expression_not_closed_literal')

    def observed_origins(self, test_id, capsule):
        """Keep the read's evaluation phase when q asserts a saved local value."""
        observed = capsule.get('observed')
        if not observed:
            return {}
        pending, seen, result = [observed['span']], set(), defaultdict(list)
        while pending:
            position = pending.pop()
            if _pos(position) in seen:
                continue
            seen.add(_pos(position))
            node = self.node(position)
            if node is None:
                continue
            for reference in ast.walk(node):
                if not isinstance(reference, ast.Name) or not isinstance(reference.ctx, ast.Load):
                    continue
                reference_span = self.span(position['path'], reference)
                origin = self.origin(test_id, reference.id, reference_span['start_byte'])
                if origin is not None:
                    result[origin['identity']].append(position)
                binding = self.binding(test_id, reference.id, reference_span['start_byte'])
                if binding is not None:
                    rhs = self.node(binding['value']['span'])
                    # Receiver creation is setup, not an earlier evaluation of
                    # q. Calls through another receiver may be saved snapshots.
                    if origin is None or isinstance(rhs, ast.Call) and isinstance(rhs.func, ast.Attribute):
                        pending.append(binding['value']['span'])
        return result


def _simple_invocation(kernel, test_id, statement):
    call = statement.value if isinstance(statement, ast.Expr) else None
    if isinstance(statement, ast.Assert):
        value = statement.test
        if isinstance(value, ast.Call):
            call = value
        elif isinstance(value, ast.Compare) and len(value.ops) == len(value.comparators) == 1:
            operands = [value.left, value.comparators[0]]
            found = [operand for operand in operands if isinstance(operand, ast.Call)]
            if len(found) == 1:
                call = found[0]
                other = next(operand for operand in operands if operand is not call)
                path = kernel.corpus['tests'][test_id]['span']['path']
                kernel.closed(test_id, kernel.span(path, other))
        if statement.msg is not None:
            path = kernel.corpus['tests'][test_id]['span']['path']
            kernel.closed(test_id, kernel.span(path, statement.msg))
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
        raise Unsupported('invocation_not_direct_receiver_call_or_simple_assert')
    path = kernel.corpus['tests'][test_id]['span']['path']
    record = kernel.call_at(test_id, kernel.span(path, call))
    if record is None:
        raise Unsupported('invocation_frontend_call_missing')
    origin = kernel.origin(test_id, call.func.value.id, record['span']['start_byte'])
    if origin is None:
        raise Unsupported('receiver_constructor_or_alias_not_recovered')
    return {'call': record, 'node': call, 'statement': statement, 'receiver': call.func.value.id,
            'origin': origin, 'test_id': test_id}


def _same_callee(kernel, left, right):
    shared = {t['function_id'] for t in left.get('targets', ())} & {t['function_id'] for t in right.get('targets', ())}
    if shared:
        resolved = all(any(t['function_id'] in shared and t.get('resolved') for t in call.get('targets', ()))
                       for call in (left, right))
        return 'resolved_source_target' if resolved else 'source_target_hypothesis'
    a, b = left.get('callee_identity') or {}, right.get('callee_identity') or {}
    if a.get('canonical') and a['canonical'] == b.get('canonical'):
        return 'source_canonical_identity'
    if a.get('scope_key') and a['scope_key'] == b.get('scope_key'):
        return 'source_scoped_callee_hypothesis'
    lt, rt = (kernel.corpus['tests'][c['test_id']] for c in (left, right))
    if (left['callee'] == right['callee'] and left['span']['path'] == right['span']['path']
            and lt.get('enclosing_scope_span') == rt.get('enclosing_scope_span')):
        return 'same_callee_spelling_in_source_scope'
    return None


def _argument_pairs(left, right):
    for source in left.get('arguments', ()):
        if source.get('spread'):
            continue
        for target in right.get('arguments', ()):
            if target.get('spread'):
                continue
            source_bindings = [b for b in left.get('argument_bindings', ()) if b['slot'] == source['slot']
                               and b.get('binding_status') == 'direct_actual_formal']
            target_bindings = [b for b in right.get('argument_bindings', ()) if b['slot'] == target['slot']
                               and b.get('binding_status') == 'direct_actual_formal']
            pairs = [(a, b) for a in source_bindings for b in target_bindings
                     if (a['function_id'], a['parameter_index']) == (b['function_id'], b['parameter_index'])]
            if pairs:
                yield source, target, {'status': 'source_actual_formal', 'source': pairs[0][0], 'target': pairs[0][1]}
            elif source.get('keyword') == target.get('keyword') and (
                    source.get('keyword') is not None or source.get('positional_index', source['slot']) == target.get('positional_index', target['slot'])):
                yield source, target, {'status': 'same_callee_syntactic_argument_coordinate',
                                      'source_slot': source['slot'], 'target_slot': target['slot']}


def _donors(kernel, ordered, skipped):
    for test_id in ordered:
        record = kernel.corpus['tests'][test_id]
        path = record['span']['path']
        function = kernel.node(record.get('definition_span', record['span']), (ast.FunctionDef, ast.AsyncFunctionDef))
        if function is None:
            continue
        proven = {_pos(q['assertion_span']) for q in kernel.observations[test_id]
                  if q.get('predicate') == 'raises' and q.get('adapter') == 'pytest_raises'}
        for context in ast.walk(function):
            if not isinstance(context, (ast.With, ast.Try)):
                continue
            if isinstance(context, ast.With):
                if len(context.items) != 1 or _pos(kernel.span(path, context)) not in proven:
                    continue
                kind = 'source_pytest_raises'
            else:
                if not context.handlers or any(h.type is None for h in context.handlers) or context.finalbody:
                    skipped['try_requires_typed_handlers_and_no_donor_finally'] += 1
                    continue
                if any(not isinstance(n, (ast.Assert, ast.Pass)) for h in context.handlers for n in h.body):
                    skipped['exception_handler_not_assertion_or_pass'] += 1
                    continue
                if any(not isinstance(n, (ast.Assert, ast.Pass, ast.Raise, ast.Expr)) for n in context.orelse):
                    skipped['exception_else_has_control_transfer_or_setup'] += 1
                    continue
                kind = 'source_typed_try_except'
            if len(context.body) != 1:
                skipped['exception_body_not_single_invocation'] += 1
                continue
            try:
                donor = _simple_invocation(kernel, test_id, context.body[0])
            except Unsupported as exc:
                skipped[str(exc)] += 1
                continue
            yield dict(donor, context=context, context_kind=kind)


def _close_context(kernel, donor, recipient, identifier):
    """Preserve the donor matcher/check, closing only source lexical values."""
    from .transforms import _transfer_bindings

    context = copy.deepcopy(donor['context'])
    context.body = [ast.Pass()]
    occupied = {n.id for module in kernel.modules.values() for n in ast.walk(module) if isinstance(n, ast.Name)}
    local = {}
    if isinstance(context, ast.With):
        target = context.items[0].optional_vars
        if target is not None:
            if not isinstance(target, ast.Name):
                raise Unsupported('exception_capture_not_simple_name')
            local[target.id] = target.id
    else:
        local.update({h.name: h.name for h in context.handlers if h.name})
    for index, name in enumerate(local):
        fresh = 'gc_exc_' + identifier[:8] + '_' + str(index)
        while fresh in occupied:
            fresh += '_'
        local[name] = fresh
        occupied.add(fresh)
    if isinstance(context, ast.Try):
        for handler in context.handlers:
            if handler.name:
                handler.name = local[handler.name]
    source_path = donor['call']['span']['path']
    recipient_path = recipient['call']['span']['path']
    globals_, dependencies = set(), []
    kernel_ = kernel

    class Close(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id in local:
                return ast.copy_location(ast.Name(id=local[node.id], ctx=node.ctx), node)
            if not isinstance(node.ctx, ast.Load):
                return node
            at = kernel_.span(source_path, node)['start_byte']
            origin = kernel_.origin(donor['test_id'], node.id, at)
            if origin is not None and origin['identity'] == donor['origin']['identity']:
                return ast.copy_location(ast.Name(id=recipient['receiver'], ctx=ast.Load()), node)
            binding = kernel_.binding(donor['test_id'], node.id, at)
            if binding is not None:
                closed = kernel_.closed(donor['test_id'], kernel_.span(source_path, node))
                dependencies.append(closed['span'])
                return ast.copy_location(ast.parse(closed['text'], mode='eval').body, node)
            globals_.add(node.id)
            return node

    context = Close().visit(context)
    # A builtin name is shared across files only if neither file/test shadows
    # it. Other global/import closure uses the established emitter adapter.
    def unshadowed_builtin(name, path, test_id):
        if name not in vars(builtins) or name in kernel.sources[path].imports:
            return False
        record = kernel.corpus['tests'][test_id]
        if name in record.get('scope_bindings', ()) or name in record.get('parameters', ()):
            return False
        for node in kernel.modules[path].body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                return False
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
                                                                  and n.id == name for n in ast.walk(node)):
                return False
        return True
    globals_ = {name for name in globals_ if not (unshadowed_builtin(name, source_path, donor['test_id'])
                                                 and unshadowed_builtin(name, recipient_path, recipient['test_id']))}
    origin = {'test_id': donor['test_id'], 'span': kernel.span(source_path, donor['context']),
              'free_identifiers': sorted(globals_)}
    target = {'test_id': recipient['test_id'], 'span': kernel.span(recipient_path, recipient['statement'])}
    imports, unknowns = _transfer_bindings(kernel.corpus, kernel.sources, origin, target)
    if unknowns:
        raise Unsupported('exception_context_bindings_not_closed:' + ','.join(unknowns))
    return context, imports, {'catch_binding_renames': local, 'closed_dependency_spans': dependencies}


def generate_exception_contexts(corpus, frontend, budget: ExceptionBudget | None = None):
    """Generate hypotheses, pinning an existing later q on the same receiver."""
    budget = budget or ExceptionBudget()
    if any(type(value) is not int or value < 1 for value in asdict(budget).values()):
        raise ValueError('Exception budgets must be positive integers')
    skipped, candidates, attempts, seen = Counter(), [], 0, set()

    def result(exhausted=False):
        return {'candidates': candidates, 'skipped': dict(sorted(skipped.items())), 'attempts': attempts,
                'budget_exhausted': exhausted, 'budget': asdict(budget), 'domain': 'exception_input_context'}

    if corpus['language'] != 'python':
        skipped['exception_context_language_not_supported'] += 1
        return result()
    kernel = _Kernel(corpus, frontend)
    ordered = sorted(corpus['tests'], key=lambda key: (corpus['tests'][key].get('retrieval_rank') or 10**9,
                                                       _pos(corpus['tests'][key]['span'])))
    donors = []
    for donor in _donors(kernel, ordered, skipped):
        donors.append(donor)
        if len(donors) >= budget.max_donors:
            break
    plans = defaultdict(list)
    for test_id in ordered:
        for call in kernel.calls[test_id]:
            node = kernel.node(call['span'], ast.Call)
            statement = kernel.parents.get(id(node))
            if isinstance(statement, ast.Compare):
                statement = kernel.parents.get(id(statement))
            if not isinstance(statement, (ast.Expr, ast.Assert)):
                continue
            owner = kernel.parents.get(id(statement))
            if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.With)):
                continue
            # Existing exception contexts are donors, not normal-exit recipients.
            if any(d['test_id'] == test_id and d['statement'] is statement for d in donors):
                continue
            try:
                recipient = _simple_invocation(kernel, test_id, statement)
            except Unsupported as exc:
                skipped[str(exc)] += 1
                continue
            after = kernel.span(call['span']['path'], statement)['end_byte']
            relevant = []
            for q in kernel.observations[test_id]:
                if q['assertion_span']['start_byte'] <= after or q.get('predicate') == 'raises':
                    continue
                positions = kernel.observed_origins(test_id, q).get(recipient['origin']['identity'], [])
                if positions and min(p['start_byte'] for p in positions) > after:
                    relevant.append(q)
            for q in relevant[:budget.max_observations_per_call]:
                plans[test_id].append((recipient, q))

    def stream(recipient, q):
        for donor in donors:
            constructor_status = _same_callee(kernel, donor['origin']['constructor'], recipient['origin']['constructor'])
            if constructor_status is None:
                continue
            call_status = _same_callee(kernel, donor['call'], recipient['call'])
            if call_status is None and donor['node'].func.attr == recipient['node'].func.attr:
                call_status = 'same_source_constructor_and_member_hypothesis'
            if call_status is None:
                continue
            input_count = 0
            for route, left, right in [('invocation', donor['call'], recipient['call']),
                                      ('receiver_constructor', donor['origin']['constructor'], recipient['origin']['constructor'])]:
                for source_arg, target_arg, binding in _argument_pairs(left, right):
                    yield recipient, q, donor, route, source_arg, target_arg, binding, call_status, constructor_status
                    input_count += 1
                    if input_count >= budget.max_inputs_per_pair:
                        break
                if input_count >= budget.max_inputs_per_pair:
                    break

    streams = [_round_robin(stream(recipient, q) for recipient, q in plans[test_id])
               for test_id in ordered if test_id in plans]
    for recipient, q, donor, route, source_arg, target_arg, binding, call_status, constructor_status in _round_robin(streams):
        if attempts >= budget.max_attempts:
            skipped['attempt_budget'] += 1
            return result(True)
        attempts += 1
        identifier = stable_id('exception_input_context', recipient['call']['id'], q['id'],
                               donor['call']['id'], route, source_arg['slot'], target_arg['slot'])
        try:
            source_value = kernel.closed(donor['test_id'], source_arg['span'])
            kernel.closed(recipient['test_id'], target_arg['span'])
            if ast.dump(ast.parse(source_value['text'], mode='eval'), include_attributes=False) == ast.dump(
                    ast.parse(kernel.text(target_arg['span']), mode='eval'), include_attributes=False):
                continue
            context, imports, closure = _close_context(kernel, donor, recipient, identifier)
            invocation = kernel.text(recipient['call']['span'])
            edits = []
            if route == 'invocation':
                offset = recipient['call']['span']['start_byte']
                lo, hi = target_arg['span']['start_byte'] - offset, target_arg['span']['end_byte'] - offset
                raw = invocation.encode()
                invocation = (raw[:lo] + source_value['text'].encode() + raw[hi:]).decode()
            else:
                edits.append({'span': target_arg['span'], 'before': kernel.text(target_arg['span']), 'after': source_value['text']})
            context.body = [ast.Expr(value=ast.parse(invocation, mode='eval').body)]
            ast.fix_missing_locations(context)
            rendered = ast.unparse(context)
            position = kernel.span(recipient['call']['span']['path'], recipient['statement'])
            source = kernel.sources[position['path']]
            line_start = source.data.rfind(b'\n', 0, position['start_byte']) + 1
            indent = source.data[line_start:position['start_byte']].decode()
            if indent.strip():
                raise Unsupported('inline_invocation_requires_suite_rewrite')
            rendered = rendered.replace('\n', '\n' + indent)
            edits.append({'span': position, 'before': kernel.text(position), 'after': rendered,
                          'role': 'source_exception_context'})
            raw = source.data
            for edit in sorted(edits, key=lambda e: e['span']['start_byte'], reverse=True):
                p = edit['span']
                raw = raw[:p['start_byte']] + edit['after'].encode() + raw[p['end_byte']:]
            ast.parse(raw.decode())
        except Unsupported as exc:
            skipped[str(exc)] += 1
            continue
        except (SyntaxError, ValueError, RecursionError):
            skipped['exception_context_render_parse_error'] += 1
            continue
        key = stable_id(recipient['test_id'], q['id'], edits, imports)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            'id': identifier, 'base_test_id': recipient['test_id'], 'source_test_ids': [donor['test_id']],
            'language': 'python', 'kind': 'exception_input_context', 'edits': edits, 'imports': imports,
            'target_capsule_id': q['id'], 'source_observation_id': q['id'],
            'relation': {'domain': 'exception_input_context', 'cell': 'source_exception_input_with_recipient_resource_observer',
                         'status': 'statically_constructed_runtime_unconfirmed', 'input_route': route,
                         'invocation_binding_status': call_status, 'constructor_binding_status': constructor_status,
                         'argument_binding': binding, 'receiver_identity': 'same_recipient_constructor_value_and_aliases',
                         'phase': 'original_q_after_source_exception_context',
                         'runtime_obligation': 'exception_occurs_and_same_receiver_reaches_existing_q',
                         'applicability': 'unknown_requires_independent_admission'},
            'oracle': {'mode': 'retain_all', 'source_test_id': recipient['test_id'], 'assertion_ids': [q['id']],
                       'target_assertion_id': q['id'], 'applicability': 'requires_independent_admission', 'basis': None},
            'provenance': {'source_spans': [kernel.span(donor['call']['span']['path'], donor['context']), source_value['span']],
                           'source_exception_context_kind': donor['context_kind'],
                           'source_exception_context_span': kernel.span(donor['call']['span']['path'], donor['context']),
                           'source_invocation_span': donor['call']['span'], 'recipient_invocation_span': recipient['call']['span'],
                           'recipient_constructor_span': recipient['origin']['constructor']['span'],
                           'source_argument_span': source_arg['span'], 'target_argument_span': target_arg['span'],
                           'source_literal_span': source_value['span'], 'source_literal_binding_path': source_value['binding_path'],
                           'receiver_mapping': {donor['receiver']: recipient['receiver']},
                           'source_observation_span': q['assertion_span'], 'exception_closure': closure,
                           'replaced_normal_observation_ids': [other['id'] for other in kernel.observations[recipient['test_id']]
                               if _pos(other['assertion_span']) == _pos(position)],
                           'unproved': ['exception_preconditions', 'external_aliases', 'literal_mutation', 'cleanup_effects', 'oracle_transport']},
            'selection': {'base_retrieval_rank': corpus['tests'][recipient['test_id']].get('retrieval_rank'),
                          'schedule': 'parent_then_invocation_and_q_round_robin'},
        })
        if len(candidates) >= budget.max_candidates:
            skipped['candidate_budget'] += 1
            return result(True)
    return result()
