"""Demand-driven local dependence graphs and conservative resolved call summaries.

This is a may-dependence prototype, not a sound whole-language points-to analysis.
Edges retain their reason. Branches are joined, loops are summarized once, and
receiver/argument effects are conservatively ordered. No target program is run.
"""
from __future__ import annotations

import ast
import collections
import re
from dataclasses import dataclass, field
from typing import Any

from .syntax import (ATTRS, BLOCKS, CALLS, FUNCTIONS, IDENTIFIERS, Source, Unit,
                     attr_parts, call_parts, canonical, child, literal, walk)


def _locally_rebound(unit: Unit, name: str) -> bool:
    """Conservative lexical shadow check; unrelated nested scopes may reject."""
    for node in walk(unit.body):
        if node.type in {'assignment', 'assignment_statement', 'short_var_declaration',
                         'variable_declarator', 'var_spec', 'const_spec'}:
            target = child(node, 'left', 'name')
            if target is not None and any(unit.source.text(n) == name for n in walk(target)
                                          if n.type == 'identifier'):
                return True
    return False


def standard_node_assertion(unit: Unit, node):
    """Recognize only calls proved to originate at the standard Node assert API."""
    source = unit.source
    if source.language != 'typescript' or node.type not in CALLS:
        return None
    fn, args = call_parts(node)
    parts = source.text(fn).split('.')
    if not parts or not all(re.fullmatch(r'[A-Za-z_$][\w$]*', p) for p in parts):
        return None
    imported = source.imports.get(parts[0])
    if imported is None or imported[0] not in {'assert', 'node:assert', 'assert/strict', 'node:assert/strict'}:
        return None
    if parts[0] in unit.params or _locally_rebound(unit, parts[0]):
        return None
    parent = node.parent
    while parent is not None:
        parameters = child(parent, 'parameters')
        if parameters is not None and any(source.text(n) == parts[0] for n in walk(parameters)
                                          if n.type == 'identifier'):
            return None
        if parent.type in BLOCKS:
            for declaration in parent.named_children:
                if declaration.type in {'lexical_declaration', 'variable_declaration'}:
                    for value in declaration.named_children:
                        name = child(value, 'name')
                        if name is not None and source.text(name) == parts[0]:
                            return None
        parent = parent.parent
    exported = imported[1]
    if len(parts) == 1:
        method = 'ok' if exported in {'default', 'strict'} else exported
    elif exported in {None, 'default', 'strict'}:
        tail = parts[1:]
        method = tail[-1] if len(tail) == 1 or (len(tail) == 2 and tail[0] == 'strict') else None
    else:
        return None
    binary = {'equal', 'notEqual', 'deepEqual', 'notDeepEqual', 'strictEqual',
              'notStrictEqual', 'deepStrictEqual', 'notDeepStrictEqual'}
    if method in binary and len(args) >= 2:
        return args[0], args[1], method
    if method == 'ok' and args:
        return args[0], None, 'truthy'
    return None


