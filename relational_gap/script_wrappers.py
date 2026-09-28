"""Scope-aware wrappers for recovered standalone Python validation scripts.

Preparation is pure: it returns new Source objects and byte provenance, never
writes or executes a historical script. The wrapped source is reparsed by the
ordinary frontend before edits are enumerated, so candidate spans cannot refer
to obsolete pre-wrapper coordinates.

Imports and top-level definitions remain module bindings. Executable script
statements move into one deterministic test with explicit ``global`` bindings,
which preserves module helpers' lookup of script-assigned variables. Cases where
lifting a definition/import would visibly change eager scope are unsupported.
"""
from __future__ import annotations

import ast
import hashlib
import io
import tokenize
from typing import Iterable

from anchor_retrieval.syntax import Source, units


class UnsupportedScript(ValueError):
    """The source cannot be wrapped within the supported scope fragment."""


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def _span(source, node):
    starts = [0]
    for line in source.data.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return {'path': source.path, 'start_byte': starts[node.lineno - 1] + node.col_offset,
            'end_byte': starts[node.end_lineno - 1] + node.end_col_offset,
            'line': node.lineno, 'end_line': node.end_lineno}


def _node_start(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.decorator_list:
        return min(node.lineno, *(item.lineno for item in node.decorator_list)), 0
    return node.lineno, node.col_offset


def _node_text(source, node):
    position = _span(source, node)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.decorator_list:
        starts = source.data.splitlines(keepends=True)
        line, column = _node_start(node)
        position['start_byte'] = sum(len(part) for part in starts[:line - 1]) + column
        position['line'] = line
    return source.data[position['start_byte']:position['end_byte']].decode(), position


def _main_guard(node):
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    test = node.test
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq) or len(test.comparators) != 1:
        return False
    left, right = test.left, test.comparators[0]
    return ((isinstance(left, ast.Name) and left.id == '__name__' and isinstance(right, ast.Constant) and right.value == '__main__')
            or (isinstance(right, ast.Name) and right.id == '__name__' and isinstance(left, ast.Constant) and left.value == '__main__'))


class _ModuleBindings(ast.NodeVisitor):
    def __init__(self):
        self.names = set()
        self.annotated = set()
        self.star_import = False

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)
        # Defaults/decorators can contain assignment expressions in this scope.
        for item in [*node.decorator_list, *node.args.defaults, *(x for x in node.args.kw_defaults if x)]:
            self.visit(item)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.names.add(node.name)
        for item in [*node.decorator_list, *node.bases, *(x.value for x in node.keywords)]:
            self.visit(item)

    def visit_Lambda(self, node):
        for item in [*node.args.defaults, *(x for x in node.args.kw_defaults if x)]:
            self.visit(item)

    def visit_Import(self, node):
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split('.')[0])

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == '*':
                self.star_import = True
            else:
                self.names.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name:
            self.names.add(node.name)
        if node.pattern:
            self.visit(node.pattern)

    def visit_MatchStar(self, node):
        if node.name:
            self.names.add(node.name)

    def visit_MatchMapping(self, node):
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if isinstance(node.target, ast.Name):
            self.annotated.add(node.target.id)
        self.generic_visit(node)

    def _comprehension(self, node):
        # Comprehension induction variables have their own scope. NamedExpr
        # targets in the body still bind the enclosing module.
        for part in ast.walk(node):
            if isinstance(part, ast.NamedExpr):
                self.visit(part.target)

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension


def _eager_nodes(node, future_annotations):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        result = [*node.decorator_list, *node.args.defaults, *(x for x in node.args.kw_defaults if x)]
        if not future_annotations:
            args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            if node.args.vararg:
                args.append(node.args.vararg)
            if node.args.kwarg:
                args.append(node.args.kwarg)
            result += [item.annotation for item in args if item.annotation]
            if node.returns:
                result.append(node.returns)
        return result
    if isinstance(node, ast.ClassDef):
        result = [*node.decorator_list, *node.bases, *(item.value for item in node.keywords)]
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                result.extend(_eager_nodes(item, future_annotations))
            else:
                result.append(item)
        return result
    return []


def _reads(nodes):
    return {item.id for node in nodes for item in ast.walk(node)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}


def _string_lines(text):
    protected = set()
    try:
        for item in tokenize.generate_tokens(io.StringIO(text).readline):
            name = tokenize.tok_name[item.type]
            if item.type == tokenize.STRING or name.startswith('FSTRING'):
                if item.end[0] > item.start[0]:
                    protected.update(range(item.start[0] + 1, item.end[0] + 1))
    except (tokenize.TokenError, IndentationError):
        # Original source is parsed before rendering. A node fragment can begin
        # inside an indented suite; its string tokenization remains useful.
        pass
    return protected


