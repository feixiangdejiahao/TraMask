"""Source observation migration over frozen, program-selected action contexts.

generate_projections(corpus, pending_candidates) returns oracle-compatible
candidates. materialize_projection returns generic emitter proposals. Neither
function modifies the frozen generator or driver, runs a subject, or permits
the model to edit the selected body.

The supported fragment is a closed observation on one typed receiver/return
root, within the same file and enclosing scope. Literal dependencies are
inlined. Ambiguous extra objects and control initializers remain explicit skips.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import ATTRS, CALLS, Source, attr_parts, call_parts, child, walk
from experimental.llm_baseline import validate_body
from experimental.semantic_transport import oracle
from experimental.semantic_transport.proposals import _block, _dominating_definition, _expected, _scope as _lexical_scope
from experimental.semantic_transport.state_contexts import _reads
from generic_composition.corpus import _assertion_nodes, _callee_identity, source_text


@dataclass(frozen=True)
class Budget:
    max_candidates: int = 128
    max_templates: int = 256
    projections_per_action: int = 4
    max_attempts: int = 4096


class Unsupported(ValueError):
    pass


def _id(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def _key(node):
    return node.start_byte, node.end_byte


def _contains(outer, inner):
    return outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def _position(source, node):
    return {'path': source.path, 'start_byte': node.start_byte, 'end_byte': node.end_byte}


def _scope(record):
    position = record.get('enclosing_scope_span') or {}
    return record['span']['path'], position.get('start_byte'), position.get('end_byte')


def _sources(corpus):
    return [Source(path, item['code'], item.get('language', corpus['language']))
            for path, item in sorted(corpus['sources'].items())
            if item.get('complete_file', True) and not item.get('parse_error')]


def _index(corpus, replacement=None, sources=None):
    return Index([replacement if replacement is not None and source.path == replacement.path else source
                  for source in (sources if sources is not None else _sources(corpus))], '')


def _find(source, position):
    return next((n for n in walk(source.root) if _key(n) == (position['start_byte'], position['end_byte'])), None)


def _unwrap(node):
    while node is not None and node.type in {'parenthesized_expression', 'expression_list'} and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


def _receiver_definition(unit, reference):
    """Find the object's allocation/alias binding, allowing intervening mutations."""
    choices = []
    for node in walk(unit.body):
        if node.end_byte >= reference.start_byte or _lexical_scope(node) != _lexical_scope(reference):
            continue
        if node.type not in {'assignment', 'assignment_statement', 'short_var_declaration',
                             'variable_declarator', 'var_spec', 'const_spec'}:
            continue
        lhs, rhs = child(node, 'left', 'name'), child(node, 'right', 'value')
        if lhs is not None and rhs is not None and unit.source.text(lhs) == unit.source.text(reference):
            choices.append((node, _unwrap(rhs)))
    if not choices:
        return None
    latest, value = max(choices, key=lambda pair: pair[0].end_byte)
    block, ancestor = _block(latest.parent), reference.parent
    while ancestor is not None and ancestor != block:
        ancestor = ancestor.parent
    return value if ancestor is not None else None


def _origins(index, unit, root):
    node = _unwrap(root)
    seen = set()
    while node is not None and node.type == 'identifier':
        if _key(node) in seen:
            return ()
        seen.add(_key(node))
        node = _receiver_definition(unit, node)
    if node is None or node.type not in CALLS:
        return ()
    identity = _callee_identity(index, unit, node)
    if identity.get('canonical') and identity.get('resolution') in {
        'local_symbol', 'package_symbol', 'import_symbol', 'import_alias',
    }:
        return (identity['canonical'],)
    function, _ = call_parts(node)
    name = unit.source.text(function)
    classes = [n for n in unit.source.root.named_children
               if n.type in {'class_definition', 'class_declaration'}
               and unit.source.text(child(n, 'name')) == name]
    return (unit.source.path + '::class::' + name,) if len(classes) == 1 else ()


