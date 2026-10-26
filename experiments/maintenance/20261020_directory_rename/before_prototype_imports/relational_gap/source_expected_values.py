"""Recover primitive expected constants behind source-local names.

Only unique, direct, prior local definitions and immutable primitive literals
are interpreted. The test/subject is never executed. This supplies source
values to the semantic expression environment; it does not justify a new
oracle or authorize a new edit location.
"""
from __future__ import annotations

from anchor_retrieval.syntax import FUNCTIONS, Source, child, walk
from experimental.semantic_transport.oracle import OracleError, Unknown, encode_value, parse_source_literal
from generic_composition.corpus import ASSIGNMENTS


def _inside(position, outer):
    return position['path'] == outer['path'] and outer['start_byte'] <= position['start_byte'] <= position['end_byte'] <= outer['end_byte']


def _overlap(a, b):
    return a['path'] == b['path'] and max(a['start_byte'], b['start_byte']) < min(a['end_byte'], b['end_byte'])


def _span(path, node):
    return {'path': path, 'start_byte': node.start_byte, 'end_byte': node.end_byte}


def resolve_expected_constant(corpus, test_id, expected_span, *, edits=(), cache=None):
    test = corpus['tests'][test_id]
    path = expected_span['path']
    metadata = corpus['sources'][path]
    language = metadata.get('language', corpus['language'])
    cache = {} if cache is None else cache
    if path not in cache:
        source = Source(path, metadata['code'], language)
        cache[path] = source, {(n.start_byte, n.end_byte): n for n in walk(source.root)}
    source, nodes = cache[path]
    body = nodes.get((test['body_span']['start_byte'], test['body_span']['end_byte']))
    expression = nodes.get((expected_span['start_byte'], expected_span['end_byte']))
    unknown = lambda reason: {'known': False, 'reason': reason}
    if source.root.has_error or body is None or expression is None or not _inside(expected_span, test['span']):
        return unknown('expected_source_scope_unavailable')
    owner = expression.parent
    while owner is not None and owner != body:
        if owner.type in FUNCTIONS | {'arrow_function', 'function_expression', 'func_literal', 'lambda',
                                     'class_definition', 'class_declaration'}:
            return unknown('expected_use_crosses_nested_binding_scope')
        owner = owner.parent
    if owner != body:
        return unknown('expected_use_outside_direct_test_scope')
    declarations, definition_nodes, unsafe = {}, {}, set()
    for node in walk(body):
        if node.type in ASSIGNMENTS | {'var_spec', 'const_spec', 'assignment_expression',
                                      'augmented_assignment_expression', 'named_expression'}:
            target = child(node, 'left', 'name')
            if target is None:
                continue
            while target.type in {'expression_list', 'pattern_list'} and len(target.named_children) == 1:
                target = target.named_children[0]
            names = [source.text(n) for n in walk(target)
                     if n.type in {'identifier', 'shorthand_property_identifier_pattern'}]
            for name in names:
                declarations.setdefault(name, []).append(node)
            if target.type == 'identifier':
                definition_nodes[id(node)] = child(node, 'right', 'value')
        elif node.type in {'update_expression', 'inc_statement', 'dec_statement', 'global_statement', 'nonlocal_statement'}:
            unsafe.update(source.text(n) for n in walk(node) if n.type == 'identifier')
        elif node.type in {'as_pattern', 'as_pattern_target', 'case_pattern', 'catch_clause'}:
            unsafe.update(source.text(n) for n in walk(node) if n.type == 'identifier')
        elif node.type in {'unary_expression', 'unary_operator'} and source.text(node).lstrip().startswith('&'):
            unsafe.update(source.text(n) for n in walk(node) if n.type == 'identifier')
        elif node.type in {'for_statement', 'for_in_statement', 'range_clause'}:
            target = child(node, 'left')
            if target is not None:
                unsafe.update(source.text(n) for n in walk(target) if n.type == 'identifier')
    positions, seen = [], set()
    at = expected_span['start_byte']
    for _ in range(16):
        text = source.text(expression)
        try:
            value = parse_source_literal(text, language)
        except (OracleError, ValueError, TypeError):
            value = Unknown('source_expression_not_literal')
        if not isinstance(value, Unknown):
            if type(value) not in {str, bytes, int, float, bool, type(None)}:
                return unknown('expected_mutable_or_compound_value')
            return {'known': True, 'value': encode_value(value), 'source_spans': positions,
                    'basis': 'unique_prior_local_primitive_literal', 'reflection_and_external_mutation': 'not_modelled'}
        while expression.type in {'parenthesized_expression', 'expression_list'} and len(expression.named_children) == 1:
            expression = expression.named_children[0]
        if expression.type != 'identifier':
            return unknown('expected_expression_not_local_literal_alias')
        name = source.text(expression)
        if name in unsafe or name in seen or len(declarations.get(name, ())) != 1:
            return unknown('expected_binding_nonunique_or_mutable')
        seen.add(name)
        declaration = declarations[name][0]
        value_node = definition_nodes.get(id(declaration))
        owner = declaration.parent
        while owner is not None and owner.type in {'expression_statement', 'lexical_declaration', 'variable_declaration',
                                                    'var_declaration', 'const_declaration', 'var_spec_list', 'const_spec_list',
                                                    'statement_list'}:
            owner = owner.parent
        if owner != body or declaration.end_byte > at or value_node is None:
            return unknown('expected_definition_not_prior_direct_local')
        position = _span(path, declaration)
        if any(_overlap(position, edit['span']) for edit in edits):
            return unknown('expected_definition_is_edited')
        positions.append(position)
        at = declaration.start_byte
        expression = value_node
    return unknown('expected_alias_depth_budget')