def _indented(source, node, target_indent='    '):
    """Reindent code lines while keeping multiline string bytes unchanged."""
    original, position = _node_text(source, node)
    base_indent = _node_start(node)[1]
    protected = _string_lines(original)
    out, mappings = [], []
    source_cursor = position['start_byte']
    output_cursor = 0
    for number, line in enumerate(original.splitlines(keepends=True), 1):
        raw = line.encode()
        removed = 0
        if number > 1 and number not in protected:
            # AST columns count UTF-8 bytes. Leading indentation is ASCII.
            while removed < min(base_indent, len(raw)) and raw[removed:removed + 1] in {b' ', b'\t'}:
                removed += 1
        prefix = '' if number in protected else target_indent
        piece = prefix.encode() + raw[removed:]
        mappings.append({'source_span': {'path': source.path, 'start_byte': source_cursor + removed,
                                         'end_byte': source_cursor + len(raw)},
                         'relative_start_byte': output_cursor + len(prefix.encode()),
                         'relative_end_byte': output_cursor + len(piece)})
        out.append(piece)
        source_cursor += len(raw)
        output_cursor += len(piece)
    return b''.join(out).decode(), mappings, position


def wrap_python_script(source: Source) -> dict:
    """Return a wrapped Source and JSON provenance, or an explicit unsupported row."""
    base_record = {'source_path': source.path, 'source_sha256': hashlib.sha256(source.data).hexdigest(),
                   'language': source.language, 'origin': source.origin, 'step': source.step,
                   'execution_status': 'not_executed_by_preparation'}
    if source.language != 'python':
        return {'status': 'unsupported', 'source': source,
                'record': dict(base_record, status='unsupported', reason='script_wrapper_language_not_supported')}
    try:
        tree = ast.parse(source.code, filename=source.path)
        compile(source.code, source.path, 'exec')
    except (SyntaxError, ValueError, TypeError) as exc:
        return {'status': 'unsupported', 'source': source,
                'record': dict(base_record, status='unsupported', reason='script_parse_error', detail=str(exc))}
    try:
        return _wrap_parsed(source, tree, base_record)
    except UnsupportedScript as exc:
        return {'status': 'unsupported', 'source': source,
                'record': dict(base_record, status='unsupported', reason=str(exc))}