def _roots(index, unit, observed):
    """Obtain class types at the actual read/call, not from a final variable env."""
    flow, found = index.flow(unit.id), {}
    nodes = {_key(node): node for node in walk(observed)}
    classes = set(index.classes)

    def add(node, types):
        node = _unwrap(node)
        if node is None or not _contains(observed, node) or node.type not in {'identifier', *CALLS}:
            return
        types, origins = set(types) & classes, _origins(index, unit, node)
        if not types and not origins:
            return
        group = ('identifier', unit.source.text(node)) if node.type == 'identifier' else ('expression', *_key(node))
        row = found.setdefault(group, {'nodes': {}, 'types': set(), 'origins': set()})
        row['nodes'][_key(node)] = node
        row['types'].update(types)
        row['origins'].update(origins)

    for call in flow.calls:
        meta = flow.nodes[call.node]
        node = nodes.get((meta['start_byte'], meta['end_byte']))
        if node is None or node.type not in CALLS:
            continue
        function, arguments = call_parts(node)
        if function is not None and function.type in ATTRS and call.receiver is not None:
            add(attr_parts(function)[0], call.receiver.types)
        for argument, value in zip([a for a in arguments if a.type != 'keyword_argument'], call.args):
            add(argument, value.types)
        if node == observed:
            types = {unit.source.text(function)} & classes
            for target, _ in call.targets:
                types.update(index.return_types(index.units[target]))
            if types:
                add(node, types)
    for meta in flow.nodes:
        node = nodes.get((meta['start_byte'], meta['end_byte']))
        if meta['kind'] == 'field_read' and node is not None and node.type in ATTRS:
            add(attr_parts(node)[0], meta.get('receiver_types', []))
    roots = [{'nodes': [r['nodes'][key] for key in sorted(r['nodes'])],
              'types': tuple(sorted(r['types'])), 'origins': tuple(sorted(r['origins']))}
             for r in found.values()]
    # A root inside a typed wrapper input would let observation replacement
    # silently delete that wrapper. Observe the outer action result instead.
    return [root for root in roots if not all(any(
        _key(outer) != _key(node) and _contains(outer, node)
        for other in roots if other is not root for outer in other['nodes'])
        for node in root['nodes'])]


def _match(left, right):
    return bool(set(left['types']) & set(right['types']) or set(left['origins']) & set(right['origins']))


def _expand_observed(source, unit, node, record):
    seen = set()
    while node.type == 'identifier':
        if _key(node) in seen:
            raise Unsupported('cyclic_observation_definition')
        seen.add(_key(node))
        rhs = _unwrap(_dominating_definition(source, node, record['span']))
        if rhs is None or rhs.type == 'identifier' or not any(n.type in ATTRS for n in walk(rhs)):
            break
        node = rhs
    return node


def _literal_dependency(source, record, reference):
    rhs = _dominating_definition(source, reference, record['span'])
    value = oracle.parse_source_literal(source.text(rhs), source.language) if rhs is not None else oracle.unknown()
    if isinstance(value, oracle.Unknown):
        raise Unsupported('observer_local_dependency_not_literal')
    return oracle.emit_literal(value, source.language)


def _rewrite(source, node, edits):
    cursor, out = node.start_byte, []
    unique = {}
    for a, b, text in edits:
        if (a, b) in unique and unique[a, b] != text:
            raise Unsupported('conflicting_observer_bindings')
        unique[a, b] = text
    for (a, b), text in sorted(unique.items()):
        if a < cursor or not node.start_byte <= a <= b <= node.end_byte:
            raise Unsupported('overlapping_observer_bindings')
        out += [source.data[cursor:a].decode(), text]
        cursor = b
    return ''.join(out) + source.data[cursor:node.end_byte].decode()


def _close_observer(template, target_record, target_unit, replacement):
    source, record, observed, root = (template[k] for k in ('source', 'record', 'observed', 'root'))
    simple = bool(re.fullmatch(r'[A-Za-z_$][\w$]*', replacement))
    if len(root['nodes']) > 1 and not simple:
        raise Unsupported('would_duplicate_effectful_root')
    root_name = source.text(root['nodes'][0]) if root['nodes'][0].type == 'identifier' else None
    edits = [(*_key(node), replacement if simple else '(' + replacement + ')') for node in root['nodes']]
    local = set(record.get('scope_bindings', [])) | set(template['unit'].params)
    target_local = set(target_record.get('scope_bindings', [])) | set(target_unit.params)
    for reference in _reads(observed):
        if any(_contains(node, reference) for node in root['nodes']):
            continue
        name = source.text(reference)
        if root_name is not None and name == root_name:
            if not simple:
                raise Unsupported('would_duplicate_effectful_root')
            edits.append((*_key(reference), replacement))
        elif name in local:
            edits.append((*_key(reference), _literal_dependency(source, record, reference)))
        elif name in target_local:
            raise Unsupported('observer_global_shadowed_in_recipient')
    return _rewrite(source, observed, edits)


