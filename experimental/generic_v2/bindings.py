"""Local lexical/arity checks for source-backed expression replacement.

This experimental check never imports or runs the subject. It is deliberately
three-valued: an unknown external name, receiver type or signature is NOT a
rejection. ``compatible`` means only that the implemented mechanical checks
passed, not that the expression has the right semantics or a valid oracle.

All reported spans refer to the edited source. Only inserted references and
calls containing the edit are checked; pre-existing syntax errors are reported
separately. No library names, testing APIs or repository IDs are used.
"""
from __future__ import annotations

import builtins
from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping

from anchor_retrieval.syntax import CALLS, Source, call_parts, child, walk

_FUNCTIONS = {'function_definition', 'function_declaration', 'function_expression',
              'arrow_function', 'lambda', 'func_literal', 'method_declaration', 'method_definition'}
_DECL_FUNCTIONS = {'function_definition', 'function_declaration'}
_CLASSES = {'class_definition', 'class_declaration', 'class'}
_CONDITIONAL = {'if_statement', 'for_statement', 'while_statement', 'try_statement',
                'except_clause', 'case_clause', 'switch_case', 'for_in_statement'}
_TYPES = {'type', 'type_annotation', 'type_arguments', 'type_parameters',
          'generic_type', 'interface_declaration', 'type_alias_declaration'}
_PATTERNS = {'identifier', 'shorthand_property_identifier_pattern'}
_NONCALLABLE = {'integer', 'float', 'string', 'true', 'false', 'none', 'list',
                'tuple', 'dictionary', 'set', 'int_literal', 'float_literal',
                'imaginary_literal', 'interpreted_string_literal', 'raw_string_literal',
                'rune_literal', 'number', 'array', 'object', 'null', 'undefined', 'nil'}
_GO_PREDECLARED = set('''any bool byte comparable complex64 complex128 error float32
    float64 int int8 int16 int32 int64 rune string uint uint8 uint16 uint32 uint64
    uintptr true false iota nil append cap clear close complex copy delete imag len
    make max min new panic print println real recover'''.split())


def _span(node):
    return {'start_byte': node.start_byte, 'end_byte': node.end_byte}


def _field(node):
    if node.parent is None:
        return None
    return next((node.parent.field_name_for_child(i) for i, c in enumerate(node.parent.children)
                 if c == node), None)


def _unwrap(node):
    while node is not None and node.type in {'parenthesized_expression', 'expression_list'} and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


@dataclass(frozen=True)
class Parameter:
    name: str | None
    mode: str = 'positional'
    required: bool = True


@dataclass(frozen=True)
class Signature:
    parameters: tuple[Parameter, ...]
    return_count: int | None
    unknowns: tuple[str, ...] = ()


@dataclass
class _Binding:
    name: str
    node: object
    scope: '_Scope'
    kind: str
    available_from: int
    signature: Signature | None = None
    noncallable: bool = False
    conditional: bool = False

    @property
    def id(self):
        return f'{self.scope.id}:{self.name}:{self.node.start_byte}'


@dataclass
class _Scope:
    node: object
    kind: str
    parent: '_Scope | None'
    bindings: dict[str, list[_Binding]] = field(default_factory=dict)
    directives: set[str] = field(default_factory=set)

    @property
    def id(self):
        return f'{self.kind}@{self.node.start_byte}'


def _pattern_names(node):
    if node is None:
        return []
    if node.type in _PATTERNS:
        return [node]
    if node.type in {'attribute', 'subscript', 'member_expression', 'selector_expression', 'subscript_expression'}:
        return []  # Writes through a value do not create a lexical binding.
    if node.type in {'pair_pattern', 'pair'}:
        return _pattern_names(child(node, 'value'))
    if node.type in {'assignment_pattern', 'object_assignment_pattern'}:
        return _pattern_names(child(node, 'left'))
    if node.type in {'typed_parameter', 'required_parameter', 'optional_parameter', 'default_parameter',
                     'typed_default_parameter'}:
        pattern = child(node, 'name', 'pattern')
        if pattern is None:
            pattern = next((c for c in node.named_children if c.type not in _TYPES), None)
        return _pattern_names(pattern)
    return [n for c in node.named_children if c.type not in _TYPES for n in _pattern_names(c)]