def _wrap_parsed(source, tree, base_record):
    retained, moved, main_guards = [], [], []
    future_annotations = any(isinstance(node, ast.ImportFrom) and node.module == '__future__'
                             and any(alias.name == 'annotations' for alias in node.names) for node in tree.body)
    for index, node in enumerate(tree.body):
        docstring = index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) or docstring:
            retained.append(node)
        elif _main_guard(node):
            main_guards.append(node)
            moved.extend(node.body)
        else:
            moved.append(node)
    if not moved:
        return {'status': 'unchanged', 'source': source,
                'record': dict(base_record, status='unchanged', reason='no_executable_script_statements')}
    assignments = _ModuleBindings()
    for node in moved:
        assignments.visit(node)
    if assignments.annotated:
        raise UnsupportedScript('annotated_module_binding_requires_annotation_lowering')
    if assignments.star_import:
        raise UnsupportedScript('star_import_inside_executable_context')
    # __name__ checks are interpreted only at an exact conventional main guard.
    guarded_names = {id(item) for guard in main_guards for item in ast.walk(guard.test)}
    if any(isinstance(node, ast.Name) and node.id == '__name__' and id(node) not in guarded_names for node in ast.walk(tree)):
        raise UnsupportedScript('script_name_introspection_outside_main_guard')
    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id in {'eval', 'exec', 'locals', 'globals'} for node in ast.walk(tree)):
        raise UnsupportedScript('dynamic_namespace_requires_script_scope')
    first_moved = min(node.lineno for node in moved)
    for node in retained:
        if node.lineno < first_moved:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise UnsupportedScript('import_after_executable_setup_requires_order_preservation')
        eager = _eager_nodes(node, future_annotations)
        if _reads(eager) & assignments.names:
            raise UnsupportedScript('eager_definition_depends_on_moved_script_binding')
        if (getattr(node, 'decorator_list', None)
                or any(isinstance(part, (ast.Call, ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)) for expression in eager for part in ast.walk(expression))):
            raise UnsupportedScript('eager_definition_effect_after_executable_setup')
    names = sorted(assignments.names)
    name = 'test_relational_script_' + _digest(source.path + '\0' + source.code)
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    identifiers.update(node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    if name in identifiers:
        raise UnsupportedScript('generated_wrapper_name_collision')
    output, mappings = [], []
    cursor = 0
    def append(text):
        nonlocal cursor
        start = cursor
        output.append(text)
        cursor += len(text.encode())
        return start
    # Preserve a leading shebang/encoding/comments before the first statement.
    if tree.body:
        first_line, first_column = _node_start(tree.body[0])
        header = b''.join(source.data.splitlines(keepends=True)[:first_line - 1]).decode()
        append(header)
    for node in retained:
        text, position = _node_text(source, node)
        start = append(text)
        mappings.append({'source_span': position, 'generated_span': {'path': source.path,
                         'start_byte': start, 'end_byte': cursor}, 'kind': 'retained_module_statement'})
        append('\n\n')
    append('def ' + name + '():\n')
    if names:
        append('    global ' + ', '.join(names) + '\n')
    wrapper_body_start = cursor
    for node in moved:
        text, copied, position = _indented(source, node)
        start = append(text)
        for item in copied:
            mappings.append({'source_span': item['source_span'], 'generated_span': {'path': source.path,
                             'start_byte': start + item['relative_start_byte'], 'end_byte': start + item['relative_end_byte']},
                             'kind': 'copied_script_line'})
        append('\n')
    code = ''.join(output)
    try:
        compile(code, source.path, 'exec')
    except (SyntaxError, ValueError) as exc:
        raise UnsupportedScript('wrapped_source_compile_error:' + str(exc)) from None
    wrapped = Source(source.path, code, source.language, origin=source.origin, step=source.step,
                     written_path=source.written_path)
    assertions = sum(isinstance(node, ast.Assert) for statement in moved for node in ast.walk(statement))
    record = dict(base_record, status='wrapped', wrapper_name=name,
                  wrapped_sha256=hashlib.sha256(wrapped.data).hexdigest(), global_bindings=names,
                  retained_statement_spans=[_node_text(source, node)[1] for node in retained],
                  moved_statement_spans=[_node_text(source, node)[1] for node in moved],
                  main_guard_spans=[_span(source, node) for node in main_guards],
                  body_span={'path': source.path, 'start_byte': wrapper_body_start, 'end_byte': cursor},
                  mappings=mappings, assertion_count=assertions,
                  observation_status='contains_source_assertions' if assertions else 'unchecked_output_or_no_assertion',
                  limitations=['shared module lifetime across generated test clones',
                               'external process state and arbitrary library effects not isolated',
                               'wrapper is a source transformation, not evidence of prior execution'])
    return {'status': 'wrapped', 'source': wrapped, 'record': record}


def prepare_script_sources(sources: Iterable[Source], *, origins=('trajectory',)) -> dict:
    """Wrap eligible historical modules before relation extraction.

    Existing registered tests remain unchanged. Python and TypeScript wrappers
    expose their framework/scoping assumptions; other languages remain explicit
    unsupported records.
    """
    result, records = [], []
    for source in sources:
        if source.origin not in origins:
            result.append(source)
            continue
        if any(unit.test and unit.node != source.root for unit in units(source)[0]):
            result.append(source)
            records.append({'source_path': source.path, 'status': 'unchanged', 'reason': 'registered_test_definitions_present'})
            continue
        prepared = wrap_typescript_script(source) if source.language == 'typescript' else wrap_python_script(source)
        result.append(prepared['source'])
        records.append(prepared['record'])
    return {'sources': result, 'records': records}


def wrap_typescript_script(source: Source) -> dict:
    """Wrap a standalone JS/TS module in one source-preserving Vitest callback.

    Imports remain module declarations. Helpers move with their lexical inputs
    into the callback: retaining helpers outside while moving const/let setup
    inside would break closures. Source order and template-string bytes remain
    unchanged. The new framework dependency is explicit in the record.
    """
    from anchor_retrieval.syntax import CALLS, FUNCTIONS, call_parts, child, walk

    base = {'source_path': source.path, 'source_sha256': hashlib.sha256(source.data).hexdigest(),
            'language': source.language, 'origin': source.origin, 'step': source.step,
            'execution_status': 'not_executed_by_preparation'}
    def unsupported(reason):
        return {'status': 'unsupported', 'source': source, 'record': dict(base, status='unsupported', reason=reason)}
    if source.language != 'typescript':
        return unsupported('script_wrapper_language_not_supported')
    if source.root.has_error:
        return unsupported('script_parse_error')
    retained, moved = [], []
    for node in source.root.named_children:
        if node.type in {'import_statement', 'comment', 'hash_bang_line'}:
            retained.append(node)
        elif node.type == 'export_statement':
            # An empty export marks module syntax and creates no binding.
            if ''.join(source.text(node).strip().rstrip(';').split()) == 'export{}':
                retained.append(node)
            else:
                return unsupported('exported_module_binding_requires_original_module_scope')
        elif node.type in {'internal_module', 'module', 'namespace_declaration', 'ambient_declaration'}:
            return unsupported('typescript_namespace_or_ambient_scope_not_supported')
        else:
            moved.append(node)
    if not moved:
        return {'status': 'unchanged', 'source': source,
                'record': dict(base, status='unchanged', reason='no_executable_script_statements')}
    # Direct eval can create/use bindings of its original lexical environment.
    if any(node.type in CALLS and source.text(call_parts(node)[0]) == 'eval' for node in walk(source.root)):
        return unsupported('dynamic_namespace_requires_script_scope')
    identifier = _digest(source.path + '\0' + source.code)
    name, registration = 'relational_script_' + identifier, '__relational_test_' + identifier
    if any(source.text(node) == registration for node in walk(source.root) if node.type == 'identifier'):
        return unsupported('generated_wrapper_name_collision')
    nested = FUNCTIONS | {'arrow_function', 'function_expression', 'generator_function', 'generator_function_declaration'}
    def owned_walk(node):
        yield node
        for part in node.named_children:
            if part.type not in nested:
                yield from owned_walk(part)
    asynchronous = any(node.type in {'await_expression', 'await'} for statement in moved for node in owned_walk(statement))
    output, mappings, cursor = [], [], 0
    def append(text):
        nonlocal cursor
        start = cursor
        output.append(text)
        cursor += len(text.encode())
        return start
    def position(node):
        return {'path': source.path, 'start_byte': node.start_byte, 'end_byte': node.end_byte,
                'line': node.start_point.row + 1, 'end_line': node.end_point.row + 1}
    for node in retained:
        start = append(source.text(node))
        mappings.append({'source_span': position(node), 'generated_span': {'path': source.path,
                         'start_byte': start, 'end_byte': cursor}, 'kind': 'retained_module_statement'})
        append('\n')
    append("import { test as " + registration + " } from 'vitest';\n\n")
    # Test discovery recognizes the registration spelling test(...). An alias
    # declaration inside module scope keeps the imported name collision-free.
    # The original script is moved wholly into a lexical block inside callback,
    # so even a source-local binding called test retains its original meaning.
    if 'test' in source.imports:
        # Existing imported test can be used when it really names Vitest's test.
        imported = source.imports.get('test')
        if imported != ('vitest', 'test'):
            return unsupported('test_registration_binding_collision')
    else:
        append('const test = ' + registration + ';\n')
    append('test(' + repr(name) + ', ' + ('async ' if asynchronous else '') + '() => {\n')
    body_start = cursor
    for statement in moved:
        raw = source.text(statement)
        protected = set()
        for item in walk(statement):
            if item.type in {'template_string', 'string'} and item.end_point.row > item.start_point.row:
                protected.update(range(item.start_point.row + 1, item.end_point.row + 1))
        source_cursor = statement.start_byte
        for relative_row, line in enumerate(raw.splitlines(keepends=True)):
            global_row = statement.start_point.row + relative_row
            prefix = '' if global_row in protected else '  '
            start = append(prefix + line)
            length = len(line.encode())
            mappings.append({'source_span': {'path': source.path, 'start_byte': source_cursor, 'end_byte': source_cursor + length},
                             'generated_span': {'path': source.path, 'start_byte': start + len(prefix), 'end_byte': cursor},
                             'kind': 'copied_script_line'})
            source_cursor += length
        append('\n')
    body_end = cursor
    append('});\n')
    code = ''.join(output)
    wrapped = Source(source.path, code, source.language, origin=source.origin, step=source.step, written_path=source.written_path)
    if wrapped.root.has_error:
        return unsupported('wrapped_source_parse_error')
    calls = [node for statement in moved for node in walk(statement) if node.type in CALLS]
    assertions = sum(source.text(call_parts(node)[0]).split('.')[0] in {'assert', 'expect'} for node in calls)
    record = dict(base, status='wrapped', wrapper_name=name,
                  wrapped_sha256=hashlib.sha256(wrapped.data).hexdigest(),
                  wrapper_import={'module': 'vitest', 'imported_name': 'test', 'name': registration},
                  asynchronous=asynchronous, assertion_count=assertions,
                  observation_status='contains_source_assertion_syntax' if assertions else 'unchecked_output_or_no_assertion',
                  retained_statement_spans=[position(node) for node in retained],
                  moved_statement_spans=[position(node) for node in moved], mappings=mappings,
                  body_span={'path': source.path, 'start_byte': body_start, 'end_byte': body_end},
                  binding_strategy='imports_module_scoped; executable_helpers_and_inputs_share_callback_scope',
                  limitations=['Vitest dependency and test harness must be available',
                               'external process state and arbitrary library effects not isolated',
                               'wrapper registration delays execution until the test callback runs'])
    return {'status': 'wrapped', 'source': wrapped, 'record': record}