def _bank(corpus, index, budget, skipped):
    templates, seen = [], set()
    for capsule in sorted(corpus['capsules'], key=lambda c: (
            corpus['tests'][c['test_id']].get('retrieval_rank') or 99999, c['id'])):
        try:
            if capsule.get('helper_assertions') or not capsule.get('observed'):
                raise Unsupported('observer_helper_or_actual_missing')
            record = corpus['tests'][capsule['test_id']]
            if record.get('parameterization_status', 'none_detected') != 'none_detected':
                raise Unsupported('observer_parameter_rows_require_instantiation')
            unit = index.units.get(record['id'])
            if unit is None:
                raise Unsupported('observer_source_unit_missing')
            source = unit.source
            statement = _find(source, capsule['assertion_span'])
            original = _find(source, capsule['observed']['span'])
            if statement is None or original is None:
                raise Unsupported('observer_source_node_missing')
            if statement.type == 'if_statement' and child(statement, 'initializer') is not None:
                raise Unsupported('observer_control_initializer_unsupported')
            expected, seed, provenance = _expected(corpus, capsule, source, {})
            observed = _expand_observed(source, unit, original, record)
            if any(n.type in {'lambda', 'arrow_function', 'function_expression', 'func_literal',
                              'list_comprehension', 'set_comprehension', 'dictionary_comprehension',
                              'generator_expression'} for n in walk(observed)):
                raise Unsupported('observer_nested_binding_scope_unsupported')
            for root in _roots(index, unit, observed):
                row = dict(capsule=capsule, record=record, unit=unit, source=source,
                           statement=statement, original=original, observed=observed,
                           root=root, expected=expected, seed=seed, expected_provenance=provenance)
                shape = _close_observer(row, record, unit, '__projection_root__')
                key = (_scope(record), shape, capsule['predicate'], root['types'], root['origins'])
                if key in seen:
                    continue
                seen.add(key)
                templates.append(row)
                if len(templates) >= budget.max_templates:
                    return templates
        except (ValueError, KeyError, TypeError) as exc:
            skipped[str(exc)] += 1
    return templates


def _edited_action(corpus, pending, sources):
    parent = corpus['tests'][pending['base_test_id']]
    pos = parent['body_span']
    raw = corpus['sources'][pos['path']]['code'].encode()
    source = Source(pos['path'], (raw[:pos['start_byte']] + pending['preview_body'].encode()
                                 + raw[pos['end_byte']:]).decode(), corpus['language'])
    if source.root.has_error:
        raise Unsupported('action_preview_parse_error')
    index = _index(corpus, source, sources)
    unit = index.units.get(parent['id'])
    if unit is None or not index.flow(unit.id).assertions:
        raise Unsupported('action_preview_observation_missing')
    statement, observed, expected, predicate = _assertion_nodes(source, index.flow(unit.id).assertions[-1], unit)
    if statement is None or observed is None or expected is None:
        raise Unsupported('action_preview_terminal_observation_unsupported')
    return parent, source, index, unit, statement, observed, predicate


def _inputs(source, index, unit, statement, root, pending):
    result, provenance = [], []
    nodes = {_key(node): node for node in walk(unit.body) if node.type in CALLS}
    flow = index.flow(unit.id)
    root_spans = {_key(node) for node in root['nodes']}
    cone = flow.slice([meta['id'] for meta in flow.nodes
                       if (meta['start_byte'], meta['end_byte']) in root_spans])
    for call in sorted(flow.calls, key=lambda c: flow.nodes[c.node]['start_byte']):
        if call.node not in cone:
            continue
        meta = flow.nodes[call.node]
        if meta['start_byte'] >= statement.start_byte and not any(
                node.start_byte <= meta['start_byte'] < meta['end_byte'] <= node.end_byte for node in root['nodes']):
            continue
        call_node = nodes.get((meta['start_byte'], meta['end_byte']))
        if call_node is None:
            continue
        for argument in call_parts(call_node)[1]:
            argument = child(argument, 'value') if argument.type == 'keyword_argument' else argument
            value = oracle.parse_source_literal(source.text(argument), source.language)
            if isinstance(value, oracle.Unknown) and argument.type == 'identifier':
                try:
                    rhs = _dominating_definition(source, argument, _position(source, unit.node))
                    value = oracle.parse_source_literal(source.text(rhs), source.language) if rhs is not None else value
                except ValueError:
                    pass
            if isinstance(value, oracle.Unknown):
                continue
            result.append(oracle.encode_value(value))
            provenance.append({'kind': 'action_argument', 'text': source.text(argument), **_position(source, argument)})
    if not result:
        result = copy.deepcopy(pending.get('arg', []))
        provenance = [{'kind': 'existing_context_argument', 'slot': i} for i in range(len(result))]
    return result, provenance


