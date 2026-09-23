"""Tree-sitter source inventory; historical commands are parsed, never executed."""
from __future__ import annotations

import ast
import hashlib
import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from tree_sitter import Language, Node, Parser
import tree_sitter_go
import tree_sitter_python
import tree_sitter_typescript

SKIP = {'.git', '.venv', 'node_modules', 'vendor', 'dist', 'build', '__pycache__', '.mypy_cache'}
LANGUAGES = {
    'python': Language(tree_sitter_python.language()),
    'go': Language(tree_sitter_go.language()),
    'typescript': Language(tree_sitter_typescript.language_typescript()),
}
TSX_LANGUAGE = Language(tree_sitter_typescript.language_tsx())
FUNCTIONS = {'function_definition', 'function_declaration', 'method_declaration', 'method_definition'}
CALLS = {'call', 'call_expression', 'new_expression'}
ATTRS = {'attribute', 'member_expression', 'selector_expression'}
IDENTIFIERS = {'identifier', 'field_identifier', 'property_identifier', 'type_identifier'}
BLOCKS = {'block', 'statement_block', 'statement_list', 'module', 'program', 'source_file'}


def walk(node: Node, stop_functions: bool = False) -> Iterator[Node]:
    yield node
    for child in node.named_children:
        if stop_functions and child.type in FUNCTIONS:
            continue
        yield from walk(child, stop_functions)


def child(node: Node, *names: str) -> Node | None:
    for name in names:
        value = node.child_by_field_name(name)
        if value is not None:
            return value
    return None


def call_parts(node: Node) -> tuple[Node | None, list[Node]]:
    fn = child(node, 'function', 'constructor')
    args = child(node, 'arguments')
    return fn, list(args.named_children) if args is not None else []


def attr_parts(node: Node) -> tuple[Node | None, Node | None]:
    return child(node, 'object', 'operand'), child(node, 'attribute', 'property', 'field')


def literal(text: str) -> Any:
    """Only literal syntax, not eval/imports/calls. Raises ValueError if unknown."""
    text = text.strip()
    if text.startswith('`') and text.endswith('`') and '${' not in text:
        return text[1:-1]
    if text in {'true', 'false', 'null', 'nil', 'undefined'}:
        return {'true': True, 'false': False, 'null': None, 'nil': None, 'undefined': None}[text]
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError):
        raise ValueError(text[:80]) from None