def standard_go_guard(unit: Unit, node):
    """A failure-only testing branch denotes the logical negation of its guard.

    Report arguments may read values but cannot invoke other calls or channel
    operations. An initializer is retained by Flow before extracting the oracle.
    """
    source = unit.source
    if source.language != 'go' or node.type != 'if_statement' or child(node, 'alternative') is not None:
        return None
    guard, body = child(node, 'condition'), child(node, 'consequence')
    if guard is None or body is None:
        return None
    statements = [n for n in body.named_children if n.type != 'comment']
    if len(statements) == 1 and statements[0].type == 'statement_list':
        statements = [n for n in statements[0].named_children if n.type != 'comment']
    if not statements:
        return None
    for statement in statements:
        if statement.type != 'expression_statement' or len(statement.named_children) != 1:
            return None
        call = statement.named_children[0]
        if call.type not in CALLS:
            return None
        fn, args = call_parts(call)
        if fn is None or fn.type not in ATTRS:
            return None
        receiver, method = attr_parts(fn)
        if receiver is None or receiver.type != 'identifier' or source.text(method) not in {'Fatal', 'Fatalf', 'Error', 'Errorf', 'Fail', 'FailNow'}:
            return None
        name = source.text(receiver)
        typename = unit.param_types.get(name, '').lstrip('*').split('.')
        if (len(typename) != 2 or typename[1] not in {'T', 'B', 'F', 'TB'}
                or source.imports.get(typename[0], ('',))[0] != 'testing'
                or _locally_rebound(unit, name)):
            return None
        for argument in args:
            for inner in walk(argument):
                if inner.type in CALLS or inner.type in {'receive_expression', 'send_statement'}:
                    return None
                if inner.type == 'unary_expression' and source.text(child(inner, 'operator')) == '<-':
                    return None
    actual, expected, predicate = guard, None, 'falsy'
    inverse = {'==': '!=', '!=': '==', '<': '>=', '<=': '>', '>': '<=', '>=': '<'}
    if guard.type == 'binary_expression':
        operator = source.text(child(guard, 'operator'))
        if operator in inverse:
            actual, expected = child(guard, 'left'), child(guard, 'right')
            predicate = inverse[operator]
            try:
                literal(source.text(actual))
                actual, expected = expected, actual
                predicate = {'<': '>', '>': '<', '<=': '>=', '>=': '<='}.get(predicate, predicate)
            except ValueError:
                pass
    elif guard.type == 'unary_expression' and source.text(child(guard, 'operator')) == '!':
        actual, predicate = child(guard, 'operand'), 'truthy'
    return actual, expected, predicate, child(node, 'initializer')


@dataclass
class Value:
    id: int
    types: frozenset[str] = frozenset()
    constants: tuple[str, ...] = ()
    regexes: frozenset[str] = frozenset()


@dataclass
class Call:
    node: int
    name: str
    args: list[Value]
    keywords: dict[str, Value]
    receiver: Value | None
    targets: list[tuple[str, str]]


@dataclass
class Assertion:
    node: int
    line: int
    end_line: int
    text: str
    observed: str
    fields: list[str]
    predicate: str
    expected: str
    incidental: bool
    expression_node: Any = None
    expected_expression_node: Any = None
    assertion_adapter: str = 'direct'