def _fixture_name(donor, target, name):
    if name not in donor.params:
        return None
    typ = donor.param_types.get(name)
    matches = [p for p in target.params if typ and target.param_types.get(p) == typ]
    if len(matches) == 1:
        return matches[0]
    if name in {'self', 'cls'} and donor.owner and donor.owner == target.owner and name in target.params:
        return name
    return None


def _assertion(template, target_record, target_unit, observed_text):
    source, node, expected = template['source'], template['statement'], template['expected']
    hint = None
    if source.language == 'go':
        position = template['expected_provenance'].get('span', expected)
        raw = source.data[position['start_byte']:position['end_byte']].decode()
        match = re.match(r'((?:\[\d*\]\w+|map\[\w+\]\w+))\s*\{', raw.strip())
        hint = match.group(1) if match else None
    literal = oracle.emit_literal(template['seed'], source.language, hint)
    edits = [(*_key(template['original']), observed_text, False),
             (expected['start_byte'], expected['end_byte'], literal, True)]
    local = set(template['record'].get('scope_bindings', [])) | set(template['unit'].params)
    target_local = set(target_record.get('scope_bindings', [])) | set(target_unit.params)
    for ref in _reads(node):
        if _contains(template['original'], ref) or expected['start_byte'] <= ref.start_byte < ref.end_byte <= expected['end_byte']:
            continue
        name = source.text(ref)
        mapped = _fixture_name(template['unit'], target_unit, name)
        if mapped is not None:
            edits.append((*_key(ref), mapped, False))
        elif name in local:
            edits.append((*_key(ref), _literal_dependency(source, template['record'], ref), False))
        elif name in target_local:
            raise Unsupported('assertion_global_shadowed_in_recipient')
    cursor, out, size, hole = node.start_byte, [], 0, None
    for a, b, text, is_hole in sorted(set(edits)):
        if a < cursor or not node.start_byte <= a <= b <= node.end_byte:
            raise Unsupported('overlapping_assertion_template_edits')
        prefix = source.data[cursor:a].decode()
        out.extend([prefix, text])
        size += len(prefix.encode())
        if is_hole:
            hole = size, size + len(text.encode())
        size += len(text.encode())
        cursor = b
    out.append(source.data[cursor:node.end_byte].decode())
    if hole is None:
        raise Unsupported('projection_expected_hole_missing')
    return ''.join(out), hole, literal, hint


def generate_projections(corpus, pending_candidates, budget=Budget()):
    """Generate separately frozen terminal-observation variants of existing actions."""
    if any(type(v) is not int or v < 1 for v in asdict(budget).values()):
        raise ValueError('Projection budgets must be positive integers')
    skipped, templates_by_scope = Counter(), defaultdict(list)
    sources = _sources(corpus)
    templates = _bank(corpus, _index(corpus, sources=sources), budget, skipped)
    for template in templates:
        templates_by_scope[_scope(template['record'])].append(template)
    candidates, seen, attempts = [], set(), 0
    for pending in pending_candidates:
        count = 0
        try:
            parent, source, index, unit, statement, observed, predicate = _edited_action(corpus, pending, sources)
            roots = _roots(index, unit, observed)
        except (ValueError, KeyError, TypeError) as exc:
            skipped[str(exc)] += 1
            continue
        for root in roots:
            replacement = source.text(root['nodes'][0])
            for template in templates_by_scope[_scope(parent)]:
                attempts += 1
                if attempts > budget.max_attempts:
                    skipped['attempt_budget'] += 1
                    return _result(candidates, templates, skipped, attempts - 1, budget)
                if not _match(template['root'], root):
                    continue
                try:
                    actual = _close_observer(template, parent, unit, replacement)
                    if actual == source.text(observed) and predicate == template['capsule']['predicate']:
                        continue
                    assertion, hole, literal, hint = _assertion(template, parent, unit, actual)
                    if '\n' in assertion:
                        raise Unsupported('multiline_observer_assertion_unsupported')
                    lo = statement.start_byte - parent['body_span']['start_byte']
                    hi = statement.end_byte - parent['body_span']['start_byte']
                    original = pending['preview_body'].encode()
                    body = (original[:lo] + assertion.encode() + original[hi:]).decode()
                    mechanical = validate_body(corpus, parent['id'], body)
                    if mechanical['status'] == 'unsupported':
                        raise Unsupported(mechanical['reason'])
                    signature = (original[:lo] + assertion.encode()[:hole[0]] + b'__expected_hole__'
                                 + assertion.encode()[hole[1]:] + original[hi:])
                    if (pending['id'], signature) in seen:
                        continue
                    seen.add((pending['id'], signature))
                    args, origins = _inputs(source, index, unit, statement, root, pending)
                    cid = _id('observation_projection', pending['id'], actual, template['capsule']['id'])
                    row = copy.deepcopy(pending)
                    row.update(id=cid, candidate_id=cid, arg=args, preview_body=body,
                               pre=copy.deepcopy(pending.get('pre', [])) + [oracle.encode_value(template['seed'])],
                               source_test_ids=sorted(set(pending['source_test_ids']) | {template['record']['id']}),
                               observations=[{'text': actual, 'predicate': template['capsule']['predicate'],
                                              'expected_source': template['expected_provenance'],
                                              **({'go_type': hint} if hint else {})}],
                               semantic_status='requires_observation_projection_transformer')
                    row['projection'] = {
                        'action_candidate_id': pending['id'], 'source_capsule_id': template['capsule']['id'],
                        'action_context_id': pending['context']['id'],
                        'source_test_id': template['record']['id'], 'source_observation': template['source'].text(template['observed']),
                        'source_root': template['source'].text(template['root']['nodes'][0]), 'target_root': replacement,
                        'types': sorted(set(template['root']['types']) & set(root['types'])),
                        'constructor_origins': sorted(set(template['root']['origins']) & set(root['origins'])),
                        'expected_hole': {'start_byte': lo + hole[0], 'end_byte': lo + hole[1]},
                        'seed_literal': literal, 'source_expected_slot': len(row['pre']) - 1,
                        'input_sources': origins, 'terminal_observation_only': True,
                        'semantic_status': 'source_backed; applicability_and_expected_relation_unproved',
                    }
                    candidates.append(row)
                    count += 1
                except (ValueError, KeyError, TypeError) as exc:
                    skipped[str(exc)] += 1
                if count >= budget.projections_per_action or len(candidates) >= budget.max_candidates:
                    break
            if count >= budget.projections_per_action or len(candidates) >= budget.max_candidates:
                break
        if len(candidates) >= budget.max_candidates:
            break
    return _result(candidates, templates, skipped, attempts, budget)


