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
                           'line': node.start_point.row + 1, 'end_line': node.end_point.row + 1, **meta})
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
            name = self.source.text(receiver).split('.')[0]
            if name in self.env:
                names.append(name)
        # Unknown/helper functions may mutate object arguments. Preserve an explicit may edge.
        for arg in args:
            if arg.type == 'identifier' and self.source.text(arg) in self.env:
                name = self.source.text(arg)
                if any(not t.startswith('@builtin:') or t in {'@builtin:list', '@builtin:dict', '@builtin:set'}
                       for t in self.env[name].types):
                    names.append(name)
        for name in set(names):
            old = self.env[name]
            merged = self.add('may_effect', name, node, [old, value], types=old.types,
                              constants=old.constants, regexes=old.regexes, variable=name)
            self.edge_kinds[merged.id, value.id] = 'may_effect'
            self.env[name] = merged

    def assign(self, target, value: Value, rhs=None):
        if target is None:
            return
        text = self.source.text(target)
        if target.type in {'tuple_pattern', 'pattern_list', 'expression_list', 'tuple', 'list_pattern', 'array_pattern'}:
            children = target.named_children
            for i, part in enumerate(children):
                projected = self.add('projection', self.source.text(part), part, [value], types=value.types)
                if value.regexes and rhs is not None and self.source.text(rhs).endswith('.groups()'):
                    for regex in value.regexes:
                        self.nodes[projected.id]['factor'] = self.index.factor_key(regex, i + 1)
                self.assign(part, projected)
            return
        defined = self.add('definition', text, target, [value], types=value.types,
                           constants=value.constants, regexes=value.regexes, variable=text)
        if rhs is not None and rhs.type in ATTRS:
            self.nodes[defined.id]['alias'] = self.source.text(rhs)
        self.env[text] = defined
        if target.type in ATTRS:
            obj, field = attr_parts(target)
            base = self.source.text(obj)
            if base in {'self', 'cls'} or (base in self.unit.param_types and self.unit.owner):
                self.fields[self.source.text(field)].append(defined.id)

    def _assert(self, node, actual, expected='', predicate='assert', incidental=False):
        value = self.expression(actual)
        anchor = self.add('assertion', self.source.text(node), node, [value])
        self.assertions.append(Assertion(anchor.id, node.start_point.row + 1, node.end_point.row + 1,
                                        self.source.text(node), self.source.text(actual), self.fields_in(actual),
                                        predicate, expected, incidental))

    def assertion_call(self, node) -> bool:
        if node.type not in CALLS:
            return False
        fn, args = call_parts(node)
        name = self.source.text(fn)
        if self.source.language == 'go' and re.match(r'^(require|assert)\.', name) and len(args) >= 2:
            method = name.split('.')[-1]
            binary = method in {'Equal', 'NotEqual', 'Same', 'NotSame', 'Contains', 'NotContains', 'Len', 'Greater', 'Less'}
            actual = args[2] if binary and len(args) >= 3 and method not in {'Contains', 'NotContains', 'Len'} else args[1]
            expected = self.source.text(args[1] if actual != args[1] else args[2]) if len(args) >= 3 else ''
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
        elif kind in {'assignment', 'augmented_assignment', 'assignment_statement', 'short_var_declaration', 'variable_declarator', 'named_expression'}:
            target = child(node, 'left', 'name')
            rhs = child(node, 'right', 'value')
            if rhs is not None:
                value = self.expression(rhs)
                if kind == 'augmented_assignment' and self.source.text(target) in self.env:
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
        elif kind in {'lexical_declaration', 'variable_declaration', 'var_declaration', 'const_declaration', 'var_spec', 'const_spec'}:
            for n in node.named_children:
                self.statements(n)
        elif kind in {'if_statement', 'for_statement', 'while_statement', 'for_in_statement', 'range_clause', 'switch_statement', 'expression_switch_statement', 'try_statement', 'with_statement'}:
            condition = child(node, 'condition', 'value', 'right')
            if condition is not None:
                self.guards.append(self.expression(condition).id)
            # A walrus definition in a condition reaches the body.
            before = dict(self.env)
            environments = [before]
            for branch in node.named_children:
                if branch == condition:
                    continue
                if branch.type in BLOCKS or branch.type in {'else_clause', 'elif_clause', 'except_clause', 'finally_clause', 'case_statement', 'range_clause'}:
                    self.env = dict(before)
                    self.statements(branch)
                    environments.append(dict(self.env))
                elif kind in {'for_statement', 'for_in_statement'}:
                    self.statements(branch)
            if condition is not None:
                self.guards.pop()
            self.env = dict(before)
            for name in set().union(*(e.keys() for e in environments)):
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
