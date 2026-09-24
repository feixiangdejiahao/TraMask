"""Program-selected contexts with independent, explicit expected-value holes.

The subject is never executed here. Context search is source driven; semantic
completion cannot change the selected input edit, assertion predicate or body.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import copy
import hashlib
import json
import re

from anchor_retrieval.syntax import CALLS, FUNCTIONS, Source, call_parts, child, walk
from generic_composition.corpus import source_text
from generic_composition import engine
from experimental.llm_baseline import validate_body
from . import oracle


@dataclass(frozen=True)
class Budget:
    max_candidates: int = 128
    shown_candidates: int = 24
    top_k: int = 10
    contexts_per_observation: int = 6
    max_test_bytes: int = 14000


def identifier(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def inside(a, b):
    return a['path'] == b['path'] and b['start_byte'] <= a['start_byte'] <= a['end_byte'] <= b['end_byte']


def _position(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte,
                line=node.start_point.row + 1, end_line=node.end_point.row + 1)


def _node(source, span):
    return next((n for n in walk(source.root)
                 if n.start_byte == span['start_byte'] and n.end_byte == span['end_byte']), None)


def _scope(node):
    while node is not None:
        if node.type in FUNCTIONS | {'class_definition', 'class_declaration', 'lambda',
                                     'arrow_function', 'function_expression', 'func_literal'}:
            return node
        node = node.parent
    return None


def _block(node):
    while node is not None:
        if node.type in {'block', 'statement_block', 'statement_list'}:
            return node
        node = node.parent
    return None


def _dominating_definition(source, current, test_span):
    """An identifier source oracle must not come from a sibling scope or branch."""
    definitions = []
    for node in walk(source.root):
        if not (test_span['start_byte'] <= node.start_byte < node.end_byte < current.start_byte):
            continue
        if node.type == 'nonlocal_statement' and any(
                source.text(name) == source.text(current) for name in node.named_children):
            raise ValueError('expected_binding_has_nonlocal_writes')
        if node.type not in {'assignment', 'augmented_assignment', 'assignment_expression', 'augmented_assignment_expression',
                             'assignment_statement', 'short_var_declaration', 'variable_declarator',
                             'var_spec', 'const_spec', 'update_expression', 'inc_statement', 'dec_statement',
                             'for_statement', 'for_in_statement'}:
            continue
        if _scope(node) != _scope(current):
            continue
        lhs = child(node, 'left', 'name', 'argument', 'operand')
        if lhs is None:
            continue
        if source.text(lhs) != source.text(current):
            if lhs.type in {'pattern_list', 'tuple_pattern', 'tuple', 'array_pattern', 'list_pattern', 'expression_list'} and any(
                    name.type == 'identifier' and source.text(name) == source.text(current) for name in walk(lhs)):
                raise ValueError('expected_binding_unpacking_unsupported')
            continue
        definitions.append(node)
    if not definitions:
        return None
    latest = max(definitions, key=lambda n: n.end_byte)
    block = _block(latest.parent)
    ancestry, ancestor = set(), current.parent
    while ancestor is not None:
        ancestry.add((ancestor.start_byte, ancestor.end_byte, ancestor.type))
        ancestor = ancestor.parent
    if block is None or (block.start_byte, block.end_byte, block.type) not in ancestry:
        raise ValueError('expected_definition_does_not_dominate_observation')
    operator = child(latest, 'operator')
    if (latest.type in {'augmented_assignment', 'augmented_assignment_expression', 'update_expression',
                        'inc_statement', 'dec_statement', 'for_statement', 'for_in_statement'}
            or operator is not None and source.text(operator) not in {'=', ':='}):
        raise ValueError('expected_definition_not_literal')
    rhs = child(latest, 'right', 'value')
    if rhs is None:
        return None
    parsed = oracle.parse_source_literal(source.text(rhs), source.language)
    def immutable(value):
        return (type(value) in {str, bytes, int, float, bool, type(None)}
                or type(value) is tuple and all(immutable(v) for v in value))
    if not isinstance(parsed, oracle.Unknown) and immutable(parsed):
        return rhs
    # A later alias/use can mutate a literal container. Keep this local source
    # fact narrow; the main program effect analysis is a may analysis.
    for node in walk(block):
        if latest.end_byte <= node.start_byte < current.start_byte and node.type == 'identifier':
            if source.text(node) == source.text(current):
                raise ValueError('expected_binding_used_after_literal_definition')
    return rhs


def _expected(corpus, capsule, source, row):
    """One explicit source oracle; a single literal inside a constructor is a hole."""
    expression = capsule.get('expected')
    if expression is None:
        helpers = [h.get('caller_expected') for h in capsule.get('helper_assertions', [])
                   if h.get('caller_expected')]
        if len(helpers) != 1:
            raise ValueError('no_unique_explicit_expected')
        expression = helpers[0]
    text = expression['text']
    position = expression['span']
    if text in row:
        return position, row[text], {'kind': 'parameter_row', 'name': text}
    value = oracle.parse_source_literal(text, corpus['language'])
    if not isinstance(value, oracle.Unknown):
        return position, value, {'kind': 'literal'}
    current = _node(source, position)
    if current is None:
        raise ValueError('expected_node_missing')
    if current.type == 'identifier':
        rhs = _dominating_definition(source, current, capsule['test_span'])
        if rhs is not None:
            value = oracle.parse_source_literal(source.text(rhs), corpus['language'])
            if not isinstance(value, oracle.Unknown):
                return position, value, {'kind': 'preceding_literal_definition', 'span': _position(source, rhs)}
    literals = []
    for n in walk(current):
        if n.children and n.type not in {'string', 'raw_string_literal', 'interpreted_string_literal'}:
            continue
        try:
            value = oracle.parse_source_literal(source.text(n), corpus['language'])
        except (ValueError, TypeError):
            continue
        if isinstance(value, oracle.Unknown):
            continue
        if n.type in {'identifier', 'property_identifier', 'field_identifier'}:
            continue
        literals.append((n, value))
    maximal = [(n, v) for n, v in literals if not any(
        m != n and m.start_byte <= n.start_byte and n.end_byte <= m.end_byte for m, _ in literals)]
    if len(maximal) == 1:
        n, value = maximal[0]
        return _position(source, n), value, {'kind': 'single_literal_in_source_expected', 'outer': text}
    raise ValueError('expected_not_statically_available')


def _direct_statement(source, body, position):
    choices = [n for n in body.named_children if n.type != 'comment']
    if len(choices) == 1 and choices[0].type == 'statement_list':
        choices = list(choices[0].named_children)
    return next((n for n in choices if n.start_byte <= position['start_byte']
                 and position['end_byte'] <= n.end_byte), None)


def _apply(raw, lo, hi, edits):
    cursor, parts = lo, []
    for edit in sorted(edits, key=lambda e: (e['span']['start_byte'], e['span']['end_byte'])):
        a, b = edit['span']['start_byte'], edit['span']['end_byte']
        if not lo <= a <= b <= hi or a < cursor:
            raise ValueError('overlapping_or_outside_atomic_edit')
        if raw[a:b].decode() != edit['before']:
            raise ValueError('source_edit_mismatch')
        parts += [raw[cursor:a].decode(), edit['after']]
        cursor = b
    return ''.join(parts) + raw[cursor:hi].decode()


def atomic_body(corpus, source, proposal, capsule, expected_span, expected_literal, row):
    """Keep the selected observation and its prefix, not stale later oracles."""
    parent = corpus['tests'][proposal['base_test_id']]
    body = _node(source, parent['body_span'])
    if body is None:
        raise ValueError('body_node_missing')
    end_statement = _direct_statement(source, body, capsule['assertion_span'])
    if end_statement is None:
        raise ValueError('assertion_not_in_body')
    # A nested control block is retained as a whole. We do not split its syntax.
    lo, hi = body.start_byte, end_statement.end_byte
    edits = [dict(e) for e in proposal['edits'] if inside(e['span'], parent['body_span'])]
    if any(e['span']['end_byte'] > hi for e in edits):
        raise ValueError('context_after_selected_observation')
    edits.append({'span': expected_span, 'before': source_text(corpus, expected_span), 'after': expected_literal})
    neutralized = []
    first_context_edit = min((e['span']['start_byte'] for e in proposal['edits']), default=lo)
    for other in corpus['capsules']:
        if other['test_id'] != capsule['test_id'] or other['id'] == capsule['id']:
            continue
        s = other['assertion_span']
        if not lo <= s['start_byte'] < s['end_byte'] <= hi:
            continue
        if s['end_byte'] <= first_context_edit:
            continue  # This assertion executes before the changed context.
        if any(inside(e['span'], s) for e in edits):
            # Different oracle inside the context/selected statement cannot be removed.
            raise ValueError('overlapping_other_observation')
        observed = other.get('observed')
        if not observed or other.get('helper_assertions'):
            raise ValueError('cannot_neutralize_other_assertion_helper')
        node = _node(source, s)
        if node is None:
            raise ValueError('cannot_preserve_other_observation_effects')
        actual = observed['text']
        if corpus['language'] == 'python':
            if node.type != 'assert_statement' or not node.named_children:
                raise ValueError('cannot_preserve_other_observation_effects')
            # Evaluate the whole condition, retaining both operands, short
            # circuiting and comparison effects; only remove the assertion.
            after = '(True if (' + source.text(node.named_children[0]) + ') else False)'
        elif corpus['language'] == 'go':
            if node.type != 'if_statement' or child(node, 'consequence') is None:
                raise ValueError('cannot_preserve_other_observation_effects')
            consequence = child(node, 'consequence')
            # A recognized failure-only guard retains initializer/condition
            # evaluation and scope; only the failure-reporting body is removed.
            after = source.data[node.start_byte:consequence.start_byte].decode() + '{}'
        else:
            expected = other.get('expected')
            if other.get('predicate') not in {'toBe', 'toEqual', 'toStrictEqual', 'equal', 'strictEqual',
                                             'deepEqual', 'deepStrictEqual'} or expected is None:
                raise ValueError('cannot_preserve_other_observation_effects')
            call = node
            while call.type == 'expression_statement' and len(call.named_children) == 1:
                call = call.named_children[0]
            if call.type not in CALLS:
                raise ValueError('cannot_preserve_other_observation_effects')
            _, arguments = call_parts(call)
            evaluated = [source.text(argument) for argument in arguments]
            if other.get('assertion_adapter') != 'node_assert_import':
                evaluated.insert(0, actual)
            # Include optional assertion-message arguments as well: their
            # expressions execute before a standard assertion call.
            after = 'void ([' + ', '.join(evaluated) + '])'
        edits.append({'span': s, 'before': source_text(corpus, s), 'after': after})
        neutralized.append(other['id'])
    raw = source.code.encode() if hasattr(source, 'code') else corpus['sources'][source.path]['code'].encode()
    text = _apply(raw, lo, hi, edits)
    if corpus['language'] == 'python' and row:
        indent = raw[raw.rfind(b'\n', 0, lo) + 1:lo].decode()
        statements = [name + ' = ' + oracle.emit_literal(value, 'python') for name, value in sorted(row.items())]
        text = ('\n' + indent).join(statements) + '\n' + indent + text
    if corpus['language'] != 'python':
        text += '\n}'
    return text, neutralized


def _affected(capsule, context):
    if context.get('target_capsule_id'):
        return capsule['id'] == context['target_capsule_id']
    parameter = context.get('parameter_input_name')
    if parameter and any(n.get('parameter') == parameter
                         for n in capsule['bindings']['slice_nodes']):
        return True
    spans = [dict(path=capsule['test_span']['path'], start_byte=n['start_byte'], end_byte=n['end_byte'])
             for n in capsule['bindings']['slice_nodes']]
    for edit in context['edits']:
        if any(inside(edit['span'], s) for s in spans):
            return True
    return False


def generate(corpus, budget=Budget()):
    basic = engine.generate(corpus, engine.Budget(max_candidates=budget.max_candidates,
                           top_k=budget.top_k, max_test_bytes=budget.max_test_bytes))
    from .state_contexts import generate_state_contexts
    state = generate_state_contexts(corpus, top_k=budget.top_k, max_candidates=budget.max_candidates)
    sources = {p: Source(p, v['code'], corpus['language']) for p, v in corpus['sources'].items()}
    contexts = basic['candidates'] + state['candidates']
    donors = {d['id']: d for d in engine.expanded_donors(corpus)}
    by_test = defaultdict(list)
    for c in corpus['capsules']:
        by_test[c['test_id']].append(c)
    candidates, skipped = [], Counter()
    for context in contexts:
        parent = corpus['tests'][context['base_test_id']]
        source = sources[parent['span']['path']]
        target = donors.get(context.get('provenance', {}).get('target_donor_id'))
        row = (target or {}).get('parameter_row')
        if row:
            context = dict(context, parameter_input_name=row['name'])
        original_row = copy.deepcopy(row['bindings']) if row else {}
        new_row = copy.deepcopy(original_row)
        args = list(context.get('arg_values', []))
        for edit in context['edits']:
            try:
                value = oracle.parse_source_literal(edit['after'], corpus['language'])
                if isinstance(value, oracle.Unknown):
                    continue
                args.append(value)
                if row and not inside(edit['span'], parent['body_span']):
                    new_row[row['name']] = value
            except (ValueError, TypeError):
                pass
        relevant = [c for c in by_test[parent['id']] if _affected(c, context)]
        relevant.sort(key=lambda c: (c['incidental'], not bool(c.get('retrieval_anchor_ids')), c['assertion_span']['start_byte']))
        for capsule in relevant[:budget.contexts_per_observation]:
            try:
                expected_span, value, provenance = _expected(corpus, capsule, source, original_row)
                hint = None
                if corpus['language'] == 'go':
                    original = source_text(corpus, provenance.get('span', expected_span)).strip()
                    match = re.match(r'((?:\[\d*\]\w+|map\[\w+\]\w+))\s*\{', original)
                    hint = match.group(1) if match else None
                literal = oracle.emit_literal(value, corpus['language'], hint)
                body, neutralized = atomic_body(corpus, source, context, capsule, expected_span, literal, new_row)
                mechanical = validate_body(corpus, parent['id'], body)
                if mechanical['status'] == 'unsupported':
                    skipped[mechanical['reason']] += 1
                    continue
            except (ValueError, TypeError, KeyError) as exc:
                skipped[str(exc)] += 1
                continue
            cid = identifier('observation_transport', context['id'], capsule['id'], original_row)
            candidates.append({'id': cid, 'candidate_id': cid, 'language': corpus['language'],
                'base_test_id': parent['id'], 'source_test_ids': context['source_test_ids'],
                'context': context, 'capsule_id': capsule['id'], 'expected_span': expected_span,
                'pre': [oracle.encode_value(value)], 'arg': [oracle.encode_value(v) for v in args],
                'observations': [{'text': capsule['observed']['text'] if capsule.get('observed') else capsule['assertion'],
                                  'predicate': capsule['predicate'], 'expected_source': provenance,
                                  **({'go_type': hint} if hint else {})}],
                'parameter_bindings': {k: oracle.encode_value(v) for k, v in new_row.items()},
                'preview_body': body, 'neutralized_assertions': neutralized,
                'priority': [parent.get('retrieval_rank') or 99999, int(capsule['incidental']),
                             int(not bool(capsule.get('retrieval_anchor_ids'))), capsule['assertion_span']['start_byte']],
                'semantic_status': 'requires_observation_transformer'})
    bins = defaultdict(lambda: defaultdict(lambda: defaultdict(deque)))
    for candidate in sorted(candidates, key=lambda c: (c['priority'], c['id'])):
        bins[candidate['base_test_id']][candidate['context']['kind']][candidate['capsule_id']].append(candidate)
    # One candidate per parent per round; inside each parent alternate context
    # families, then observation capsules. Large tests cannot monopolize shown K.
    ordered = sorted(bins, key=lambda key: (corpus['tests'][key].get('retrieval_rank') or 99999, key))
    kind_order = {parent: deque(sorted(bins[parent])) for parent in ordered}
    for offset, parent in enumerate(ordered):
        kind_order[parent].rotate(-(offset % len(kind_order[parent])))
    capsule_order = {(parent, kind): deque(sorted(capsules, key=lambda cap: (capsules[cap][0]['priority'], cap)))
                     for parent, kinds in bins.items() for kind, capsules in kinds.items()}
    selected = []
    while bins and len(selected) < budget.max_candidates:
        for parent in ordered:
            if parent not in bins:
                continue
            kind = kind_order[parent].popleft()
            capsules = capsule_order[parent, kind]
            cap = capsules.popleft()
            selected.append(bins[parent][kind][cap].popleft())
            if bins[parent][kind][cap]:
                capsules.append(cap)
            else:
                del bins[parent][kind][cap]
            if bins[parent][kind]:
                kind_order[parent].append(kind)
            else:
                del bins[parent][kind]
            if not bins[parent]:
                del bins[parent]
            if len(selected) == budget.max_candidates:
                break
    return {'algorithm': 'dependency_guided_observation_transport_v1', 'budget': asdict(budget),
            'candidates': selected, 'shown_ids': [c['id'] for c in selected[:budget.shown_candidates]],
            'counts': {'contexts': len(contexts), 'oracle_context_pairs': len(candidates),
                       'candidates': len(selected), 'shown': min(len(selected), budget.shown_candidates)},
            'skipped': dict(skipped), 'context_skipped': {'value': basic['skipped'], 'state': state['skipped']}}


def materialize(corpus, candidate, completion):
    if completion.get('candidate_id') != candidate['candidate_id']:
        raise ValueError('completion_candidate_mismatch')
    # Recompute the literal at the trust boundary. Even a direct caller cannot
    # smuggle body text through a forged cached completion["literal"].
    checked = oracle.validate_completions({'completions': [{
        'candidate_id': completion.get('candidate_id'), 'observe': completion.get('observe'),
        'expected': completion.get('expected_expr'), 'guard': completion.get('guard_expr'),
    }]}, [candidate])
    if not checked['accepted']:
        raise ValueError('completion_not_valid:' + checked['rejected'][0]['code'])
    authoritative = checked['accepted'][0]
    if completion.get('literal') != authoritative['literal']:
        raise ValueError('completion_literal_mismatch')
    completion = authoritative
    parent = corpus['tests'][candidate['base_test_id']]
    path = parent['span']['path']
    source = Source(path, corpus['sources'][path]['code'], corpus['language'])
    capsule = next(c for c in corpus['capsules'] if c['id'] == candidate['capsule_id'])
    row = {k: oracle.decode_value(v) for k, v in candidate['parameter_bindings'].items()}
    body, neutralized = atomic_body(corpus, source, candidate['context'], capsule,
                                   candidate['expected_span'], completion['literal'], row)
    validation = validate_body(corpus, parent['id'], body)
    if validation['status'] == 'unsupported':
        raise ValueError(validation['reason'])
    return {'id': identifier(candidate['id'], body), 'base_test_id': parent['id'],
            'source_test_ids': candidate['source_test_ids'], 'language': corpus['language'],
            'kind': 'semantic_observation_transport', 'rule_id': candidate['id'],
            'imports': candidate['context'].get('imports', []),
            'edits': [{'span': parent['body_span'], 'before': source_text(corpus, parent['body_span']), 'after': body}],
            'oracle': {'mode': 'observation_transformer', 'completion': completion,
                       'source_test_id': parent['id'], 'assertion_ids': [capsule['id']],
                       'semantic_status': 'model_hypothesis_requires_independent_evaluation'},
            'provenance': {'context': candidate['context'], 'pre': candidate['pre'], 'arg': candidate['arg'],
                           'source_expected_span': candidate['expected_span'],
                           'neutralized_assertions': neutralized, 'binding_analysis': validation}}