def _signature(source, node):
    params = child(node, 'parameters')
    if params is None:
        # TS single unparenthesized arrow argument.
        single = child(node, 'parameter')
        if single is not None:
            return Signature((Parameter(source.text(single)),), 1)
        return None
    if source.language == 'python' and node.parent and node.parent.type == 'decorated_definition':
        return None  # The decorator may replace the callable.
    result, unknowns = [], []
    kwonly = False
    for item in params.named_children:
        kind = item.type
        if kind == 'comment':
            continue
        if kind == 'positional_separator':
            result = [Parameter(p.name, 'posonly', p.required) for p in result]
            continue
        if kind == 'keyword_separator':
            kwonly = True
            continue
        if source.language == 'go':
            names = item.children_by_field_name('name')
            mode = 'varargs' if kind == 'variadic_parameter_declaration' else 'positional'
            result.extend(Parameter(source.text(n) if n else None, mode, mode != 'varargs')
                          for n in (names or [None]))
            continue
        names = _pattern_names(item)
        name = source.text(names[0]) if len(names) == 1 else None
        if source.language == 'python':
            text = source.text(item).lstrip()
            mode = 'kwargs' if text.startswith('**') else 'varargs' if text.startswith('*') else 'kwonly' if kwonly else 'poskw'
            required = child(item, 'value') is None and mode not in {'varargs', 'kwargs'}
            if mode == 'varargs':
                kwonly = True
        else:
            pattern = child(item, 'pattern')
            mode = 'varargs' if pattern and pattern.type == 'rest_pattern' else 'positional'
            required = kind != 'optional_parameter' and child(item, 'value') is None and mode != 'varargs'
            if name == 'this':
                continue  # TypeScript's fake receiver parameter consumes no argument.
        if name is None and source.language == 'python':
            unknowns.append('unsupported_parameter_pattern')
        result.append(Parameter(name, mode, required))
    returns = 1
    if source.language == 'go':
        ret = child(node, 'result')
        returns = 0 if ret is None else 1
        if ret is not None and ret.type == 'parameter_list':
            returns = sum(max(1, len(p.children_by_field_name('name')))
                          for p in ret.named_children if p.type != 'comment')
    return Signature(tuple(result), returns, tuple(unknowns))


