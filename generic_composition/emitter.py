"""Clone source tests beside their original lexical scope and apply byte edits.

The emitter does not generate expectations or decide semantic validity. It
keeps the original test body/decorators, changes the registration name, and
applies exactly the requested edits. Imports are the only file-level additions.
"""
from __future__ import annotations

import ast
import hashlib
import json
import posixpath
import re
from collections import defaultdict

from anchor_retrieval.syntax import CALLS, Source, call_parts, child, literal, walk
from .corpus import source_text


class Unsupported(ValueError):
    pass


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _safe_id(value: str) -> str:
    return value if re.fullmatch(r'[A-Za-z0-9_]+', value) else _digest(value)


def _name(language: str, identifier: str, control=False) -> str:
    prefix = {'python': 'test_gc_', 'go': 'TestGC_', 'typescript': 'gc_'}[language]
    return prefix + ('control_' if control else '') + _safe_id(identifier)


def _source(corpus, path):
    metadata = corpus['sources'][path]
    if not metadata.get('complete_file', True):
        raise Unsupported('incomplete_source_file')
    if metadata.get('parse_error'):
        raise Unsupported('original_source_parse_error')
    return Source(path, metadata['code'], metadata.get('language', corpus['language']))


def _unit_node(source, test):
    definition = test.get('definition_span', test['span'])
    candidates = [n for n in walk(source.root)
                  if n.start_byte == definition['start_byte'] and n.end_byte == definition['end_byte']]
    preferred = {'python': {'function_definition'}, 'go': {'function_declaration', 'method_declaration'},
                 'typescript': CALLS}[source.language]
    node = next((n for n in candidates if n.type in preferred), None)
    if node is None:
        # Compatibility with a corpus that only supplied decorated test spans.
        node = next((n for n in walk(source.root) if n.type in preferred
                     and test['span']['start_byte'] <= n.start_byte
                     and n.end_byte <= test['span']['end_byte']), None)
    if node is None:
        raise Unsupported('test_definition_not_found')
    return node


def _rename(source, node, name):
    if source.language in {'python', 'go'}:
        target = child(node, 'name')
        if target is None:
            raise Unsupported('unnamed_test_definition')
        return target.start_byte, target.end_byte, name
    fn, args = call_parts(node)
    if not args:
        raise Unsupported('missing_test_title')
    if '.each' in source.text(fn):
        # Replacing a formatted parameterized title by one constant would
        # collapse runtime rows to duplicate IDs; no silent row renaming.
        raise Unsupported('typescript_parameterized_title_requires_runtime_row_mapping')
    try:
        title = literal(source.text(args[0]))
    except ValueError:
        raise Unsupported('nonliteral_test_title') from None
    if not isinstance(title, str):
        raise Unsupported('nonstring_test_title')
    return args[0].start_byte, args[0].end_byte, json.dumps(name, ensure_ascii=False)


def _runtime_name(source, node, name):
    if source.language != 'typescript':
        return name
    titles = []
    parent = node.parent
    while parent is not None:
        if parent.type in CALLS:
            fn, args = call_parts(parent)
            if source.text(fn).split('.')[0] in {'describe', 'context', 'suite'} and args:
                try:
                    value = literal(source.text(args[0]))
                except ValueError:
                    raise Unsupported('dynamic_enclosing_suite_title') from None
                if not isinstance(value, str):
                    raise Unsupported('nonstring_enclosing_suite_title')
                titles.append(value)
        parent = parent.parent
    return ' '.join([*reversed(titles), name])


def _clone(source, test, name, edits):
    node = _unit_node(source, test)
    test_span = test['span']
    start, end = test_span['start_byte'], test_span['end_byte']
    operations = []
    for edit in edits:
        position = edit['span']
        a, b = position['start_byte'], position['end_byte']
        if position['path'] != source.path or not start <= a <= b <= end:
            raise Unsupported('edit_outside_base_test')
        if source.data[a:b].decode() != edit['before']:
            raise Unsupported('edit_before_mismatch')
        if not isinstance(edit['after'], str):
            raise Unsupported('replacement_must_be_text')
        operations.append((a, b, edit['after']))
    operations.append(_rename(source, node, name))
    operations.sort(key=lambda item: (item[0], item[1]))
    for left, right in zip(operations, operations[1:]):
        if left[1] > right[0] or (left[0] == left[1] == right[0]):
            raise Unsupported('overlapping_edits_or_test_name_edit')
    body = source.data[start:end]
    try:
        for a, b, after in reversed(operations):
            body = body[:a - start] + after.encode() + body[b - start:]
        text = body.decode()
    except UnicodeError:
        raise Unsupported('edit_splits_utf8_character') from None
    insertion = test.get('insertion_after_byte', end)
    if not end <= insertion <= len(source.data):
        raise Unsupported('invalid_insertion_position')
    first_line_start = source.data.rfind(b'\n', 0, start) + 1
    leading = source.data[first_line_start:start].decode()
    indent = re.match(r'[ \t]*', leading).group()
    if source.language == 'typescript':
        text += ';'
    return {'insertion': insertion, 'text': '\n\n' + indent + text + '\n',
            'test_name': name, 'id': _runtime_name(source, node, name)}