def json_safe(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        return {'$set': sorted((json_safe(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))}
    if isinstance(value, bytes):
        return {'$bytes_hex': value.hex()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        if all(isinstance(k, str) for k in value):
            return {k: json_safe(v) for k, v in value.items()}
        return {'$mapping': sorted([[json_safe(k), json_safe(v)] for k, v in value.items()], key=repr)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {'$literal_repr': repr(value)}


def canonical(value: Any) -> str:
    # JS tests legitimately contain isolated UTF-16 surrogates; preserve them as escapes.
    return json.dumps(json_safe(value), sort_keys=True, ensure_ascii=True)


def is_test_path(path: str) -> bool:
    return bool(re.search(r'(^|/)(tests?|__tests__)/|(^|/)test_|_test\.go$|\.(test|spec)(-d)?\.', path))


def diff_lines(patch: str) -> dict[str, set[int]]:
    """New-side positions, including the boundary of a deletion-only hunk."""
    result: dict[str, set[int]] = {}
    path = None
    line = 0
    for row in patch.splitlines():
        if row.startswith('+++ b/'):
            path = row[6:]
            result.setdefault(path, set())
        elif row.startswith('@@'):
            match = re.search(r'\+(\d+)', row)
            if match:
                line = int(match[1])
        elif path and row.startswith('+'):
            result[path].add(line)
            line += 1
        elif path and row.startswith('-') and not row.startswith('---'):
            result[path].add(max(1, line))
        elif row.startswith(' '):
            line += 1
    return result


@dataclass
class Source:
    path: str
    code: str
    language: str
    origin: str = 'repository'
    step: int | str | None = None
    written_path: str | None = None
    root: Node = field(init=False, repr=False)
    data: bytes = field(init=False, repr=False)
    imports: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    exports: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.data = self.code.encode()
        grammar = TSX_LANGUAGE if self.language == 'typescript' and self.path.endswith('.tsx') else LANGUAGES[self.language]
        self.root = Parser(grammar).parse(self.data).root_node
        self._imports()

    def text(self, node: Node | None) -> str:
        return self.data[node.start_byte:node.end_byte].decode() if node is not None else ''

    @property
    def type_only(self) -> bool:
        return bool(re.search(r'\.test-d\.tsx?$', self.path))

    @property
    def lookup_path(self) -> str:
        return self.written_path or self.path

    def _imports(self):
        if self.language == 'python':
            try:
                tree = ast.parse(self.code)
            except SyntaxError:
                return
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    mod = '.' * node.level + (node.module or '')
                    for alias in node.names:
                        self.imports[alias.asname or alias.name] = (mod, alias.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports[alias.asname or alias.name.split('.')[0]] = (alias.name, None)
        elif self.language == 'typescript':
            for node in self.root.named_children:
                if node.type not in {'import_statement', 'export_statement'}:
                    continue
                src = child(node, 'source')
                if src is None:
                    continue
                try:
                    mod = literal(self.text(src))
                except ValueError:
                    continue
                if node.type == 'export_statement':
                    self.exports.append(mod)
                for item in walk(node):
                    if item.type == 'import_specifier':
                        name, alias = child(item, 'name'), child(item, 'alias')
                        self.imports[self.text(alias or name)] = (mod, self.text(name))
                    elif item.type == 'import_clause':
                        for name in item.named_children:
                            if name.type == 'identifier':
                                self.imports[self.text(name)] = (mod, 'default')
                    elif item.type == 'namespace_import':
                        name = next((n for n in item.named_children if n.type == 'identifier'), None)
                        self.imports[self.text(name)] = (mod, None)
        else:
            for node in walk(self.root):
                if node.type == 'import_spec':
                    path = child(node, 'path')
                    if path is None:
                        continue
                    mod = literal(self.text(path))
                    package_path = re.sub(r'/v\d+$', '', mod)
                    alias = self.text(child(node, 'name')) or package_path.rsplit('/', 1)[-1]
                    self.imports[alias] = (mod, None)


@dataclass
class Unit:
    source: Source
    node: Node
    body: Node
    name: str
    owner: str = ''
    test: bool = False
    params: list[str] = field(default_factory=list)
    param_types: dict[str, str] = field(default_factory=dict)
    return_types: set[str] = field(default_factory=set)
    decorators: list[str] = field(default_factory=list)
    parameter_values: dict[str, list[Any]] = field(default_factory=dict)
    parameter_rows: list[Any] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f'{self.source.path}:{self.node.start_point.row + 1}:{self.owner + "." if self.owner else ""}{self.name}'

    @property
    def line(self) -> int:
        return self.node.start_point.row + 1

    @property
    def fingerprint(self) -> str:
        # Comments/formatting/locations are irrelevant; retain identifiers and literals.
        tokens = []
        def leaves(node):
            if node.type == 'comment':
                return
            if not node.children:
                tokens.append((node.type, self.source.text(node)))
            for item in node.children:
                leaves(item)
        leaves(self.node)
        contexts = []
        ancestor = self.node.parent
        while ancestor is not None:
            if ancestor.type in CALLS:
                fn, args = call_parts(ancestor)
                if self.source.text(fn).split('.')[0] in {'describe', 'context', 'suite'} and args:
                    contexts.append(self.source.text(args[0]))
            ancestor = ancestor.parent
        # Equal text in different files/scopes can bind to different imports or fixtures.
        identity = [self.source.lookup_path, self.owner, contexts, self.source.imports]
        return hashlib.sha256(canonical([identity, tokens, self.decorators, self.parameter_rows]).encode()).hexdigest()


def _parameters(unit: Unit):
    src, node = unit.source, unit.node
    params = child(node, 'parameters')
    if params is not None:
        for p in params.named_children:
            target = child(p, 'name', 'pattern')
            if p.type in {'identifier', 'list_splat_pattern', 'dictionary_splat_pattern'}:
                target = p
            if target is None and p.named_children:
                target = p.named_children[0]
            if target is None:
                continue
            names = [src.text(n) for n in walk(target) if n.type == 'identifier']
            for name in names:
                if name not in unit.params:
                    unit.params.append(name)
                typ = child(p, 'type')
                if typ is not None:
                    unit.param_types[name] = src.text(typ).lstrip(': ').strip()
    receiver = child(node, 'receiver')
    if receiver is not None:
        for p in receiver.named_children:
            name, typ = child(p, 'name'), child(p, 'type')
            if name is not None:
                unit.param_types[src.text(name)] = src.text(typ)
    result = child(node, 'return_type', 'result')
    if result is not None:
        unit.return_types.update(re.findall(r'[A-Za-z_]\w*', src.text(result)))
    parent = node.parent
    if parent is not None and parent.type == 'decorated_definition':
        unit.decorators = [src.text(n) for n in parent.named_children if n.type == 'decorator']
    if src.language == 'python':
        try:
            parsed = ast.parse(src.text(parent if parent is not None and parent.type == 'decorated_definition' else node))
            fn = parsed.body[0]
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in fn.decorator_list:
                    if isinstance(dec, ast.Call) and ast.unparse(dec.func).endswith('.parametrize') and len(dec.args) >= 2:
                        names = ast.literal_eval(dec.args[0])
                        names = [x.strip() for x in names.split(',')] if isinstance(names, str) else names
                        rows = ast.literal_eval(dec.args[1])
                        unit.parameter_rows.append({'names': names, 'rows': rows})
                        for i, name in enumerate(names):
                            unit.parameter_values[name] = [r if len(names) == 1 else r[i] for r in rows]
        except (SyntaxError, ValueError, TypeError, IndexError, AttributeError):
            pass


def units(source: Source) -> tuple[list[Unit], dict[str, list[str]]]:
    result = []
    classes: dict[str, list[str]] = {}
    for node in walk(source.root):
        if node.type in {'class_definition', 'class_declaration'}:
            name = source.text(child(node, 'name'))
            bases = child(node, 'superclasses')
            classes[name] = [source.text(n).split('[')[0] for n in bases.named_children] if bases else []
        if node.type in FUNCTIONS:
            body = child(node, 'body')
            if body is None:
                continue  # TS overload/type declaration, not executable implementation.
            name = source.text(child(node, 'name'))
            owner = ''
            parent = node.parent
            while parent is not None:
                if parent.type in {'class_definition', 'class_declaration'}:
                    owner = source.text(child(parent, 'name'))
                    break
                parent = parent.parent
            if source.language == 'go' and child(node, 'receiver') is not None:
                recv = child(node, 'receiver')
                types = [source.text(n) for n in walk(recv) if n.type == 'type_identifier']
                owner = types[-1] if types else ''
            test = ((source.language == 'python' and name.startswith('test')) or
                    (source.language == 'go' and name.startswith('Test'))) and (
                        is_test_path(source.path) or source.origin == 'trajectory')
            unit = Unit(source, node, body, name, owner, test)
            _parameters(unit)
            result.append(unit)
        if source.language == 'typescript' and node.type == 'call_expression':
            fn, args = call_parts(node)
            if not re.match(r'^(test|it)(\.|\(|$)', source.text(fn)) or len(args) < 2:
                continue
            callback = next((a for a in reversed(args) if a.type in {'arrow_function', 'function_expression'}), None)
            if callback is None:
                continue
            try:
                name = str(literal(source.text(args[0])))
            except ValueError:
                name = source.text(args[0])
            body = child(callback, 'body')
            if body is not None:
                result.append(Unit(source, node, body, name, test=True))
    if source.origin == 'trajectory' and not any(u.test for u in result):
        if any(n.type == 'assert_statement' for n in walk(source.root)):
            result.append(Unit(source, source.root, source.root, '<script>', test=True))
    return result, classes


def trajectory_sources(trajectory: dict, language: str) -> list[Source]:
    result = []
    heredoc = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)^\1\s*$", re.M | re.S)
    for step in trajectory.get('steps', []):
        for ci, call in enumerate(step.get('tool_calls', [])):
            args = call.get('arguments', {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    continue
            if not isinstance(args, dict):
                continue
            command = args.get('command', '')
            if not isinstance(command, str):
                continue
            candidates = []
            for i, match in enumerate(heredoc.finditer(command)):
                header = command[command.rfind('\n', 0, match.start()) + 1:match.start()]
                # Redirection may appear after the heredoc marker.
                header += command[match.start():command.find('\n', match.start())]
                paths = re.findall(r'[\w./-]+\.(?:py|go|tsx?)(?=[\s\'\"<>]|$)', header)
                written = paths[-1].removeprefix('/repo/') if paths else None
                if not written and re.search(r'>+\s*[\'\"]?[^\s\'\"]+\.(?:md|txt|patch|diff|json|toml|yaml|yml)(?:[\'\"]|\s|$)', header):
                    continue
                code = match.group(2)
                lang = ('go' if (written and written.endswith('.go')) or re.match(r'\s*package\s+\w+', code)
                        else 'typescript' if (written and re.search(r'\.tsx?$', written)) or 'vitest' in code
                        else 'python' if 'python' in header or (written and written.endswith('.py'))
                        else language)
                candidates.append((str(i), code, lang, written))
            # Literal python -c scripts, without executing shell interpolation.
            for i, match in enumerate(re.finditer(r"python[\d.]*\s+-c\s+('(?:[^']*)'|\"(?:[^\"]*)\")", command, re.S)):
                candidates.append((f'c{i}', match.group(1)[1:-1], 'python', None))
            for label, code, lang, written in candidates:
                suffix = {'python': '.py', 'go': '.go', 'typescript': '.ts'}[lang]
                path = f"trajectory/step-{step['step_id']}-{ci}-{label}{suffix}"
                result.append(Source(path, code, lang, 'trajectory', step['step_id'], written))
    return result


def load_sources(repo: Path, language: str, trajectory: dict | None = None) -> list[Source]:
    extensions = {'python': {'.py'}, 'go': {'.go'}, 'typescript': {'.ts', '.tsx'}}[language]
    result = []
    for path in sorted(repo.rglob('*')):
        if not path.is_file() or path.suffix not in extensions or set(path.relative_to(repo).parts) & SKIP:
            continue
        if path.stat().st_size > 1_000_000:
            continue
        result.append(Source(path.relative_to(repo).as_posix(), path.read_text(errors='replace'), language))
    if trajectory is not None:
        result.extend(trajectory_sources(trajectory, language))
    return result