class _Index:
    def __init__(self, source, go_package_names=None):
        self.source = source
        self.go_package_names = go_package_names
        self.root = _Scope(source.root, 'module', None)
        self.scopes = {source.root.id: self.root}
        self.declarations = set()
        self.scope_for = {}
        self.writes = []
        self._visit(source.root, self.root)

    def _add(self, scope, name_node, kind, start, *, value=None, function=None, conditional=False):
        if name_node is None:
            return
        name = self.source.text(name_node)
        if name == '_' and self.source.language == 'go':
            return
        self.declarations.add(name_node.id)
        value = _unwrap(value)
        signature = _signature(self.source, function or value) if (function or (value and value.type in _FUNCTIONS)) else None
        binding = _Binding(name, name_node, scope, kind, start, signature,
                           bool(value and value.type in _NONCALLABLE), conditional)
        scope.bindings.setdefault(name, []).append(binding)

    def _function_scope(self, scope):
        while scope.parent is not None and scope.kind not in {'function', 'module'}:
            scope = scope.parent
        return scope

    def _conditional(self, node, scope):
        if self.source.language != 'python':
            return False
        current = node.parent
        while current is not None and current != scope.node:
            if current.type in _CONDITIONAL:
                return True
            current = current.parent
        return False

    def _visit(self, node, scope):
        language = self.source.language
        kind = node.type
        self.scope_for[node.id] = scope
        if kind in _FUNCTIONS:
            name = child(node, 'name')
            if kind in _DECL_FUNCTIONS:
                hoisted = language in {'go', 'typescript'}
                self._add(scope, name, 'function', scope.node.start_byte if hoisted else node.end_byte,
                          function=node, conditional=self._conditional(node, scope))
            nested = _Scope(node, 'function', scope)
            self.scopes[node.id] = nested
            self.scope_for[node.id] = nested
            if name is not None:
                self.declarations.add(name.id)
                # Named function expressions are private to their own body.
                if kind == 'function_expression':
                    self._add(nested, name, 'function', node.start_byte, function=node)
            params = child(node, 'parameters', 'parameter')
            if params is not None:
                for p in params.named_children if params.type != 'identifier' else [params]:
                    if language == 'go':
                        names = p.children_by_field_name('name')
                    else:
                        names = _pattern_names(p)
                    for n in names:
                        self._add(nested, n, 'parameter', node.start_byte)
                        annotation = child(p, 'type')
                        if annotation is not None and annotation.type == 'type_annotation' and len(annotation.named_children) == 1:
                            annotation = annotation.named_children[0]
                        if annotation is not None and annotation.type in {'function_type', 'func_type'}:
                            nested.bindings[self.source.text(n)][-1].signature = _signature(self.source, annotation)
            receiver = child(node, 'receiver')
            if receiver is not None:
                for p in receiver.named_children:
                    for n in p.children_by_field_name('name'):
                        self._add(nested, n, 'parameter', node.start_byte)
            # Go named results are local variables as well as a result signature.
            if language == 'go':
                ret = child(node, 'result')
                if ret is not None and ret.type == 'parameter_list':
                    for p in ret.named_children:
                        for n in p.children_by_field_name('name'):
                            self._add(nested, n, 'parameter', node.start_byte)
            for c in node.named_children:
                if c != name:
                    self._visit(c, nested)
            return
        if kind in _CLASSES:
            name = child(node, 'name')
            self._add(scope, name, 'class', node.end_byte)
            nested = _Scope(node, 'class', scope)
            self.scopes[node.id] = nested
            for c in node.named_children:
                if c != name:
                    self._visit(c, nested)
            return
        if language == 'typescript' and kind == 'function_signature':
            # Overload declarations require union-signature resolution. Do not
            # apply the implementation signature as if it were the only one.
            self._add(scope, child(node, 'name'), 'overload', 0)
            return
        if node != self.source.root and ((language != 'python' and kind in {'block', 'statement_block'}) or
                (language == 'go' and kind in {'if_statement', 'for_statement', 'expression_switch_statement', 'type_switch_statement'}) or
                (language == 'typescript' and kind in {'for_statement', 'for_in_statement', 'catch_clause'}) or
                (language == 'python' and kind in {'list_comprehension', 'set_comprehension', 'dictionary_comprehension', 'generator_expression'})):
            scope = _Scope(node, 'comprehension' if language == 'python' else 'block', scope)
            self.scopes[node.id] = scope
            self.scope_for[node.id] = scope
        if kind in {'global_statement', 'nonlocal_statement'}:
            scope.directives.update(self.source.text(c) for c in node.named_children if c.type == 'identifier')
        if language == 'typescript' and kind == 'catch_clause':
            for name in _pattern_names(child(node, 'parameter')):
                self._add(scope, name, 'parameter', node.start_byte)
        if kind in {'import_statement', 'import_from_statement', 'import_declaration'}:
            self._imports(node, scope)
            return
        if language == 'python' and kind in {'assignment', 'augmented_assignment', 'named_expression', 'for_statement', 'for_in_clause', 'as_pattern'}:
            lhs = child(node, 'left', 'name', 'alias')
            rhs = child(node, 'right', 'value')
            for name in _pattern_names(lhs):
                visible = rhs.end_byte if kind in {'for_statement', 'for_in_clause'} and rhs is not None else node.end_byte
                self._add(scope, name, 'local', visible, value=rhs if lhs == name and kind not in {'for_statement', 'for_in_clause'} else None,
                          conditional=self._conditional(node, scope) or kind == 'for_statement')
        if language == 'typescript' and kind == 'variable_declarator':
            lhs, rhs = child(node, 'name'), child(node, 'value')
            is_var = node.parent is not None and node.parent.type == 'variable_declaration'
            destination = self._function_scope(scope) if is_var else scope
            for name in _pattern_names(lhs):
                self._add(destination, name, 'var' if is_var else 'local', node.end_byte,
                          value=rhs if lhs == name else None)
        if language == 'go' and kind in {'short_var_declaration', 'var_spec', 'const_spec'}:
            names = node.children_by_field_name('name') if kind != 'short_var_declaration' else _pattern_names(child(node, 'left'))
            rhs = child(node, 'right', 'value')
            values = list(rhs.named_children) if rhs is not None and rhs.type == 'expression_list' else [rhs]
            for i, name in enumerate(names):
                self._add(scope, name, 'local', scope.node.start_byte if scope.kind == 'module' else node.end_byte,
                          value=values[i] if len(values) == len(names) else None)
        if language == 'go' and kind in {'type_spec', 'type_alias', 'type_parameter_declaration'}:
            for name in node.children_by_field_name('name'):
                self._add(scope, name, 'type', scope.node.start_byte if scope.kind == 'module' else name.start_byte)
        if kind in {'assignment_expression', 'assignment_statement', 'augmented_assignment', 'update_expression'}:
            for name in _pattern_names(child(node, 'left', 'argument')):
                self.writes.append((self.source.text(name), name, node.start_byte))
                # Go '=' writes an existing binding; it never declares one.
                # Retain it as a checked reference, including assignment-only edits.
                if language != 'go':
                    self.declarations.add(name.id)
        if language == 'go' and kind == 'range_clause':
            # Range declaration is visible in the loop body, not the range source.
            if ':=' in self.source.text(node):
                for name in _pattern_names(child(node, 'left')):
                    self._add(scope, name, 'local', node.end_byte)
        for c in node.named_children:
            self._visit(c, scope)

    def _imports(self, node, scope):
        language = self.source.language
        if language == 'go':
            for item in walk(node):
                if item.type == 'import_spec':
                    alias = child(item, 'name')
                    path = child(item, 'path')
                    if alias is None and path is not None:
                        # Source already provides the language's package-name convention.
                        for name, (module, _) in self.source.imports.items():
                            if self.source.text(path).strip('"`') == module:
                                binding = _Binding(name, path, scope, 'import', 0)
                                scope.bindings.setdefault(name, []).append(binding)
                    else:
                        self._add(scope, alias, 'import', 0)
        elif language == 'typescript':
            for item in walk(node):
                if item.type == 'import_specifier':
                    self._add(scope, child(item, 'alias', 'name'), 'import', 0)
                elif item.type == 'namespace_import':
                    self._add(scope, next((c for c in item.named_children if c.type == 'identifier'), None), 'import', 0)
                elif item.type == 'import_clause':
                    for c in item.named_children:
                        if c.type == 'identifier':
                            self._add(scope, c, 'import', 0)
        else:
            # Tree-sitter distinguishes from-module syntax from imported aliases.
            names = node.children_by_field_name('name')
            for item in names:
                alias = child(item, 'alias')
                if alias is not None:
                    self._add(scope, alias, 'import', node.end_byte)
                else:
                    name = next((c for c in walk(item) if c.type == 'identifier'), None)
                    self._add(scope, name, 'import', node.end_byte)

    def _crosses_function(self, inner, outer):
        while inner is not None and inner != outer:
            if inner.kind == 'function':
                return True
            inner = inner.parent
        return False

    def resolve(self, name, node):
        start_scope = self.scope_for.get(node.id, self.root)
        scope = start_scope
        while scope is not None:
            if scope.kind == 'comprehension':
                return None, 'unknown', 'comprehension_evaluation_order_unknown'
            if name in scope.directives:
                return None, 'unknown', 'global_or_nonlocal_directive'
            rows = scope.bindings.get(name, [])
            if rows:
                available = [b for b in rows if b.available_from <= node.start_byte]
                delayed = self._crosses_function(start_scope, scope)
                if delayed and len(rows) > 1:
                    return rows[0], 'unknown', 'outer_binding_may_change_before_invocation'
                if available:
                    b = max(available, key=lambda x: x.node.start_byte)
                    if b.conditional:
                        return b, 'unknown', 'conditional_definition'
                    return b, 'available', None
                b = min(rows, key=lambda x: x.node.start_byte)
                if delayed:
                    return b, 'unknown', 'deferred_outer_definition'
                if self.source.language == 'go':
                    scope = scope.parent  # Go local scope starts after its declaration.
                    continue
                if b.kind == 'var':
                    return b, 'unknown', 'hoisted_var_before_initializer'
                return b, 'invalid', 'use_before_local_definition'
            scope = scope.parent
            # Python methods do not close over a class namespace.
            if self.source.language == 'python' and scope is not None and scope.kind == 'class':
                scope = scope.parent
        if self.source.language == 'python' and name in vars(builtins):
            return None, 'available', 'language_builtin'
        if self.source.language == 'go' and self.go_package_names is not None:
            if name in _GO_PREDECLARED:
                return None, 'available', 'language_builtin'
            if name in self.go_package_names:
                return None, 'available', 'same_package_declaration'
            if '.' in self.root.bindings:
                return None, 'unknown', 'dot_import_members_unresolved'
            parent = node.parent
            if (parent is not None and parent.type == 'literal_element' and
                    parent.parent is not None and parent.parent.type == 'keyed_element' and
                    child(parent.parent, 'key') == parent):
                # A simple composite key can be a struct-field label, or a
                # map-key expression. Distinguishing aliases requires types.
                return None, 'unknown', 'composite_literal_key_kind_unknown'
            return None, 'invalid', 'undeclared_go_identifier'
        return None, 'unknown', 'external_or_unresolved_binding'

    def callable(self, node):
        node = _unwrap(node)
        if node is None:
            return None, False, 'unknown_callable'
        if node.type in _FUNCTIONS:
            return _signature(self.source, node), False, None
        if node.type == 'identifier':
            binding, status, reason = self.resolve(self.source.text(node), node)
            if binding is not None and status == 'available':
                if any(b.kind == 'overload' for b in binding.scope.bindings[binding.name]):
                    return None, False, 'overloaded_signature_unknown'
                for name, write, pos in self.writes:
                    target, _, _ = self.resolve(name, write)
                    if target is not None and target.id == binding.id and binding.node.start_byte < pos < node.start_byte:
                        return None, False, 'reassigned_callable'
                return binding.signature, binding.noncallable, None
            return None, False, reason
        if node.type in _NONCALLABLE:
            return None, True, None
        # Never borrow a method declaration just because its member name matches.
        return None, False, 'receiver_type_or_callable_unknown'


