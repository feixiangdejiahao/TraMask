"""Source-backed oracle-helper call instances, without helper-name templates.

The corpus has already resolved helper assertions and actual/formal bindings.
This adapter uses those facts, accepts only direct expression statements with
literal/caller-parameter arguments, and keeps the real parent test as the edit
and execution context. It neither executes helpers nor claims effect isolation.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json

from anchor_retrieval.syntax import CALLS, Source, child, walk
from experimental.generic_v2.bindings import _Index, analyze_bindings
from experimental.generic_v2.generate import _binding_labels, _refine, _roles
from experimental.generic_v3.alignment import align_analogy
from generic_composition.corpus import source_text
from generic_composition.terms import BudgetExceeded, SourceTerm, Span, Term, from_source, render, subterms


def _id(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:24]


def _span(source, node):
    return {'path': source.path, 'start_byte': node.start_byte, 'end_byte': node.end_byte,
            'line': node.start_point.row + 1, 'end_line': node.end_point.row + 1}


def _contains(outer, inner):
    return outer['start_byte'] <= inner.start_byte and inner.end_byte <= outer['end_byte']


def _one_statement_tree(source, statement, max_nodes):
    converted = from_source(source, statement, max_nodes=max_nodes)
    # Only an ordered-list representation adapter: the one child is the exact
    # original statement, with every original byte span retained.
    positions = {(): Span(statement.start_byte, statement.end_byte)}
    positions.update({(0,) + path: span for path, span in converted.spans.items()})
    return SourceTerm(Term('module', children=(converted.term,)), positions,
                      source.path, source.text(statement)), converted


_GO_CONSTANTS = {'int_literal', 'float_literal', 'imaginary_literal', 'rune_literal',
                 'interpreted_string_literal', 'raw_string_literal', 'true', 'false', 'nil'}
_GO_TYPES = {'bool', 'byte', 'complex64', 'complex128', 'float32', 'float64', 'int',
             'int8', 'int16', 'int32', 'int64', 'rune', 'string', 'uint', 'uint8',
             'uint16', 'uint32', 'uint64', 'uintptr'}


def _argument_reason(source, node, test, bindings):
    """Check source closure, not runtime purity or aggregate/type correctness."""
    if node.type == 'identifier':
        name = source.text(node)
        binding, status, _ = bindings.resolve(name, node)
        if name not in test['parameters']:
            return 'argument_requires_external_local_state_or_computation'
        if status != 'available' or binding is None or binding.kind != 'parameter':
            return 'caller_parameter_not_available_as_original_binding'
        for written_name, write, pos in bindings.writes:
            target, _, _ = bindings.resolve(written_name, write)
            if target and target.id == binding.id and binding.node.start_byte < pos < node.start_byte:
                return 'caller_parameter_reassigned_before_instance'
        return None
    if source.language != 'go':
        return 'argument_requires_external_local_state_or_computation'
    if node.type in _GO_CONSTANTS:
        return None
    if node.type in {'literal_element', 'parenthesized_expression'} and len(node.named_children) == 1:
        return _argument_reason(source, node.named_children[0], test, bindings)
    if node.type == 'unary_expression':
        operator, operand = child(node, 'operator'), child(node, 'operand')
        if operator and operand and (source.text(operator) in {'+', '-'} or
                                     (source.text(operator) == '&' and operand.type == 'composite_literal')):
            return _argument_reason(source, operand, test, bindings)
    if node.type == 'call_expression':
        callee, args = child(node, 'function'), child(node, 'arguments')
        if callee and callee.type == 'identifier' and source.text(callee) in _GO_TYPES and args and len(args.named_children) == 1:
            # The language spelling alone is insufficient when locally shadowed.
            binding, _, _ = bindings.resolve(source.text(callee), callee)
            shadow_types = any(n.type in {'type_spec', 'type_alias'} and child(n, 'name') is not None
                               and source.text(child(n, 'name')) == source.text(callee) for n in walk(source.root))
            if binding is None and not shadow_types:
                return _argument_reason(source, args.named_children[0], test, bindings)
        return 'argument_call_is_not_an_unshadowed_predeclared_conversion'
    if node.type in {'composite_literal', 'literal_value'}:
        typ = child(node, 'type')
        body = child(node, 'body') if typ is not None else node
        struct_keys = typ is not None and typ.type == 'struct_type'
        if typ is not None and typ.type == 'type_identifier':
            # Resolve only an unambiguous same-file top-level declaration. An
            # imported type or competing local declaration remains unknown.
            specs = [n for n in walk(source.root) if n.type in {'type_spec', 'type_alias'}
                     and child(n, 'name') is not None and source.text(child(n, 'name')) == source.text(typ)]
            if len(specs) == 1 and specs[0].parent.parent == source.root:
                declared_type = child(specs[0], 'type')
                struct_keys = declared_type is not None and declared_type.type == 'struct_type'
        if body is not None:
            for item in body.named_children:
                children = list(item.named_children) if item.type == 'keyed_element' else [item]
                if item.type == 'keyed_element' and struct_keys:
                    key = child(item, 'key')
                    if key and len(key.named_children) == 1 and key.named_children[0].type == 'identifier':
                        children = [child(item, 'value')]
                for value in children:
                    reason = _argument_reason(source, value, test, bindings)
                    if reason:
                        return reason
            return None
    return 'argument_requires_external_local_state_or_computation'


def _helper_binding_reason(source, call, test, mappings, bindings):
    callee = child(call, 'function')
    if callee is None or callee.type != 'identifier':
        return 'helper_callee_binding_not_proved'
    binding, status, reason = bindings.resolve(source.text(callee), callee)
    if binding is None or binding.kind != 'function' or (status != 'available' and reason != 'deferred_outer_definition'):
        return 'helper_callee_binding_not_proved'
    definitions = {h['id']: h['span'] for h in test.get('support', {}).get('helpers', [])}
    if any(m['helper_id'] not in definitions or
           definitions[m['helper_id']]['path'] != source.path or
           not _contains(definitions[m['helper_id']], binding.node) for m in mappings):
        return 'helper_mapping_does_not_match_lexical_definition'
    for name, write, pos in bindings.writes:
        target, _, _ = bindings.resolve(name, write)
        if target and target.id == binding.id and binding.node.start_byte < pos < call.start_byte:
            return 'helper_callee_reassigned_before_instance'
    return None


def extract(corpus, *, max_instances=4096, max_nodes=1500):
    """Return private instance records plus explicit unsupported reasons.

    ``tree`` is a SourceTerm for composition, not JSON; ``helper_assertions`` and
    ``ports`` retain JSON source evidence from the existing corpus. Instance IDs
    distinguish calls even when A/B/C have exactly the same parent test ID.
    """
    if type(max_instances) is not int or max_instances < 1:
        raise ValueError('max_instances must be positive')
    cache, records, rejected, skipped, seen = {}, [], [], Counter(), set()
    capsules = sorted(corpus['capsules'], key=lambda c: (
        c.get('retrieval_rank') or 99999, c['test_id'], c['assertion_span']['start_byte']))
    for capsule in capsules:
        mappings = capsule.get('helper_assertions', [])
        if not mappings:
            continue
        test = corpus['tests'][capsule['test_id']]
        position = capsule['assertion_span']
        location = (test['id'], position['start_byte'], position['end_byte'])
        if location in seen:
            continue
        seen.add(location)

        def reject(reason):
            skipped[reason] += 1
            rejected.append({'capsule_id': capsule['id'], 'parent_test_id': test['id'],
                             'span': position, 'reason': reason})

        if len(records) >= max_instances:
            reject('instance_budget')
            continue
        metadata = corpus['sources'][position['path']]
        if not metadata.get('complete_file', True) or metadata.get('parse_error'):
            reject('incomplete_or_unparseable_source')
            continue
        if test.get('parameterization_status', 'none_detected') != 'none_detected':
            reject('parent_parameter_rows_require_instantiation')
            continue
        if any(m.get('binding_status') != 'resolved' for m in mappings):
            reject('helper_argument_binding_unknown')
            continue
        if position['path'] not in cache:
            source = Source(position['path'], metadata['code'], corpus['language'])
            nodes = {}
            for node in walk(source.root):
                nodes.setdefault((node.start_byte, node.end_byte), []).append(node)
            cache[position['path']] = source, nodes, _Index(source)
        source, nodes, bindings = cache[position['path']]
        call = next((n for n in nodes.get((position['start_byte'], position['end_byte']), [])
                     if n.type in CALLS), None)
        statement = call.parent if call is not None else None
        if statement is None or statement.type != 'expression_statement' or statement.named_children != [call]:
            reject('not_a_standalone_expression_statement')
            continue
        body_span = test['body_span']
        body = next((n for n in nodes.get((body_span['start_byte'], body_span['end_byte']), [])
                     if n.type in {'block', 'statement_block'}), None)
        parent = statement.parent
        if parent is not None and parent.type == 'statement_list':
            parent = parent.parent  # Transparent Go grammar node, not control flow.
        if body is None or parent != body:
            reject('not_a_direct_parent_test_statement')
            continue
        helper_reason = _helper_binding_reason(source, call, test, mappings, bindings)
        if helper_reason:
            reject(helper_reason)
            continue
        origins = {}
        for mapping in mappings:
            for bound in mapping['argument_bindings']:
                actual = bound['actual']
                origins[(actual['span']['start_byte'], actual['span']['end_byte'])] = actual
        invalid = None
        for actual in origins.values():
            if actual.get('literal_known'):
                continue
            p = actual['span']
            node = next((n for n in nodes.get((p['start_byte'], p['end_byte']), [])
                         if n.type == actual['kind']), None)
            if node is None:
                invalid = 'argument_requires_external_local_state_or_computation'
                break
            invalid = _argument_reason(source, node, test, bindings)
            if invalid:
                break
        if invalid:
            reject(invalid)
            continue
        try:
            tree, original = _one_statement_tree(source, statement, max_nodes)
        except BudgetExceeded:
            reject('instance_node_budget')
            continue
        ports = []
        for mapping in mappings:
            observed = {b['parameter'] for b in mapping['observed_parameter_origins']}
            expected = {b['parameter'] for b in mapping['expected_parameter_origins']}
            for bound in mapping['argument_bindings']:
                roles = [role for role, names in [('observed', observed), ('expected', expected)]
                         if bound['parameter'] in names]
                ports.append({'helper_id': mapping['helper_id'], 'helper_assertion_span': mapping['assertion_span'],
                              'parameter': bound['parameter'], 'slot': bound['slot'], 'keyword': bound.get('keyword'),
                              'roles': roles or ['context'], 'actual': bound['actual']})
        role_map = {}
        for path, _ in subterms(tree.term, max_nodes=max_nodes):
            span = tree.spans[path]
            roles = {(role, port['helper_id'], port['parameter']) for port in ports
                     if _contains(port['actual']['span'], span)
                     for role in port['roles'] if role != 'context'}
            if roles:
                role_map[path] = tuple(sorted(roles))
        scope = test['enclosing_scope_span']
        helper_ids = tuple(sorted({m['helper_id'] for m in mappings}))
        records.append({'instance_id': _id('helper_assertion_instance', location, helper_ids),
                        'parent_test_id': test['id'], 'test': test, 'language': corpus['language'],
                        'span': _span(source, statement), 'call_span': _span(source, call),
                        'text': source.text(statement), 'tree': tree,
                        'capsule_ids': [capsule['id']], 'helper_ids': helper_ids,
                        'helper_assertions': mappings, 'ports': ports,
                        'bindings': {(0,) + p: label for p, label in
                                     _binding_labels(source, statement, original, test['parameters']).items()},
                        'literal_roles': role_map,
                        'group_key': (scope['path'], scope['start_byte'], scope['end_byte'],
                                      tuple(test['parameters']), helper_ids),
                        'unproved': ['helper_and_caller_parameter_effects', 'aliasing', 'oracle_applicability']})
    return {'instances': records, 'unsupported': rejected, 'skipped': dict(skipped)}


def compose(corpus, A, B, C, *, max_nodes=1500, max_holes=32, refine=_refine,
            mechanical_cache=None, source_cache=None):
    """Use the existing v3 kernel and emit a replacement of C's statement only.

    This small adapter does not perform a new search. A driver may use the same
    ranked/budgeted triple enumeration over ``instance_id`` instead of test ID.
    """
    if len({r['instance_id'] for r in (A, B, C)}) != 3:
        return {'status': 'unsupported', 'reason': 'three_distinct_instances_required'}
    if A['group_key'] != B['group_key'] or A['group_key'] != C['group_key']:
        return {'status': 'unsupported', 'reason': 'different_helper_or_lexical_interface'}
    try:
        records = [refine(r, max_nodes) for r in (A, B, C)]
        result = align_analogy(*(r['tree'] for r in records), roles=_roles(*records),
                               max_nodes=max_nodes, max_holes=max_holes)
    except BudgetExceeded:
        return {'status': 'unsupported', 'reason': 'instance_node_budget'}
    if result.status != 'hypothesis':
        return {'status': 'unsupported', 'reason': result.reason, 'provenance': result.provenance}
    after = render(result.output)
    before = source_text(corpus, C['span'])
    mechanical_cache = {} if mechanical_cache is None else mechanical_cache
    source_cache = {} if source_cache is None else source_cache
    path = C['span']['path']
    if path not in source_cache:
        source_cache[path] = Source(path, corpus['sources'][path]['code'], corpus['language'])
    key = (C['parent_test_id'], C['span']['start_byte'], C['span']['end_byte'], after)
    if key not in mechanical_cache:
        mechanical_cache[key] = analyze_bindings(source_cache[path], corpus['language'], C['span']['start_byte'], after,
                                                end_byte=C['span']['end_byte'])
    mechanical = mechanical_cache[key]
    if mechanical['status'] == 'invalid':
        return {'status': 'unsupported', 'reason': 'mechanically_invalid_instance', 'binding_analysis': mechanical}
    triple = [r['instance_id'] for r in (A, B, C)]
    rid = _id('assertion_instance_analogy', triple)
    sources = {name: {'test_id': r['parent_test_id'], 'instance_id': r['instance_id'],
                      'span': r['span'], 'text': r['text']} for name, r in zip('ABC', (A, B, C))}
    candidate = {'id': _id(rid, after), 'base_test_id': C['parent_test_id'],
                 'source_test_ids': list(dict.fromkeys(r['parent_test_id'] for r in (A, B))),
                 'language': corpus['language'], 'kind': 'assertion_instance_analogy', 'rule_id': rid,
                 'imports': [], 'edits': [{'span': C['span'], 'before': before, 'after': after}],
                 'oracle': {'mode': 'transport_from_source', 'source_test_id': B['parent_test_id'],
                            'binding_source_test_id': C['parent_test_id'],
                            'assertion_ids': B['capsule_ids'], 'semantic_status': 'requires_admission'},
                 'provenance': dict(result.provenance, sources=sources,
                                    source_assertion_ports={name: r['ports'] for name, r in zip('ABC', (A, B, C))},
                                    binding_analysis=mechanical)}
    rule = {'id': rid, 'kind': candidate['kind'], 'before_span': A['span'], 'after_span': B['span'],
            'semantic_status': 'hypothesis_from_test_edit'}
    return {'status': 'hypothesis', 'candidate': candidate, 'rule': rule}
