"""Static test definitions; runtime instances and reachability are separate."""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
from pathlib import PurePosixPath
import re

from .anchors import js_test_registration
from .source_text import decode_source


def _row(path, raw, name, start, end, framework):
    return {'id': hashlib.sha256((path + '\0' + name + '\0' + str(start)).encode()).hexdigest()[:24],
            'path': path, 'name': name, 'first_line': start, 'last_line': end,
            'framework': framework, 'source_sha256': hashlib.sha256(raw).hexdigest()}


def _parsed(units, spans):
    counts = Counter(unit['id'] for unit in units)
    ranges = {}
    for unit, span in zip(units, spans):
        if counts[unit['id']] > 1:
            unit['id'] = hashlib.sha256((unit['id'] + '\0' + str(span[0])).encode()).hexdigest()[:24]
        ranges[unit['id']] = span
    return {'units': units, 'ranges': ranges, 'status': 'parsed'}


def discover(path, raw, *, normalized=False):
    """Parse function declarations without importing the subject repository."""
    suffix = PurePosixPath(path).suffix
    try:
        if suffix == '.py':
            return _python(path, raw, raw.decode('utf-8') if normalized else decode_source(path, raw))
        if suffix in {'.go', '.rs', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts'}:
            return _treesitter(path, raw)
    except (SyntaxError, UnicodeError) as error:
        return {'units': [], 'status': 'unresolved', 'reason': str(error)}
    return {'units': [], 'status': 'not_test_source'}


def _python(path, raw, text):
    normalized = text.encode('utf-8')
    tree = ast.parse(text)
    units, spans = [], []
    lines = normalized.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def visit(body, parents=(), is_test_class=False):
        for node in body:
            if isinstance(node, ast.ClassDef):
                test_class = node.name.startswith('Test') or any(ast.unparse(b).endswith('TestCase') for b in node.bases)
                visit(node.body, (*parents, node.name), test_class)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                name = '::'.join((*parents, node.name))
                if node.name.startswith('test') and (not parents or is_test_class):
                    unit = _row(path, raw, name, start, node.end_lineno, 'pytest_or_unittest')
                    units.append(unit)
                    spans.append([offsets[start - 1], offsets[node.end_lineno - 1] + node.end_col_offset])
    visit(tree.body)
    # Preserve assertion-bearing standalone scripts as a separate kind. The
    # presence of an assert is not a claim that execution reached that assert.
    def module_assertions(nodes):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(node, ast.Assert):
                return True
            if module_assertions(list(ast.iter_child_nodes(node))):
                return True
        return False
    if not units and module_assertions(tree.body):
        unit = _row(path, raw, '<script>', 1, len(raw.splitlines()), 'script')
        units.append(unit)
        spans.append([0, len(normalized)])
    return _parsed(units, spans)


def _treesitter(path, raw):
    from tree_sitter import Language, Parser
    if path.endswith('.go'):
        import tree_sitter_go
        grammar, language = tree_sitter_go.language(), 'go'
    elif path.endswith('.rs'):
        import tree_sitter_rust
        grammar, language = tree_sitter_rust.language(), 'rust'
    else:
        import tree_sitter_typescript
        grammar = tree_sitter_typescript.language_tsx() if path.endswith(('.tsx', '.jsx')) else tree_sitter_typescript.language_typescript()
        language = 'javascript'
    root = Parser(Language(grammar)).parse(raw).root_node
    if root.has_error:
        raise SyntaxError('source_parse_error:' + path)
    units, spans = [], []

    def add(name, node, framework, start=None):
        unit = _row(path, raw, name, node.start_point.row + 1, node.end_point.row + 1, framework)
        units.append(unit)
        spans.append([node.start_byte if start is None else start, node.end_byte])

    def text(node):
        return raw[node.start_byte:node.end_byte].decode() if node is not None else ''

    def visit(node, parents=()):
        if language == 'go' and node.type == 'function_declaration':
            name = text(node.child_by_field_name('name'))
            if name != 'TestMain' and re.match(r'^(?:Test|Example|Fuzz)(?:[^a-z]|$)', name):
                add(name, node, 'go')
        elif language == 'rust':
            if node.type == 'mod_item':
                parents = (*parents, text(node.child_by_field_name('name')))
            elif node.type == 'function_item':
                attrs, sibling, start = [], node.prev_named_sibling, node.start_byte
                while sibling is not None and sibling.type in {'attribute_item', 'line_comment', 'block_comment'}:
                    if sibling.type == 'attribute_item':
                        attrs.append(text(sibling))
                        start = sibling.start_byte
                    sibling = sibling.prev_named_sibling
                if any(re.search(r'#\[\s*(?:[\w:]+::)?test\s*(?:\(|\])', a) for a in attrs):
                    name = '::'.join((*parents, text(node.child_by_field_name('name'))))
                    add(name, node, 'rust', start)
        elif language == 'javascript' and node.type == 'call_expression':
            registration = js_test_registration(raw, node)
            args = node.child_by_field_name('arguments')
            values = list(args.named_children) if args is not None else []
            if registration:
                literal = values[0].type == 'string'
                label = text(values[0])[1:-1] if literal else '<dynamic@' + str(node.start_point.row + 1) + '>'
                if registration in {'describe', 'suite', 'context'}:
                    parents = (*parents, label)
                else:
                    add(' > '.join((*parents, label)), node, 'javascript')
        return [(child,parents) for child in node.named_children]
    todo=[(root,())]
    while todo:
        node,parents=todo.pop()
        todo.extend(reversed(visit(node,parents)))
    return _parsed(units, spans)