def _value_reference(index, node):
    if node.type not in {'identifier', 'shorthand_property_identifier'} or node.id in index.declarations:
        return False
    if index.source.language == 'go' and index.source.text(node) == '_':
        return False
    field = _field(node)
    if field in {'attribute', 'property', 'field', 'label'}:
        return False
    if field in {'name', 'key'} and node.parent.type in {'keyword_argument', 'pair', 'method_definition'}:
        return False
    parent = node.parent
    while parent is not None:
        if parent.type in _TYPES or parent.type.startswith('import'):
            return False
        if parent.type in _FUNCTIONS or parent.type in {'block', 'statement_block', 'module', 'program', 'source_file'}:
            break
        parent = parent.parent
    return True


def _arguments(source, args):
    positional, keywords, spread = [], [], False
    for arg in args:
        if arg.type == 'comment':
            continue
        if arg.type in {'list_splat', 'dictionary_splat', 'spread_element', 'variadic_argument'}:
            spread = True
        elif arg.type == 'keyword_argument':
            keywords.append(source.text(child(arg, 'name')))
        else:
            positional.append(arg)
    return positional, keywords, spread


def _arity_errors(signature, count, keywords, language):
    params = signature.parameters
    if signature.unknowns:
        return [], list(signature.unknowns)
    positional = [p for p in params if p.mode in {'positional', 'posonly', 'poskw'}]
    varargs = any(p.mode == 'varargs' for p in params)
    kwargs = any(p.mode == 'kwargs' for p in params)
    errors = []
    if count > len(positional) and not varargs:
        errors.append('too_many_positional_arguments')
    bound = {p.name for p in positional[:count]}
    if language != 'python':
        if count < sum(p.required for p in positional):
            errors.append('missing_required_arguments')
        return errors, []
    by_name = {p.name: p for p in params if p.name is not None and p.mode not in {'varargs', 'kwargs'}}
    seen = set()
    for name in keywords:
        if name in seen:
            errors.append('duplicate_keyword_argument')
        seen.add(name)
        p = by_name.get(name)
        if p is not None and p.mode != 'posonly':
            if name in bound:
                errors.append('multiple_values_for_argument')
            bound.add(name)
        elif not kwargs:
            errors.append('unexpected_keyword_argument')
    if any(p.required and p.mode not in {'varargs', 'kwargs'} and p.name not in bound for p in params):
        errors.append('missing_required_arguments')
    return sorted(set(errors)), []


