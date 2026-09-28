"""Complete a source call term with a source-owned, single-hole call context.

If a validation contains C[f(x)] and another uses f(y), the input hypothesis is
C[f(y)]. Only a direct call argument becomes a hole: its evaluation occurs once
in the original argument position. Callback bodies and other arguments come
from the source context. Callee alignment and lexical closure do not establish
type compatibility or the new observation's expected value.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import posixpath

from anchor_retrieval.syntax import ATTRS, CALLS, FUNCTIONS, Source, attr_parts, child, walk
from generic_composition.corpus import ASSIGNMENTS, source_text, span
from generic_composition.engine import stable_id


@dataclass(frozen=True)
class ContextBudget:
    max_candidates: int = 128
    max_contexts: int = 512
    max_attempts: int = 4096
    max_context_bytes: int = 3000
    max_contexts_per_callee: int = 24


def _pos(value):
    position = value.get('span', value)
    return position['path'], position['start_byte'], position['end_byte']


def _inside(inner, outer):
    a, b = inner.get('span', inner), outer.get('span', outer)
    return a['path'] == b['path'] and b['start_byte'] <= a['start_byte'] and a['end_byte'] <= b['end_byte']


def _identity(call):
    identity = call.get('callee_identity', {})
    return identity.get('canonical') or identity.get('scope_key') or (call['span']['path'] + '::' + call['callee'])


def _free_context_names(source, root, hole):
    """Lexically close expression-bodied callbacks, with no textual capture.

    Statement-bodied callbacks, defaults and assignments require a larger scope
    analysis and remain explicit unknowns. A direct argument hole cannot occur
    under any of these callback binders.
    """
    free = set()
    callbacks = FUNCTIONS | {'arrow_function', 'function_expression', 'func_literal', 'lambda'}
    def visit(node, bound):
        if node == hole:
            return
        if node.type in ASSIGNMENTS | {'assignment_expression', 'named_expression', 'update_expression'}:
            raise ValueError('context_assignment_scope_unsupported')
        if node.type in callbacks:
            params = child(node, 'parameters', 'parameter')
            body = child(node, 'body')
            if body is None or body.type in {'block', 'statement_block'}:
                raise ValueError('context_statement_callback_unsupported')
            if params is not None and any(n.type in {'default_parameter', 'default_parameter_declaration', 'assignment_pattern',
                                                    'object_pattern', 'array_pattern', 'typed_default_parameter'}
                                          for n in walk(params)):
                raise ValueError('context_callback_parameter_scope_unsupported')
            names = {source.text(n) for n in walk(params) if n.type == 'identifier'} if params is not None else set()
            visit(body, bound | names)
            return
        if node.type in {'identifier', 'shorthand_property_identifier'}:
            parent = node.parent
            if parent is not None and parent.type in ATTRS and node == attr_parts(parent)[1]:
                return
            if parent is not None and parent.type in {'pair', 'keyed_element', 'keyword_argument'} and node == child(parent, 'key', 'name'):
                return
            name = source.text(node)
            if name not in bound:
                free.add(name)
            return
        for part in node.named_children:
            visit(part, bound)
    visit(root, set())
    return free


def _import_key(corpus, path, item):
    module = item['module']
    if corpus['language'] == 'typescript' and module.startswith('.'):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(path), module))
        candidates = [base, base + '.ts', base + '.tsx', base + '/index.ts', base + '/index.tsx']
        if base.endswith(('.js', '.mjs', '.cjs')):
            stem = base.rsplit('.', 1)[0]
            candidates += [stem + '.ts', stem + '.tsx']
        found = [name for name in candidates if name in corpus['sources']]
        module = found[0] if len(found) == 1 else base
    elif corpus['language'] == 'python' and module.startswith('.'):
        dots = len(module) - len(module.lstrip('.'))
        base = posixpath.dirname(path)
        for _ in range(dots - 1):
            base = posixpath.dirname(base)
        module = posixpath.normpath(posixpath.join(base, module[dots:].replace('.', '/')))
    return module, item.get('imported_name')


def _close_context(corpus, context, target):
    source_test = corpus['tests'][context['test_id']]
    target_test = corpus['tests'][target['test_id']]
    source_locals, target_locals = set(source_test.get('scope_bindings', [])), set(target_test.get('scope_bindings', []))
    imports = {item['name']: item for item in source_test['support']['imports']}
    target_imports = {item['name']: item for item in target_test['support']['imports']}
    same_file = context['span']['path'] == target['span']['path']
    same_scope = source_test.get('enclosing_scope_span') == target_test.get('enclosing_scope_span')
    added = []
    for name in context['free_names']:
        # Source callbacks have already had their own binders removed; captures
        # of an enclosing test-local value must not become another test's value.
        if name in source_locals or name in target_locals:
            raise ValueError('context_test_local_capture')
        if name in imports:
            if (name in target_imports and
                    _import_key(corpus, context['span']['path'], imports[name]) !=
                    _import_key(corpus, target['span']['path'], target_imports[name])):
                raise ValueError('context_import_alias_collision')
            if name not in target_imports:
                added.append(dict(imports[name], source_path=context['span']['path']))
        elif not (same_file and same_scope):
            raise ValueError('context_unresolved_shared_name')
    return added


def generate_call_contexts(corpus, frontend, *, budget=ContextBudget()):
    if any(type(value) is not int or value < 1 for value in asdict(budget).values()):
        raise ValueError('context budgets must be positive integers')
    if corpus['language'] not in {'python', 'typescript'}:
        return {'candidates': [], 'counts': {'contexts': 0, 'attempts': 0, 'candidates': 0}, 'skipped': {'language_unsupported': 1}}
    sources = {path: Source(path, metadata['code'], metadata.get('language', corpus['language']))
               for path, metadata in corpus['sources'].items() if metadata.get('complete_file', True) and not metadata.get('parse_error')}
    maps = {path: {(n.start_byte, n.end_byte): n for n in walk(source.root)} for path, source in sources.items()}
    tests = corpus['tests']
    rank = lambda test_id: (tests[test_id].get('retrieval_rank') or 10**9, test_id)
    observations = defaultdict(list)
    for observation in frontend.get('observations', []):
        if observation.get('kind') == 'assertion':
            observations[observation['test_id']].append(observation)
    def eligible(call):
        if call.get('role') != 'operation' or call['test_id'] not in tests or not call.get('observation_ids'):
            return False
        return not any(o.get('expected') and _inside(call, o['expected']) for o in observations[call['test_id']])
    calls = sorted((c for c in frontend.get('calls', []) if eligible(c)), key=lambda c: (rank(c['test_id']), _pos(c)))
    by_span = {_pos(c): c for c in calls}
    by_callee = defaultdict(list)
    for call in calls:
        by_callee[_identity(call)].append(call)
    contexts, skipped, seen = [], Counter(), set()
    for outer in calls:
        source = sources.get(outer['span']['path'])
        if source is None or outer['span']['end_byte'] - outer['span']['start_byte'] > budget.max_context_bytes:
            continue
        root = maps[source.path].get((outer['span']['start_byte'], outer['span']['end_byte']))
        if root is None:
            continue
        for argument in outer['arguments']:
            hole_call = by_span.get(_pos(argument))
            if hole_call is None or argument.get('spread'):
                continue
            hole = maps[source.path].get((argument['span']['start_byte'], argument['span']['end_byte']))
            if hole is None or hole.type not in CALLS:
                continue
            try:
                free = _free_context_names(source, root, hole)
            except ValueError as error:
                skipped[str(error)] += 1
                continue
            prefix = source.data[root.start_byte:hole.start_byte].decode()
            suffix = source.data[hole.end_byte:root.end_byte].decode()
            key = (_identity(hole_call), prefix, suffix, source.path)
            if key in seen:
                continue
            seen.add(key)
            contexts.append(dict(outer, hole=hole_call, prefix=prefix, suffix=suffix, free_names=sorted(free)))
            if len(contexts) >= budget.max_contexts:
                break
        if len(contexts) >= budget.max_contexts:
            break
    per_callee = defaultdict(list)
    for context in contexts:
        if len(per_callee[_identity(context['hole'])]) < budget.max_contexts_per_callee:
            per_callee[_identity(context['hole'])].append(context)
    queues, attempts, generated = defaultdict(deque), 0, set()
    # Target-first traversal allows later source contexts to contribute to a
    # high-priority existing observation without requiring its test to be early.
    for target in calls:
        for context in per_callee[_identity(target)]:
            if _inside(target, context):
                continue
            attempts += 1
            if attempts > budget.max_attempts:
                break
            try:
                imports = _close_context(corpus, context, target)
            except ValueError as error:
                skipped[str(error)] += 1
                continue
            before = source_text(corpus, target['span'])
            after = context['prefix'] + before + context['suffix']
            # Re-wrapping an identical enclosing context adds no new composition.
            if any(_inside(target, call) and source_text(corpus, call['span']) == after
                   for call in calls if call['test_id'] == target['test_id'] and call != target):
                skipped['already_wrapped_in_source'] += 1
                continue
            edits = [{'span': target['span'], 'before': before, 'after': after}]
            identifier = stable_id('source-call-context', target['test_id'], edits)
            if identifier in generated:
                continue
            generated.add(identifier)
            queues[target['test_id']].append({
                'id': identifier, 'kind': 'source_call_context', 'base_test_id': target['test_id'],
                'focus_test_id': target['test_id'], 'language': corpus['language'],
                'source_test_ids': sorted({target['test_id'], context['test_id']}), 'edits': edits, 'imports': imports,
                'relation': {'domain': 'source_call_context', 'hole_callee': _identity(target),
                             'context_callee': _identity(context), 'source_hole_slot': context['hole']['span'],
                             'hole_evaluation': 'once_in_original_direct_argument_position',
                             'type_compatibility': 'unknown', 'oracle_applicability': 'unknown'},
                'oracle': {'mode': 'retain_all', 'applicability': 'requires_independent_admission',
                           'assertion_ids': [o['id'] for o in observations[target['test_id']]]},
                'provenance': {'source_spans': [context['span'], context['hole']['span'], target['span']],
                               'source_call_ids': [context['id'], context['hole']['id'], target['id']],
                               'context_free_names': context['free_names'], 'binding_precision': 'source_imports_or_shared_enclosing_scope'},
                'selection': {'focus_order': rank(target['test_id'])[0], 'edit_size': len(after.encode())}})
        if attempts > budget.max_attempts:
            break
    result = []
    while queues and len(result) < budget.max_candidates:
        for test_id in list(queues):
            result.append(queues[test_id].popleft())
            if not queues[test_id]:
                del queues[test_id]
            if len(result) >= budget.max_candidates:
                break
    return {'candidates': result, 'counts': {'contexts': len(contexts), 'attempts': attempts, 'pool': len(generated), 'candidates': len(result)},
            'skipped': dict(skipped), 'budget': asdict(budget), 'budget_exhausted': attempts > budget.max_attempts or bool(queues),
            'status': 'source_context_hypotheses_not_checked_relations'}
