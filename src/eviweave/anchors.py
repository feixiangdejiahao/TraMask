"""Deterministic, syntactic candidates for a later dependence slice.

Names prioritize slice seeds, not evidence eligibility. Unmatched or unparsed
material remains in B's complete candidate list. No task classifier, manual
evidence, verifier, or model call participates in locating seeds.
"""
from bisect import bisect_right
import codecs
from functools import lru_cache
from pathlib import PurePosixPath
import re


IDENTIFIER = re.compile(r'[A-Za-z_$][A-Za-z_0-9$]*')
SUFFIXES = {'.py', '.go', '.rs', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts'}
FUNCTIONS = {'function_definition', 'function_declaration', 'method_declaration',
             'function_item', 'method_definition', 'generator_function_declaration'}
DECLARATIONS = FUNCTIONS | {'class_definition', 'class_declaration', 'type_spec',
                            'struct_item', 'enum_item', 'trait_item', 'interface_declaration',
                            'type_alias_declaration'}
STRINGS = {'string', 'raw_string_literal', 'interpreted_string_literal',
           'string_literal', 'template_string', 'char_literal'}


@lru_cache(maxsize=None)
def _parser(suffix):
    from tree_sitter import Language, Parser
    if suffix == '.py':
        import tree_sitter_python
        grammar = tree_sitter_python.language()
    elif suffix == '.go':
        import tree_sitter_go
        grammar = tree_sitter_go.language()
    elif suffix == '.rs':
        import tree_sitter_rust
        grammar = tree_sitter_rust.language()
    else:
        import tree_sitter_typescript
        grammar = (tree_sitter_typescript.language_tsx() if suffix in {'.tsx', '.jsx'}
                   else tree_sitter_typescript.language_typescript())
    return Parser(Language(grammar))


def _text(raw, node):
    return raw[node.start_byte:node.end_byte].decode()


def _call_name(raw, node):
    function = node.child_by_field_name('function')
    if node.type == 'new_expression':
        function = node.child_by_field_name('constructor')
    if function is None:
        return None
    while function.type == 'generic_function':
        function = function.child_by_field_name('function')
    if function.type in {'identifier', 'type_identifier'}:
        return _text(raw, function)
    for field in ('attribute', 'field', 'property', 'name'):
        member = function.child_by_field_name(field)
        if member is not None and member.type in {'identifier', 'field_identifier',
                                                  'property_identifier', 'type_identifier'}:
            return _text(raw, member)
    # Calls through a computed expression remain unresolved, rather than
    # interpreting text in a generic argument/string as an API name.
    return None


def js_test_registration(raw, node):
    """Identify JS test/suite registration, including modifiers and each chains."""
    if node.type != 'call_expression':
        return None
    callee = node.child_by_field_name('function')
    arguments = node.child_by_field_name('arguments')
    if callee is None or arguments is None:
        return None
    text = _text(raw, callee)
    match = re.match(r'^(describe|suite|context|it|test|specify)(?:\.|\(|$)', text)
    values = arguments.named_children
    if match and values and (any(v.type in {'arrow_function', 'function_expression'} for v in values)
                             or '.todo' in text):
        return match[1]
    return None


def parse_source(path, raw):
    """Index calls, other names and literal carriers in lexical source units.

    A unit is an outer function/method, a JS test registration, or a top-level
    statement. Nested helpers stay in their enclosing function. A source with
    a syntax error is recorded, without indexing its recovered syntax tree.
    """
    root = _parser(PurePosixPath(path).suffix).parse(raw).root_node
    declarations, units, errors = [], [], []
    if root.has_error:
        todo = [root]
        while todo:
            node = todo.pop()
            if node.is_error or node.is_missing:
                errors.append({'start': node.start_byte, 'end': node.end_byte,
                               'line': node.start_point.row + 1, 'kind': node.type})
            todo.extend(reversed(node.children))
        return {'units': [], 'declarations': [], 'parse_errors': errors}

    def visit(node, current=None, owner=None):
        name = node.child_by_field_name('name')
        if node.type in {'class_definition', 'class_declaration', 'struct_item', 'trait_item', 'interface_declaration'}:
            owner = _text(raw, name) if name is not None else None
        elif node.type == 'impl_item':
            type_node = node.child_by_field_name('type')
            owner = _text(raw, type_node) if type_node is not None else None
        declaration_owner = owner
        if node.type == 'method_declaration':
            receiver = node.child_by_field_name('receiver')
            if receiver is not None:
                identifiers = re.findall(r'[A-Za-z_][A-Za-z_0-9]*', _text(raw, receiver))
                declaration_owner = identifiers[-1] if identifiers else None
        if node.type in DECLARATIONS and name is not None:
            declaration = node.parent if node.parent.type == 'decorated_definition' else node
            declarations.append({'name': _text(raw, name), 'start': declaration.start_byte,
                                 'end': declaration.end_byte, 'first_line': declaration.start_point.row + 1,
                                 'last_line': declaration.end_point.row + 1,
                                 'kind': node.type, 'owner': declaration_owner})
        call_name = _call_name(raw, node) if node.type in {'call', 'call_expression', 'new_expression'} else None
        registration = js_test_registration(raw, node) in {'test', 'it', 'specify'}
        outer_function = node.type in FUNCTIONS and (current is None or current['kind'] == 'statement')
        if registration or outer_function:
            current = None
        if current is None and not node.has_error and node.type not in {
            'module', 'source_file', 'program', 'class_definition', 'class_declaration',
            'class_body', 'block', 'declaration_list', 'impl_item', 'mod_item',
            'comment', 'line_comment', 'block_comment', 'decorated_definition'}:
            current = {'start': node.start_byte, 'end': node.end_byte,
                       'first_line': node.start_point.row + 1, 'last_line': node.end_point.row + 1,
                       'name': _text(raw, name) if name is not None else '<' + node.type + '>',
                       'kind': 'function' if node.type in FUNCTIONS or registration else 'statement',
                       'calls': {}, 'uses': {}, 'literals': {},
                       'members': {}, 'keys': {}, 'jsx': {}, 'input_literals': {}, 'defines': []}
            units.append(current)
        if current is not None:
            if node.type in FUNCTIONS and node.start_byte == current['start'] and name is not None:
                current['defines'].append(_text(raw, name))
            if node.type == 'variable_declarator':
                value = node.child_by_field_name('value')
                container = node.parent
                if container.parent is not None and container.parent.type == 'export_statement':
                    container = container.parent
                if (value is not None and value.type in {'arrow_function', 'function_expression'}
                        and name is not None and current['start'] == container.start_byte):
                    current['name'] = _text(raw, name)
                    current['defines'].append(_text(raw, name))
            if current['kind'] == 'statement':
                if node.type in {'assignment', 'augmented_assignment', 'named_expression'}:
                    left = node.child_by_field_name('left') or node.child_by_field_name('name')
                    if left is not None and left.type == 'identifier':
                        current['defines'].append(_text(raw, left))
                elif node.type in {'variable_declarator', 'const_item', 'static_item', 'var_spec'}:
                    binding = node.child_by_field_name('name')
                    if binding is not None and binding.type == 'identifier':
                        current['defines'].append(_text(raw, binding))
                elif node.type in {'import_statement', 'import_from_statement', 'use_declaration'}:
                    todo = list(node.named_children)
                    while todo:
                        child = todo.pop()
                        if child.type in {'identifier', 'type_identifier'}:
                            current['defines'].append(_text(raw, child))
                        elif child.type not in STRINGS:
                            todo.extend(child.named_children)
                elif node.type == 'import_spec':
                    alias = node.child_by_field_name('name')
                    path_node = node.child_by_field_name('path')
                    if alias is not None:
                        current['defines'].append(_text(raw, alias))
                    elif path_node is not None:
                        current['defines'].append(_text(raw, path_node).strip('"`').split('/')[-1])
            if call_name is not None:
                current['calls'].setdefault(call_name, []).append([node.start_byte, node.end_byte])
            if node.type in STRINGS:
                words = sorted(set(IDENTIFIER.findall(_text(raw, node))))
                for word in words:
                    current['literals'].setdefault(word, []).append([node.start_byte, node.end_byte])
                parent = node.parent
                # A string used as an index or object key is an observed or
                # configured field, not just arbitrary test input text.
                is_key = parent is not None and (
                    parent.type in {'subscript', 'subscript_expression', 'index_expression'}
                    and parent.named_children[-1] == node
                    or parent.type in {'pair', 'property_assignment'}
                    and parent.child_by_field_name('key') == node)
                if is_key:
                    for word in words:
                        current['keys'].setdefault(word, []).append([parent.start_byte, parent.end_byte])
                is_label = False
                if parent is not None and parent.type in {'arguments', 'argument_list'}:
                    registration_call = parent.parent
                    registration_name = (_call_name(raw, registration_call)
                                         if registration_call.type in {'call', 'call_expression'} else None)
                    is_label = registration_name in {'test', 'it', 'specify', 'describe', 'suite', 'context'} and parent.named_children[0] == node
                is_docstring = parent is not None and parent.type == 'expression_statement'
                if not is_label and not is_docstring:
                    for word in words:
                        current['input_literals'].setdefault(word, []).append([node.start_byte, node.end_byte])
                return [(child,current,owner) for child in node.named_children
                        if child.type in {'interpolation','template_substitution'}]
            if node.type in {'identifier', 'field_identifier', 'property_identifier',
                             'shorthand_property_identifier', 'shorthand_property_identifier_pattern',
                             'type_identifier'}:
                parent = node.parent
                declares = parent is not None and parent.type in DECLARATIONS and parent.child_by_field_name('name') == node
                if not declares:
                    current['uses'].setdefault(_text(raw, node), []).append([node.start_byte, node.end_byte])
                    word = _text(raw, node)
                    if parent is not None:
                        if parent.type in {'attribute', 'selector_expression', 'field_expression', 'member_expression'}:
                            member = next((parent.child_by_field_name(field) for field in ('attribute', 'field', 'property')
                                           if parent.child_by_field_name(field) is not None), None)
                            if member == node:
                                current['members'].setdefault(word, []).append([parent.start_byte, parent.end_byte])
                        if parent.type in {'pair', 'pair_pattern', 'property_assignment', 'property_signature',
                                           'field_declaration', 'field_definition', 'keyword_argument'}:
                            key = parent.child_by_field_name('key') or parent.child_by_field_name('name')
                            if key == node:
                                current['keys'].setdefault(word, []).append([parent.start_byte, parent.end_byte])
                        if parent.type in {'jsx_opening_element', 'jsx_self_closing_element'} and parent.child_by_field_name('name') == node:
                            current['jsx'].setdefault(word, []).append([parent.start_byte, parent.end_byte])
        return [(child,current,owner) for child in node.named_children]
    todo=[(root,None,None)]
    while todo:
        node,current,owner=todo.pop()
        todo.extend(reversed(visit(node,current,owner)))
    return {'units': units, 'declarations': declarations, 'parse_errors': errors}


def changed_lines(patch):
    """Map Git diff paths to new lines, including both boundaries of a deletion."""
    changes, deletions = {}, {}
    path, line, in_hunk = None, 0, False
    for text in patch.splitlines():
        if text.startswith('diff --git '):
            path, in_hunk = None, False
        elif text.startswith('@@ '):
            match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', text)
            old_left = int(match[2]) if match[2] is not None else 1
            new_left = int(match[4]) if match[4] is not None else 1
            line = int(match[3])
            in_hunk = old_left > 0 or new_left > 0
        elif in_hunk:
            if text.startswith('+'):
                if path != '/dev/null':
                    changes[path].add(line)
                line += 1
                new_left -= 1
            elif text.startswith('-'):
                if path != '/dev/null':
                    changes[path].add(max(1, line))
                    deletions[path].add(max(1, line))
                old_left -= 1
            elif text.startswith(' '):
                line += 1
                old_left -= 1
                new_left -= 1
            if old_left == 0 and new_left == 0:
                in_hunk = False
        elif text.startswith('+++ '):
            header = text[4:]
            if header.startswith('"'):
                encoded = re.match(r'"((?:\\.|[^"\\])*)"', header)[1].encode()
                header = codecs.escape_decode(encoded)[0].decode()
            else:
                header = header.split('\t', 1)[0]
            path = header.removeprefix('b/')
            if path != '/dev/null':
                changes.setdefault(path, set())
                deletions.setdefault(path, set())
    for path in changes:
        for position in deletions[path]:
            changes[path].add(max(1, position - 1))
    return changes


def test_path(path):
    parts = PurePosixPath(path).parts
    filename = PurePosixPath(path).name
    return (PurePosixPath(path).stem in {'tests', 'specs'}
            or any(re.search(r'^(?:tests?|specs?|__tests__)$', part, re.I) for part in parts)
            or bool(re.search(r'(?:^test_|_test\.|[.]test[.]|[.]spec[.])', filename)))


def focused_names(issue, changes, final_sources, all_sources, *, family=False):
    """Use issue code, changed declarations and operations, rather than body locals."""
    names = set(IDENTIFIER.findall('\n'.join(re.findall(r'`+([^`]+)`+', issue))))
    owners = set()
    for path, raw, parsed in final_sources:
        lines = changes[path]
        declarations = parsed['declarations']
        for line in lines:
            enclosing = [d for d in declarations if d['first_line'] <= line <= d['last_line']]
            if enclosing and not test_path(path):
                nearest = min(enclosing, key=lambda d: d['end'] - d['start'])
                names.add(nearest['name'])
                if nearest['owner']:
                    owners.add(nearest['owner'])
                    names.add(nearest['owner'])
        starts = [0] + [match.end() for match in re.finditer(b'\n', raw)]
        for unit in parsed['units']:
            for kind in ('calls', 'members', 'keys'):
                for name, spans in unit[kind].items():
                    if any(bisect_right(starts, start) in lines for start, _ in spans):
                        names.add(name)
    if family:
        for source in all_sources:
            for declaration in source['parsed']['declarations']:
                if declaration['owner'] in owners:
                    names.add(declaration['name'])
    return sorted(names)


def target_names(issue, patch, changed_sources):
    """Issue code spans + changed identifiers + enclosing changed declarations."""
    code = re.findall(r'`+([^`]+)`+', issue)
    names = set(IDENTIFIER.findall('\n'.join(code)))
    changes = changed_lines(patch)
    for path, raw, parsed in changed_sources:
        lines = changes[path]
        for declaration in parsed['declarations']:
            if any(declaration['first_line'] <= line <= declaration['last_line'] for line in lines):
                names.add(declaration['name'])
        todo = [_parser(PurePosixPath(path).suffix).parse(raw).root_node]
        while todo:
            node = todo.pop()
            if node.start_point.row + 1 in lines and node.type in {
                'identifier', 'field_identifier', 'property_identifier',
                'shorthand_property_identifier', 'type_identifier'}:
                names.add(_text(raw, node))
            todo.extend(node.named_children)
    # A keyword in one language may be a valid API name or test input in
    # another (e.g. Python type/range). Name retrieval does not discard it.
    return sorted(names)


def rank_units(sources, names, *, mode):
    """Prioritize matching units and retain every matching expression span.

    These are positive hints for slicing, not the complete evidence workset.
    B's unmatched records and parse failures must also reach later analysis.
    Equal unit text in distinct source contexts is not merged.
    """
    targets, rows = set(names), []
    for source in sources:
        for unit in source['parsed']['units']:
            kinds = ('calls',) if mode == 'calls' else ('calls', 'uses', 'literals')
            matched = {kind: sorted(targets & unit[kind].keys()) for kind in kinds}
            if not any(matched.values()):
                continue
            anchors = sorted({tuple(span) for kind in kinds for word in matched[kind]
                              for span in unit[kind][word]})
            rows.append({'source': source['id'], 'path': source['path'],
                         'start': unit['start'], 'end': unit['end'],
                         'first_line': unit['first_line'], 'last_line': unit['last_line'],
                         'name': unit['name'], 'anchors': [list(span) for span in anchors],
                         'matched': matched,
                         'score': sum(len(words) for words in matched.values())})
    rows.sort(key=lambda row: (-row['score'], row['source'], row['start']))
    return rows