def _result(candidates, templates, skipped, attempts, budget):
    return {'algorithm': 'typed_source_observation_projection_v1', 'budget': asdict(budget),
            'candidates': candidates, 'counts': {'templates': len(templates), 'attempts': attempts, 'candidates': len(candidates)},
            'skipped': dict(skipped), 'reference_inputs': False, 'execution_outcomes': False}


def materialize_projection(corpus, candidate, completion):
    """Fill only the program-owned expected hole with a revalidated oracle literal."""
    if completion.get('candidate_id') != candidate['candidate_id']:
        raise ValueError('completion_candidate_mismatch')
    result = oracle.validate_completions({'completions': [{
        'candidate_id': completion.get('candidate_id'), 'observe': completion.get('observe'),
        'expected': completion.get('expected_expr'), 'guard': completion.get('guard_expr'),
    }]}, [candidate])
    if not result['accepted']:
        raise ValueError('completion_not_valid:' + result['rejected'][0]['code'])
    accepted = result['accepted'][0]
    if completion.get('literal') != accepted['literal']:
        raise ValueError('completion_literal_mismatch')
    parent, projection = corpus['tests'][candidate['base_test_id']], candidate['projection']
    raw, position = candidate['preview_body'].encode(), projection['expected_hole']
    lo, hi = position['start_byte'], position['end_byte']
    if not 0 <= lo <= hi <= len(raw) or raw[lo:hi].decode() != projection['seed_literal']:
        raise ValueError('projection_expected_hole_mismatch')
    body = (raw[:lo] + accepted['literal'].encode() + raw[hi:]).decode()
    validation = validate_body(corpus, parent['id'], body)
    if validation['status'] == 'unsupported':
        raise ValueError(validation['reason'])
    return {'id': _id(candidate['id'], body), 'base_test_id': parent['id'],
            'source_test_ids': candidate['source_test_ids'], 'language': corpus['language'],
            'kind': 'observation_projection', 'rule_id': candidate['id'], 'imports': candidate['context'].get('imports', []),
            'edits': [{'span': parent['body_span'], 'before': source_text(corpus, parent['body_span']), 'after': body}],
            'oracle': {'mode': 'observation_projection_transformer', 'completion': accepted,
                       'source_test_id': parent['id'], 'semantic_status': 'model_hypothesis_requires_independent_evaluation'},
            'provenance': {'projection': projection, 'action_context': candidate['context'],
                           'pre': candidate['pre'], 'arg': candidate['arg'], 'binding_analysis': validation}}
