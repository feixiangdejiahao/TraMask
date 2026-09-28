"""Recover bounded validation file versions without executing trajectory code.

Supports literal shell heredoc writes/appends and a deliberately small pure
Python file-edit language. Unknown operations never become executed evidence.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
import re

from anchor_retrieval.syntax import Source, child, trajectory_sources, walk


def _commands(trajectory):
    result = {}
    for step in trajectory.get('steps', []):
        for index, call in enumerate(step.get('tool_calls', [])):
            args = call.get('arguments', {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    continue
            if isinstance(args, dict) and isinstance(args.get('command'), str):
                result[(step['step_id'], index)] = args['command']
    return result


class Unknown(ValueError):
    pass


def recover_history(trajectory, language, *, max_bytes=500000, max_versions=256):
    raw = trajectory_sources(trajectory, language)
    commands, files, versions, skipped = _commands(trajectory), {}, [], Counter()
    pattern = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)^\1\s*$", re.M | re.S)

    def save(path, code, source, origin):
        if not isinstance(path, str) or not isinstance(code, str) or len(code.encode()) > max_bytes:
            raise Unknown('file_size_or_type')
        files[path] = code
        lang = 'go' if path.endswith('.go') else 'typescript' if re.search(r'\.tsx?$', path) else 'python' if path.endswith('.py') else None
        if lang and len(versions) < max_versions:
            digest = hashlib.sha256(code.encode()).hexdigest()[:12]
            new = Source(source.path + '-' + digest, code, lang, 'trajectory', source.step, path)
            versions.append((new, {'recovery': origin, 'historical_source': source.path}))

    def python_edits(source):
        env = {}
        def evaluate(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name) and node.id in env:
                return env[node.id]
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                a, b = evaluate(node.left), evaluate(node.right)
                if type(a) is type(b) is str and len(a)+len(b) <= max_bytes:
                    return a+b
            if isinstance(node, ast.Call):
                args = [evaluate(arg) for arg in node.args]
                if isinstance(node.func, ast.Name) and node.func.id in {'Path', 'open'} and args and isinstance(args[0], str):
                    return {'file': args[0], 'mode': args[1] if len(args)>1 else 'r'}
                if isinstance(node.func, ast.Attribute):
                    obj, method = evaluate(node.func.value), node.func.attr
                    if isinstance(obj, dict) and 'file' in obj:
                        name = obj['file']
                        if method in {'read', 'read_text'} and not args and name in files:
                            return files[name]
                        if method in {'write', 'write_text'} and len(args) == 1 and isinstance(args[0], str):
                            content = args[0]
                            if obj.get('mode') == 'a':
                                if name not in files:
                                    raise Unknown('append_without_recovered_base')
                                content = files[name]+content
                            save(name, content, source, 'restricted_python_literal_file_edit')
                            return len(content)
                    if isinstance(obj, str) and method == 'replace' and len(args) in {2,3}:
                        if all(isinstance(x, str) for x in args[:2]) and (len(args)==2 or type(args[2]) is int):
                            value = obj.replace(*args)
                            if len(value) <= max_bytes:
                                return value
            raise Unknown('unsupported_pure_file_edit')
        try:
            tree = ast.parse(source.code)
        except SyntaxError:
            return
        for statement in tree.body:
            try:
                if isinstance(statement, ast.Assign) and len(statement.targets)==1 and isinstance(statement.targets[0], ast.Name):
                    env[statement.targets[0].id] = evaluate(statement.value)
                elif isinstance(statement, ast.Expr):
                    evaluate(statement.value)
            except (Unknown, ValueError, TypeError, KeyError):
                # Unsupported commands remain in raw trajectory; no evaluation.
                continue

    for source in raw:
        identity = re.search(r'step-(.+)-(\d+)-(\d+|c\d+)\.', source.path)
        command = commands.get((source.step, int(identity[2])), '') if identity else ''
        matches = list(pattern.finditer(command))
        header = ''
        if identity and identity[3].isdigit() and int(identity[3]) < len(matches):
            match = matches[int(identity[3])]
            header = command[command.rfind('\n', 0, match.start())+1:command.find('\n', match.start())]
        if source.written_path and re.search(r'\bcat\b', header):
            path = source.written_path
            if '>>' in header:
                if path not in files:
                    skipped['append_without_recovered_base'] += 1
                    continue
                code = files[path]+source.code
                origin = 'literal_heredoc_append'
            else:
                code, origin = source.code, 'literal_heredoc_write'
            try:
                save(path, code, source, origin)
            except Unknown as exc:
                skipped[str(exc)] += 1
        else:
            before = len(versions)
            if source.language == 'python':
                python_edits(source)
            if len(versions) == before:
                versions.append((source, {'recovery': 'inline_script', 'historical_source': source.path}))
            else:
                skipped['source_edit_script_not_runtime_validation'] += 1
    unique, result, records = set(), [], []
    for source, record in versions:
        key = (source.written_path, hashlib.sha256(source.data).hexdigest())
        if key in unique:
            continue
        unique.add(key)
        result.append(source)
        records.append(dict(record, path=source.path, written_path=source.written_path,
                            step=source.step, sha256=key[1], executed_on_candidate=False))
    return result, {'versions': records, 'skipped': dict(skipped), 'raw_fragments': len(raw)}


def namespace_go_validation(source, suffix):
    """Give independently recovered test file globals distinct source names.

    Only identifier nodes are rewritten. Package/import/field names and strings
    remain unchanged. This is syntactic relocation and requires a compile and
    source-control replay; it is never evidence that the historical test passed.
    """
    declared = set()
    for node in source.root.named_children:
        if node.type == 'function_declaration':
            name = child(node, 'name')
            if name is not None and source.text(name) != 'init':
                declared.add(source.text(name))
        elif node.type in {'var_declaration', 'const_declaration', 'type_declaration'}:
            for part in walk(node):
                if part.type in {'var_spec', 'const_spec', 'type_spec'}:
                    name = child(part, 'name')
                    if name is not None:
                        declared.add(source.text(name))
    edits = [(node.start_byte, node.end_byte, source.text(node)+'_rh_'+suffix)
             for node in walk(source.root) if node.type in {'identifier', 'type_identifier'} and source.text(node) in declared]
    data = source.data
    for start, end, text in reversed(edits):
        data = data[:start]+text.encode()+data[end:]
    return Source(source.path, data.decode(), source.language, source.origin, source.step, source.written_path), sorted(declared)