def _relative_module(module, source_path, target_path, language):
    if not module.startswith('.'):
        return module
    if language == 'typescript':
        absolute = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), module))
        relative = posixpath.relpath(absolute, posixpath.dirname(target_path) or '.')
        return relative if relative.startswith('.') else './' + relative
    if language == 'python':
        dots = len(module) - len(module.lstrip('.'))
        origin = posixpath.dirname(source_path).split('/')
        if dots > len(origin):
            raise Unsupported('relative_import_escapes_repository')
        resolved = origin[:len(origin) - dots + 1] + module[dots:].split('.')
        resolved = [p for p in resolved if p]
        target = [p for p in posixpath.dirname(target_path).split('/') if p]
        common = 0
        while common < min(len(target), len(resolved)) and target[common] == resolved[common]:
            common += 1
        if not target:
            return '.'.join(resolved)
        return '.' * (len(target) - common + 1) + '.'.join(resolved[common:])
    return module


def _import_line(language, item):
    name, module, imported = item['name'], item['module'], item.get('imported_name')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise Unsupported('invalid_import_binding')
    if language == 'python':
        if imported:
            return f'from {module} import {imported}' + (f' as {name}' if imported != name else '') + '\n'
        return f'import {module}' + (f' as {name}' if name != module.split('.')[0] else '') + '\n'
    if language == 'go':
        return 'import ' + name + ' ' + json.dumps(module) + '\n'
    quoted = json.dumps(module)
    if imported == 'default':
        return f'import {name} from {quoted};\n'
    if imported:
        binding = imported if imported == name else imported + ' as ' + name
        return 'import { ' + binding + ' } from ' + quoted + ';\n'
    return f'import * as {name} from {quoted};\n'


def _header_offset(source):
    end = 0
    allowed = {'python': {'comment', 'import_statement', 'import_from_statement', 'future_import_statement'},
               'go': {'comment', 'package_clause', 'import_declaration'},
               'typescript': {'comment', 'hash_bang_line', 'import_statement'}}[source.language]
    for node in source.root.named_children:
        directive = node.type == 'expression_statement' and len(node.named_children) == 1 and node.named_children[0].type == 'string'
        if node.type in allowed or directive:
            end = node.end_byte
        else:
            break
    return end


def _top_bindings(source):
    names = set(source.imports)
    for node in source.root.named_children:
        if node.type in {'function_definition', 'function_declaration', 'class_definition', 'class_declaration'}:
            names.add(source.text(child(node, 'name')))
        if node.type == 'decorated_definition':
            definition = child(node, 'definition')
            if definition is not None:
                names.add(source.text(child(definition, 'name')))
        if node.type in {'expression_statement', 'lexical_declaration', 'variable_declaration', 'var_declaration', 'const_declaration'}:
            for n in walk(node):
                if n.type in {'assignment', 'variable_declarator', 'var_spec', 'const_spec'}:
                    target = child(n, 'left', 'name')
                    if target is not None:
                        names.update(source.text(x) for x in walk(target) if x.type == 'identifier')
    return names


def _enclosing_bindings(source, test):
    """Importing a name cannot override a binding captured from an outer scope."""
    names = set()
    parent = _unit_node(source, test).parent
    while parent is not None and parent != source.root:
        if parent.type in {'statement_block', 'block'}:
            # Python class members are not lexical bindings inside methods.
            if not (source.language == 'python' and parent.parent is not None
                    and parent.parent.type == 'class_definition'):
                for declaration in parent.named_children:
                    if declaration.type in {'lexical_declaration', 'variable_declaration', 'expression_statement'}:
                        for item in declaration.named_children:
                            if item.type in {'assignment', 'variable_declarator'}:
                                target = child(item, 'left', 'name')
                                if target is not None:
                                    names.update(source.text(n) for n in walk(target) if n.type == 'identifier')
                    elif declaration.type in {'function_definition', 'function_declaration', 'class_declaration'}:
                        names.add(source.text(child(declaration, 'name')))
        if parent.type in {'arrow_function', 'function_expression', 'function_definition', 'func_literal'}:
            parameters = child(parent, 'parameters')
            if parameters is not None:
                names.update(source.text(n) for n in walk(parameters) if n.type == 'identifier')
        parent = parent.parent
    return names