class Flow:
    def __init__(self, index, unit: Unit):
        self.index, self.unit, self.source = index, unit, unit.source
        self.nodes: list[dict] = []
        self.edges: dict[int, set[int]] = collections.defaultdict(set)
        self.edge_kinds: dict[tuple[int, int], str] = {}
        self.env: dict[str, Value] = {}
        self.calls: list[Call] = []
        self.assertions: list[Assertion] = []
        self.fields: dict[str, list[int]] = collections.defaultdict(list)
        self.returns: list[int] = []
        self.guards: list[int] = []
        self.cache: dict[tuple[int, int], Value] = {}
        for name in unit.params:
            typ = unit.param_types.get(name, '')
            types = self.index.type_names(typ)
            values = tuple(canonical(v) for v in unit.parameter_values.get(name, []))
            params_node = child(unit.node, 'parameters')
            parameter_node = next((n for n in walk(params_node) if n.type == 'identifier' and self.source.text(n) == name), unit.node) if params_node is not None else unit.node
            value = self.add('parameter', name, parameter_node, types=types, constants=values, parameter=name,
                             regexes=index.parameter_regexes.get((unit.id, name), ()))
            self.env[name] = value
            if unit.test:
                fixtures = self.index.local_functions(unit, name, fixture=True)
                if fixtures:
                    self.calls.append(Call(value.id, name, [], {}, None, [(u.id, 'fixture') for u in fixtures]))
                    value.types = frozenset(t for u in fixtures for t in self.index.return_types(u))
        for name, typ in unit.param_types.items():
            if name not in self.env:
                self.env[name] = self.add('receiver', name, unit.node, types=self.index.type_names(typ))
        if unit.owner and self.source.language == 'python':
            self.env['self'] = self.add('receiver', 'self', unit.node, types={unit.owner})
            self.env['cls'] = self.env['self']
        self.statements(unit.body)

    def add(self, kind, text, node, deps=(), types=(), constants=(), regexes=(), **meta) -> Value:
        idx = len(self.nodes)
        self.nodes.append({'id': idx, 'kind': kind, 'text': text[:600],
                           'line': node.start_point.row + 1, 'end_line': node.end_point.row + 1,
                           'start_byte': node.start_byte, 'end_byte': node.end_byte, **meta})
        if kind in {'parameter', 'receiver', 'join', 'unknown'}:
            # Synthetic graph nodes do not span the entire enclosing function/body.
            self.nodes[-1]['end_line'] = self.nodes[-1]['line']
        for dep in deps:
            did = dep.id if isinstance(dep, Value) else dep
            self.edges[idx].add(did)
            self.edge_kinds[idx, did] = 'value'
        for guard in self.guards:
            self.edges[idx].add(guard)
            self.edge_kinds[idx, guard] = 'control'
        return Value(idx, frozenset(types), tuple(constants), frozenset(regexes))

    def slice(self, roots, limit=8192) -> set[int]:
        todo, seen = list(roots), set()
        while todo and len(seen) < limit:
            node = todo.pop()
            if node in seen:
                continue
            seen.add(node)
            todo.extend(self.edges.get(node, ()))
        return seen

    def fields_in(self, node) -> list[str]:
        found = []
        for n in walk(node, stop_functions=True):
            if n.type in ATTRS:
                _, key = attr_parts(n)
                if key is not None and not (n.parent and n.parent.type in CALLS and child(n.parent, 'function') == n):
                    found.append(self.source.text(key))
            elif n.type in {'subscript', 'subscript_expression', 'index_expression'}:
                key = child(n, 'subscript', 'index')
                if key is not None:
                    try:
                        val = literal(self.source.text(key))
                        if isinstance(val, str):
                            found.append(val)
                    except ValueError:
                        pass
        return list(dict.fromkeys(found))

    def expression(self, node) -> Value:
        if node is None:
            return self.add('unknown', '', self.unit.node)
        src, kind, text = self.source, node.type, self.source.text(node)
        if kind in IDENTIFIERS:
            if text in self.env:
                value = self.env[text]
                return self.add('read', text, node, [value], types=value.types,
                                constants=value.constants, regexes=value.regexes, variable=text)
            constants = self.index.global_constants.get((src.path, text), ())
            regex = self.index.regex_names.get((src.path, text))
            types = {text} if text in self.index.classes else set()
            return self.add('global', text, node, types=types, constants=constants,
                            regexes=[regex] if regex else (), variable=text)
        if kind in {'string', 'raw_string_literal', 'interpreted_string_literal', 'integer', 'float',
                    'int_literal', 'float_literal', 'number', 'true', 'false', 'none', 'nil', 'null',
                    'undefined', 'template_string'}:
            try:
                value = literal(text)
                types = {f'@builtin:{type(value).__name__}'} if self.source.language == 'python' else set()
                return self.add('literal', text, node, constants=[canonical(value)], types=types)
            except ValueError:
                pass
        if kind in {'named_expression', 'assignment_expression'}:
            target, expr = child(node, 'name', 'left'), child(node, 'value', 'right')
            value = self.expression(expr)
            self.assign(target, value)
            return value
        if kind in ATTRS:
            obj, key = attr_parts(node)
            value = self.expression(obj)
            keytext = src.text(key)
            aliases = self.env.get(src.text(node))
            deps = [value] + ([aliases] if aliases else [])
            return self.add('field_read', text, node, deps, field=keytext,
                            types=self.index.attribute_types(value.types, keytext), regexes=value.regexes,
                            receiver_types=sorted(value.types))
        if kind in CALLS:
            fn, args = call_parts(node)
            receiver_node = attr_parts(fn)[0] if fn is not None and fn.type in ATTRS else None
            receiver = self.expression(receiver_node) if receiver_node is not None else None
            fntext = src.text(fn)
            positional, keywords = [], {}
            for arg in args:
                if arg.type == 'keyword_argument':
                    keywords[src.text(child(arg, 'name'))] = self.expression(child(arg, 'value'))
                else:
                    positional.append(self.expression(arg))
            targets = self.index.resolve(self.unit, fntext, receiver.types if receiver else set(), positional)
            types = set()
            for target, _ in targets:
                types.update(self.index.return_types(self.index.units[target]))
            simple = fntext.split('.')[-1]
            if simple in self.index.classes:
                types.add(simple)
            if simple == 'super':
                types.update(self.index.bases.get(self.unit.owner, []))
            if simple in {'list', 'tuple', 'set', 'iter', 'next', 'sorted'}:
                types.update(t for a in positional for t in a.types)
                if self.source.language == 'python' and simple in {'list', 'tuple', 'set'}:
                    types.add(f'@builtin:{simple}')
            deps = positional + list(keywords.values()) + ([receiver] if receiver else [])
            if fn is not None and fn.type == 'identifier' and fntext in self.env:
                deps.append(self.env[fntext])
                # Bound method aliases retain their original receiver/call target.
                aliastext = self.nodes[self.env[fntext].id].get('alias', '')
                if aliastext:
                    targets = self.index.resolve(self.unit, aliastext, set(), positional)
            regexes = receiver.regexes if receiver else frozenset()
            value = self.add('call', text, node, deps, types=types, regexes=regexes, call=fntext)
            self.calls.append(Call(value.id, fntext, positional, keywords, receiver, targets))
            if simple == 'group' and regexes and positional:
                for key in positional[0].constants:
                    for regex in regexes:
                        self.nodes[value.id]['factor'] = self.index.factor_key(regex, json_value(key))
            self._effect(node, value, receiver_node, args)
            return value
        if kind in {'type_assertion_expression', 'as_expression', 'type_cast_expression'}:
            operand = child(node, 'operand', 'expression') or (node.named_children[0] if node.named_children else None)
            value = self.expression(operand)
            typ = child(node, 'type')
            return self.add('cast', text, node, [value], types=self.index.type_names(src.text(typ)) or value.types)
        values = [self.expression(n) for n in node.named_children
                  if n.type not in {'comment', 'type_annotation', 'predefined_type'}]
        constants = ()
        if kind in {'parenthesized_expression', 'expression_list', 'tuple', 'list', 'array'} and len(values) == 1:
            constants = values[0].constants
        elif kind in {'binary_operator', 'binary_expression'} and len(values) == 2:
            # Small literal-only arithmetic/concatenation; never execute a call.
            if len(values[0].constants) == len(values[1].constants) == 1:
                left, right = map(json_value, (values[0].constants[0], values[1].constants[0]))
                op = src.text(child(node, 'operator'))
                try:
                    if op == '+':
                        constants = (canonical(left + right),)
                    elif op == '|':
                        constants = (canonical(left | right),)
                except TypeError:
                    pass
        types = {t for v in values for t in v.types}
        if self.source.language == 'python' and kind in {'list', 'dictionary', 'set', 'tuple'}:
            types.add('@builtin:' + {'dictionary': 'dict'}.get(kind, kind))
        return self.add(kind, text, node, values, types=types, constants=constants)

    def _effect(self, node, value, receiver, args):
        """Keep previous potentially stateful operations in later observations."""
        names = []
        if receiver is not None:
            name = self._state_root(receiver)
            if name is not None:
                names.append(name)
        # Unknown/helper functions may mutate object arguments. Preserve an explicit may edge.
        for arg in args:
            name = self._state_root(arg)
            if name is not None:
                types = self.env[name].types
                if not types or any(not t.startswith('@builtin:') or t in {'@builtin:list', '@builtin:dict', '@builtin:set'}
                                    for t in types):
                    names.append(name)
        for name in sorted(set(names)):
            self._state_effect(name, value, node)

    def _state_root(self, node):
        """Find a locally tracked access root, without claiming points-to facts."""
        while node is not None:
            if node.type == 'identifier':
                name = self.source.text(node)
                return name if name in self.env else None
            if node.type in ATTRS:
                node = attr_parts(node)[0]
            elif node.type in {'subscript', 'subscript_expression', 'index_expression'}:
                node = child(node, 'value', 'object', 'operand')
            elif node.type == 'keyword_argument':
                node = child(node, 'value')
            elif node.type in {'parenthesized_expression', 'unary_expression',
                               'list_splat', 'dictionary_splat'}:
                node = child(node, 'operand', 'argument') or next(iter(node.named_children), None)
            else:
                return None
        return None

    def _state_effect(self, name, value, node, address=()):
        old = self.env[name]
        merged = self.add('may_effect', name, node, [old, value, *address], types=old.types,
                          constants=old.constants, regexes=old.regexes, variable=name)
        self.edge_kinds[merged.id, value.id] = 'may_effect'
        self.env[name] = merged

    def assign(self, target, value: Value, rhs=None):
        if target is None:
            return
        text = self.source.text(target)
        if self.source.language == 'go' and target.type == 'identifier' and text == '_':
            return  # The RHS was evaluated, but Go's blank identifier has no binding.
        if target.type in {'tuple_pattern', 'pattern_list', 'expression_list', 'tuple', 'list_pattern', 'array_pattern'}:
            children = target.named_children
            for i, part in enumerate(children):
                projected = self.add('projection', self.source.text(part), part, [value], types=value.types)
                if value.regexes and rhs is not None and self.source.text(rhs).endswith('.groups()'):
                    for regex in value.regexes:
                        self.nodes[projected.id]['factor'] = self.index.factor_key(regex, i + 1)
                self.assign(part, projected)
            return
        address = []
        state_root = None
        if target.type in ATTRS:
            obj, _ = attr_parts(target)
            address.append(self.expression(obj))
            state_root = self._state_root(obj)
        elif target.type in {'subscript', 'subscript_expression', 'index_expression'}:
            obj = child(target, 'value', 'object', 'operand')
            address.append(self.expression(obj))
            index = child(target, 'subscript', 'index')
            if index is not None:
                address.append(self.expression(index))
            state_root = self._state_root(obj)
        defined = self.add('definition', text, target, [value], types=value.types,
                           constants=value.constants, regexes=value.regexes, variable=text)
        if rhs is not None and rhs.type in ATTRS:
            self.nodes[defined.id]['alias'] = self.source.text(rhs)
        self.env[text] = defined
        if state_root is not None:
            # Updating a field/element also changes later observations of the
            # receiver. Other names aliasing that receiver remain unproved.
            # The address controls the heap update, not the assigned field's
            # value provenance. Keep it on the state node so unrelated earlier
            # field writes do not pollute field-specific constructor summaries.
            self._state_effect(state_root, defined, target, address)
        if target.type in ATTRS:
            obj, field = attr_parts(target)
            base = self.source.text(obj)
            if base in {'self', 'cls'} or (base in self.unit.param_types and self.unit.owner):
                self.fields[self.source.text(field)].append(defined.id)

    def _assert(self, node, actual, expected='', predicate='assert', incidental=False, expected_node=None, adapter='direct'):
        value = self.expression(actual)
        anchor = self.add('assertion', self.source.text(node), node, [value])
        self.assertions.append(Assertion(anchor.id, node.start_point.row + 1, node.end_point.row + 1,
                                        self.source.text(node), self.source.text(actual), self.fields_in(actual),
                                        predicate, expected, incidental, actual, expected_node, adapter))

    def assertion_call(self, node) -> bool:
        if node.type not in CALLS:
            return False
        fn, args = call_parts(node)
        name = self.source.text(fn)
        standard = standard_node_assertion(self.unit, node)
        if standard is not None:
            actual, expected, predicate = standard
            self._assert(node, actual, self.source.text(expected), predicate,
                         expected_node=expected, adapter='node_assert_import')
            return True
        if self.source.language == 'go' and re.match(r'^(require|assert)\.', name) and len(args) >= 2:
            method = name.split('.')[-1]
            binary = method in {'Equal', 'NotEqual', 'Same', 'NotSame', 'Contains', 'NotContains', 'Len', 'Greater', 'Less'}
            actual = args[2] if binary and len(args) >= 3 and method not in {'Contains', 'NotContains', 'Len'} else args[1]
            expected = self.source.text(args[1] if actual != args[1] else args[2]) if len(args) >= 3 else ''
            if method in {'NoError', 'Error', 'Nil', 'NotNil', 'Empty', 'NotEmpty', 'True', 'False'}:
                # Unary predicates encode the expectation in the method name.
                # Additional arguments are diagnostics, not expected values.
                expected = ''
            self._assert(node, actual, expected, method, method in {'NoError', 'Error', 'NotNil', 'Nil'})
            return True
        if self.source.language == 'typescript' and fn is not None:
            expects = [n for n in walk(fn) if n.type in CALLS and self.source.text(call_parts(n)[0]) == 'expect']
            if expects:
                _, observations = call_parts(expects[0])
                if observations:
                    self._assert(node, observations[0], ', '.join(self.source.text(a) for a in args),
                                 name.rsplit('.', 1)[-1])
                    return True
        if self.source.language == 'python' and re.search(r'(^|\.)assert[A-Z_]', name) and args:
            self._assert(node, args[0], self.source.text(args[1]) if len(args) > 1 else '', name.rsplit('.', 1)[-1])
            return True
        if self.unit.test:
            targets = self.index.resolve(self.unit, name)
            helpers = [uid for uid, reason in targets if uid in self.index.oracle_helpers
                       and reason in {'local_symbol', 'import_symbol', 'package_symbol'}]
            if helpers:
                incidental = all(p in {'NoError', 'Error', 'NotNil', 'Nil'}
                                 for uid in helpers for p in self.index.oracle_helpers[uid])
                self._assert(node, node, predicate='assertion_helper', incidental=incidental)
                return True
        return False

    def statements(self, node):
        kind = node.type
        standard = standard_go_guard(self.unit, node)
        if standard is not None:
            actual, expected, predicate, initializer = standard
            previous = dict(self.env)
            if initializer is not None:
                self.statements(initializer)
            self._assert(node, actual, self.source.text(expected), predicate,
                         expected_node=expected, adapter='go_testing_failure_guard')
            if initializer is not None and initializer.type == 'short_var_declaration':
                target = child(initializer, 'left')
                for binding in walk(target) if target is not None else []:
                    if binding.type == 'identifier':
                        name = self.source.text(binding)
                        if name in previous:
                            self.env[name] = previous[name]
                        else:
                            self.env.pop(name, None)
            return
        if kind in BLOCKS:
            for n in node.named_children:
                self.statements(n)
        elif kind in FUNCTIONS or kind in {'class_definition', 'class_declaration', 'comment', 'import_statement', 'import_from_statement', 'import_declaration'}:
            return
        elif kind == 'assert_statement':
            if node.named_children:
                self._assert(node, node.named_children[0])
        elif kind == 'expression_statement':
            for n in node.named_children:
                if not self.assertion_call(n):
                    self.statements(n)
        elif kind in {'assignment', 'augmented_assignment', 'assignment_expression',
                      'augmented_assignment_expression', 'assignment_statement',
                      'short_var_declaration', 'variable_declarator', 'named_expression'}:
            target = child(node, 'left', 'name')
            rhs = child(node, 'right', 'value')
            if rhs is not None:
                value = self.expression(rhs)
                if kind in {'augmented_assignment', 'augmented_assignment_expression'} and self.source.text(target) in self.env:
                    old = self.env[self.source.text(target)]
                    value = self.add('update', self.source.text(node), node, [old, value], types=old.types | value.types)
                # Go one-to-one tuple assignments retain separate value provenance.
                lefts = target.named_children if target is not None and target.type == 'expression_list' else []
                rights = rhs.named_children if rhs.type == 'expression_list' else []
                if len(lefts) == len(rights) > 1:
                    for left, right in zip(lefts, rights):
                        self.assign(left, self.expression(right), right)
                else:
                    self.assign(target, value, rhs)
        elif kind in {'var_spec', 'const_spec'}:
            targets = node.children_by_field_name('name')
            rhs = child(node, 'value')
            rights = rhs.named_children if rhs is not None and rhs.type == 'expression_list' else []
            if len(targets) == len(rights) and targets:
                # Evaluate the complete RHS before introducing any new binding.
                values = [self.expression(right) for right in rights]
                for target, right, value in zip(targets, rights, values):
                    self.assign(target, value, right)
            else:
                value = self.expression(rhs) if rhs is not None else self.add(
                    'implicit_zero' if kind == 'var_spec' else 'unknown', '', node,
                    types=self.index.type_names(self.source.text(child(node, 'type'))))
                for target in targets:
                    projected = self.add('projection', self.source.text(target), target, [value], types=value.types)
                    self.assign(target, projected, rhs)
        elif kind in {'lexical_declaration', 'variable_declaration', 'var_declaration', 'const_declaration'}:
            for n in node.named_children:
                self.statements(n)
        elif kind in {'if_statement', 'for_statement', 'while_statement', 'for_in_statement', 'range_clause', 'switch_statement', 'expression_switch_statement', 'try_statement', 'with_statement'}:
            range_clause = next((n for n in node.named_children if n.type == 'range_clause'), None)
            condition = child(node, 'condition', 'value', 'right')
            if range_clause is not None:
                condition = child(range_clause, 'right')
            condition_value = self.expression(condition) if condition is not None else None
            # A walrus definition in a condition reaches the body. Iteration
            # definitions depend on the container, but zero iterations still
            # preserve the incoming environment at the join.
            before = dict(self.env)
            target = child(range_clause or node, 'left') if kind in {
                'for_statement', 'for_in_statement', 'range_clause'} else None
            if target is not None and condition_value is not None:
                iteration = self.add('iteration', self.source.text(target), target, [condition_value])
                self.assign(target, iteration)
            if kind == 'range_clause':
                return
            body_environment = dict(self.env)
            if condition is not None:
                self.guards.append(condition_value.id)
            environments = [before]
            for branch in node.named_children:
                if branch == condition or branch == range_clause or branch == target:
                    continue
                if branch.type in BLOCKS or branch.type in {'else_clause', 'elif_clause', 'except_clause', 'finally_clause', 'case_statement', 'range_clause'}:
                    self.env = dict(body_environment)
                    self.statements(branch)
                    environments.append(dict(self.env))
                elif kind in {'for_statement', 'for_in_statement'}:
                    self.statements(branch)
            if condition is not None:
                self.guards.pop()
            self.env = dict(before)
            for name in sorted(set().union(*(e.keys() for e in environments))):
                vals = {e[name].id: e[name] for e in environments if name in e}
                if len(vals) > 1:
                    self.env[name] = self.add('join', name, node, vals.values(),
                                              types={t for v in vals.values() for t in v.types})
                elif vals:
                    self.env[name] = next(iter(vals.values()))
        elif kind in {'return_statement', 'yield', 'yield_statement'}:
            self.returns.append(self.expression(node).id)
        elif kind in CALLS:
            if not self.assertion_call(node):
                self.expression(node)
        else:
            for n in node.named_children:
                self.statements(n)


def json_value(value: str) -> Any:
    import json
    return json.loads(value)