def _go_expected_returns(call):
    parent = call.parent
    while parent is not None and parent.type in {'parenthesized_expression', 'expression_list'}:
        if parent.type == 'expression_list' and len(parent.named_children) != 1:
            return 1
        parent = parent.parent
    if parent is None or parent.type == 'expression_statement':
        return None
    if parent.type in {'short_var_declaration', 'assignment_statement', 'var_spec', 'const_spec'}:
        lhs = child(parent, 'left')
        return len(lhs.named_children) if lhs is not None else len(parent.children_by_field_name('name'))
    if parent.type in {'argument_list', 'arguments'}:
        # The outer call handles expansion of one multi-valued argument.
        return None if len(parent.named_children) == 1 else 1
    if parent.type == 'return_statement':
        return None  # Caller may add an enclosing-function signature check later.
    return 1


def _syntax_issues(source):
    return [(n.type, source.text(n)) for n in walk(source.root) if n.type == 'ERROR' or n.is_missing]


def _go_package_names(edited, package_sources):
    """Collect package-level declarations only, from explicitly complete inputs.

    The caller supplies all build-selected peer files of the same package.
    Imports and locals in sibling functions are never package declarations.
    The target file is replaced by the edited bytes even if a stale copy was given.
    """
    def package_name(source):
        clause = next(n for n in source.root.named_children if n.type == 'package_clause')
        return source.text(clause.named_children[-1])
    expected = package_name(edited)
    sources = [edited] + [Source(path, code, 'go') for path, code in package_sources.items()
                          if path != edited.path]
    names = set()
    for source in sources:
        if _syntax_issues(source) or package_name(source) != expected:
            raise ValueError('Complete Go package inputs must parse and belong to one package')
        index = _Index(source)
        names.update(name for name, rows in index.root.bindings.items()
                     if name != 'init' and any(row.kind != 'import' for row in rows))
    return names