def _normalize_imports(corpus, source, test, requested, existing_additions):
    additions = {}
    bound = _top_bindings(source)
    local = set(test.get('scope_bindings', [])) | _enclosing_bindings(source, test)
    for raw in requested:
        item = {key: raw.get(key) for key in ('name', 'module', 'imported_name')}
        if not isinstance(item['module'], str) or not item['module']:
            raise Unsupported('missing_import_module')
        item['module'] = _relative_module(item['module'], raw.get('source_path', source.path), source.path, source.language)
        name = item['name']
        pair = (item['module'], item['imported_name'])
        if name in local:
            raise Unsupported('import_conflicts_with_test_local:' + str(name))
        if name in source.imports:
            if source.imports[name] == pair:
                continue
            raise Unsupported('import_conflicts_with_existing_import:' + str(name))
        if name in bound:
            raise Unsupported('import_conflicts_with_existing_binding:' + str(name))
        previous = existing_additions.get(name) or additions.get(name)
        if previous and (previous['module'], previous['imported_name']) != pair:
            raise Unsupported('import_conflicts_between_generated_tests:' + str(name))
        _import_line(source.language, item)  # Validate the binding before recording it.
        additions[name] = item
    return additions


def _render(source, clones, imports):
    inserts = defaultdict(list)
    for clone in clones:
        inserts[clone['insertion']].append((clone['id'], clone['text']))
    if imports:
        header = '\n' + ''.join(_import_line(source.language, imports[name]) for name in sorted(imports)) + '\n'
        inserts[_header_offset(source)].append(('', header))
    data = source.data
    for offset in sorted(inserts, reverse=True):
        value = ''.join(text for _, text in sorted(inserts[offset])).encode()
        data = data[:offset] + value + data[offset:]
    return data.decode()


def _validate(source, text):
    if source.language == 'python':
        try:
            compile(text, source.path, 'exec')
        except (SyntaxError, ValueError) as exc:
            raise Unsupported('generated_python_syntax_error:' + str(exc)) from None
    parsed = Source(source.path, text, source.language)
    if parsed.root.has_error:
        raise Unsupported('generated_tree_sitter_parse_error')


def emit(corpus: dict, candidates: list[dict]) -> dict:
    """Return edited full files; leave corpus and repository bytes unchanged.

    Every accepted candidate depends on unchanged clones of its base and source
    tests. Unsupported candidates stay explicit and are never runtime alarms.
    """
    result = {'files': {}, 'obligations': [], 'controls': [], 'unsupported': []}
    sources, clones, imports = {}, defaultdict(list), defaultdict(dict)
    control_records = {}
    seen_ids = set()
    for candidate in sorted(candidates, key=lambda c: str(c.get('id', ''))):
        identifier = str(candidate.get('id', ''))
        try:
            if not identifier or identifier in seen_ids:
                raise Unsupported('missing_or_duplicate_candidate_id')
            seen_ids.add(identifier)
            test_id = candidate['base_test_id']
            test = corpus['tests'][test_id]
            path = test['span']['path']
            source = sources.setdefault(path, _source(corpus, path))
            generated = _clone(source, test, _name(source.language, identifier), candidate.get('edits', []))
            additions = _normalize_imports(corpus, source, test, candidate.get('imports', []), imports[path])
            pending_controls = {}
            for owner in sorted({test_id, *candidate.get('source_test_ids', [])}):
                if owner in control_records:
                    continue
                original = corpus['tests'][owner]
                control_path = original['span']['path']
                control_source = sources.setdefault(control_path, _source(corpus, control_path))
                name = _name(control_source.language, _digest(owner), control=True)
                clone = _clone(control_source, original, name, [])
                pending_controls[owner] = (control_path, clone)
            proposed = {p: list(items) for p, items in clones.items()}
            proposed.setdefault(path, []).append(generated)
            for control_path, clone in pending_controls.values():
                proposed.setdefault(control_path, []).append(clone)
            proposed_imports = {p: dict(items) for p, items in imports.items()}
            proposed_imports.setdefault(path, {}).update(additions)
            for affected in {path, *(p for p, _ in pending_controls.values())}:
                _validate(sources[affected], _render(sources[affected], proposed[affected], proposed_imports.get(affected, {})))
            clones = defaultdict(list, proposed)
            imports = defaultdict(dict, proposed_imports)
            for owner, (control_path, clone) in pending_controls.items():
                record = {'id': clone['id'], 'test_name': clone['test_name'], 'base_test_id': owner,
                          'path': control_path, 'is_control': True, 'control_ids': []}
                control_records[owner] = record
                result['controls'].append(record)
            controls = [control_records[owner]['id'] for owner in sorted({test_id, *candidate.get('source_test_ids', [])})]
            result['obligations'].append({'id': generated['id'], 'candidate_id': identifier,
                                          'test_name': generated['test_name'], 'path': path,
                                          'base_test_id': test_id, 'control_ids': controls,
                                          'control_id': control_records[test_id]['id'], 'is_control': False})
        except (Unsupported, KeyError, TypeError, UnicodeError) as exc:
            result['unsupported'].append({'candidate_id': identifier, 'reason': str(exc)})
    result['files'] = {path: _render(sources[path], clones[path], imports.get(path, {})) for path in sorted(clones)}
    result['controls'].sort(key=lambda row: row['id'])
    return result