def analyze_bindings(source: Source | str, language: str | None, at_byte: int,
                     replacement: str, *, end_byte: int | None = None,
                     imported_names: Iterable[str] = (), path: str | None = None,
                     go_package_sources: Mapping[str, str] | None = None) -> dict:
    """Check one exact UTF-8-byte expression edit without changing the source.

    ``end_byte`` should be provided from the donor span. If omitted, the smallest
    named node beginning at ``at_byte`` is replaced. ``imported_names`` lists
    imports the emitter has separately validated; they remain signature-unknown.
    A result with ``status == 'invalid'`` contains a demonstrated local mechanical
    conflict. Unknown results are eligible for an independent semantic gate.
    ``go_package_sources`` is an explicit completeness assertion: all build-selected
    same-package peers are supplied. An empty mapping means the target is the only
    file. With the default None, unresolved Go names remain unknown because a peer
    file may declare them. This option does not imply complete type checking.
    """
    if isinstance(source, str):
        if language is None:
            raise ValueError('language is required for a source string')
        source = Source(path or {'python': 'input.py', 'go': 'input.go', 'typescript': 'input.ts'}[language], source, language)
    elif language is not None and source.language != language:
        raise ValueError('source language mismatch')
    if end_byte is None:
        matches = [n for n in walk(source.root) if n.start_byte == at_byte]
        if not matches:
            raise ValueError('no node starts at at_byte; provide end_byte')
        end_byte = min(matches, key=lambda n: n.end_byte).end_byte
    if not 0 <= at_byte <= end_byte <= len(source.data):
        raise ValueError('invalid source byte span')
    try:
        edited_text = (source.data[:at_byte] + replacement.encode() + source.data[end_byte:]).decode()
    except UnicodeDecodeError:
        raise ValueError('span splits a UTF-8 code point') from None
    edited = Source(source.path, edited_text, source.language)
    right = at_byte + len(replacement.encode())
    errors, unknowns, references, calls = [], [], [], []
    old_syntax, new_syntax = _syntax_issues(source), _syntax_issues(edited)
    remaining = list(old_syntax)
    for issue in new_syntax:
        if issue in remaining:
            remaining.remove(issue)
        else:
            errors.append({'reason': 'introduced_syntax_error', 'detail': issue[0]})
    if source.language == 'python' and not new_syntax:
        # compile is parsing/code generation only; no subject import or execution.
        try:
            compile(edited_text, edited.path, 'exec')
        except SyntaxError as exc:
            try:
                compile(source.code, source.path, 'exec')
            except SyntaxError:
                unknowns.append({'reason': 'preexisting_python_compile_error'})
            else:
                errors.append({'reason': 'introduced_syntax_error', 'detail': exc.msg})
    if old_syntax:
        unknowns.append({'reason': 'preexisting_parse_errors', 'count': len(old_syntax)})
    if go_package_sources is not None and edited.language != 'go':
        raise ValueError('go_package_sources is only meaningful for Go')
    package_names = (_go_package_names(edited, go_package_sources)
                     if go_package_sources is not None and not new_syntax else None)
    index = _Index(edited, package_names)
    additions = set(imported_names)
    for node in walk(edited.root):
        if at_byte <= node.start_byte and node.end_byte <= right and _value_reference(index, node):
            name = edited.text(node)
            binding, status, reason = index.resolve(name, node)
            if binding is None and name in additions:
                status, reason = 'available', 'validated_import_addition'
            row = {'name': name, 'span': _span(node), 'status': status,
                   'binding_id': f'{edited.path}:{binding.id}' if binding else None,
                   'declaration_span': _span(binding.node) if binding else None,
                   'binding_kind': binding.kind if binding else None, 'reason': reason}
            references.append(row)
            if status == 'invalid':
                errors.append({'reason': reason, 'name': name, 'span': _span(node)})
            elif status == 'unknown':
                unknowns.append({'reason': reason, 'name': name, 'span': _span(node)})
        if node.type not in CALLS or node.end_byte <= at_byte or node.start_byte >= right:
            continue
        fn, args = call_parts(node)
        signature, noncallable, reason = index.callable(fn)
        row = {'callee': edited.text(fn), 'span': _span(node),
               'signature': asdict(signature) if signature else None, 'status': 'unknown'}
        if noncallable:
            row['status'] = 'invalid'
            errors.append({'reason': 'known_noncallable_value', 'span': _span(node)})
        elif signature is None:
            unknowns.append({'reason': reason or 'signature_unknown', 'span': _span(node)})
        else:
            positional, keywords, spread = _arguments(edited, args)
            count = len(positional)
            if edited.language == 'go' and count == 1 and positional[0].type in CALLS:
                inner_fn, _ = call_parts(positional[0])
                inner_sig, _, _ = index.callable(inner_fn)
                if inner_sig is not None:
                    count = inner_sig.return_count
                else:
                    spread = True
            if spread or count is None:
                reasons, undetermined = [], ['spread_or_return_arity_unknown']
            else:
                reasons, undetermined = _arity_errors(signature, count, keywords, edited.language)
            if edited.language == 'go':
                expected = _go_expected_returns(node)
                if expected is not None and signature.return_count != expected:
                    reasons.append('return_count_mismatch')
            row['status'] = 'invalid' if reasons else 'unknown' if undetermined else 'compatible'
            errors.extend({'reason': r, 'span': _span(node), 'callee': edited.text(fn)} for r in reasons)
            unknowns.extend({'reason': r, 'span': _span(node)} for r in undetermined)
        calls.append(row)
    return {'status': 'invalid' if errors else 'unknown' if unknowns else 'compatible',
            'bindings': references, 'calls': calls, 'errors': errors, 'unknowns': unknowns,
            'source_path': edited.path, 'baseline_parse_errors': len(old_syntax),
            'precision': 'lexical + explicit local arity; external types, effects and oracle unproved',
            'edited_span': {'start_byte': at_byte, 'end_byte': right}}
