"""Integer comparison profiles from executed Go source, not static outcomes.

Only selected, source-identical function declarations are considered.  Operand
types come from lexical declarations and unique same-package function results.
The original expressions occur once as typed helper arguments; existing call
order and enclosing short circuit remain intact.  Unknowns are not relations.
No runtime value supplies an expected test result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import posixpath

from anchor_retrieval.syntax import Source, call_parts, child, walk


VERSION = 'go-integer-comparison-probe-v1'
TRACE_ENV = 'COMBINATION_COMPARISON_TRACE'
INTEGER_TYPES = frozenset({'int', 'int8', 'int16', 'int32', 'int64',
                           'uint', 'uint8', 'uint16', 'uint32', 'uint64', 'uintptr'})
COMPARATORS = {'<': 'lt', '<=': 'le', '==': 'eq', '!=': 'ne', '>=': 'ge', '>': 'gt'}
ARITHMETIC = frozenset({'+', '-', '*', '/', '%', '&', '|', '^', '&^', '<<', '>>'})
_UNTYPED = {'untyped_int', 'untyped_float'}


def _span(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _key(extent):
    return extent['path'], extent['start_byte'], extent['end_byte']


def _group(source):
    packages = [node for node in source.root.named_children if node.type == 'package_clause']
    name = source.text(packages[0].named_children[0]) if len(packages) == 1 else None
    return posixpath.dirname(source.lookup_path), name


def _names(node):
    if node is None:
        return []
    if node.type == 'identifier':
        return [node]
    return list(node.named_children) if node.type == 'expression_list' else []


def _combine_types(left, right):
    if left == right:
        return left
    if left in INTEGER_TYPES and right in _UNTYPED:
        return left
    if right in INTEGER_TYPES and left in _UNTYPED:
        return right
    if left in _UNTYPED and right in _UNTYPED:
        return 'untyped_float' if 'untyped_float' in {left, right} else 'untyped_int'
    return None


@dataclass
class _Value:
    type: str | None
    reads: set[str] = field(default_factory=set)
    calls: list[dict] = field(default_factory=list)
    may_panic: bool = False
    reason: str | None = None


class _Function:
    def __init__(self, analysis, source, node):
        self.analysis, self.source, self.node = analysis, source, node
        self.body = child(node, 'body')
        self.group = _group(source)
        self.bound_names = set()
        self.escaped_names = set()
        self.concurrent = False
        for item in walk(self.body):
            if item.type in {'var_spec', 'const_spec'}:
                self.bound_names.update(source.text(name) for name in item.children_by_field_name('name'))
            if item.type == 'short_var_declaration':
                self.bound_names.update(source.text(name) for name in _names(child(item, 'left')))
            if item.type == 'go_statement':
                self.concurrent = True
        self.environment = self._parameters(child(node, 'parameters'))
        self.environment.update(self._parameters(child(node, 'result')))
        self.bound_names.update(self.environment)
        for item in walk(self.body):
            if item.type == 'unary_expression' and source.text(child(item, 'operator')) == '&':
                self.escaped_names.update(source.text(name) for name in walk(child(item, 'operand'))
                                          if name.type == 'identifier')
            if item.type == 'func_literal':
                # Overapproximate lexical captures. A shadowed name can become
                # unknown, but cannot certify an escaped scalar as private.
                self.escaped_names.update(source.text(name) for name in walk(item)
                                          if name.type == 'identifier')

    def _primitive(self, node):
        name = self.source.text(node)
        if name in INTEGER_TYPES and name not in self.analysis.package_names[self.group]:
            return name
        return None

    def _parameters(self, node):
        result = {}
        if node is None or node.type != 'parameter_list':
            return result
        for parameter in node.named_children:
            if parameter.type != 'parameter_declaration':
                continue
            value_type = self._primitive(child(parameter, 'type'))
            for name in parameter.children_by_field_name('name'):
                result[self.source.text(name)] = value_type
        return result

    def infer(self, node, environment):
        if node is None:
            return _Value(None, reason='operand_source_unavailable')
        kind, text = node.type, self.source.text(node)
        if kind == 'identifier':
            return _Value(environment.get(text), {text}, reason=None if text in environment else 'nonlocal_operand_unknown')
        if kind in {'int_literal', 'rune_literal'}:
            return _Value('untyped_int')
        if kind == 'float_literal':
            return _Value('untyped_float')
        if kind == 'parenthesized_expression':
            return self.infer(node.named_children[0], environment)
        if kind == 'unary_expression':
            operator = self.source.text(child(node, 'operator'))
            if operator in {'+', '-', '^'}:
                return self.infer(child(node, 'operand'), environment)
            return _Value(None, reason='unsupported_unary_operand')
        if kind == 'binary_expression':
            operator = self.source.text(child(node, 'operator'))
            if operator not in ARITHMETIC:
                return _Value(None, reason='unsupported_binary_operand')
            left = self.infer(child(node, 'left'), environment)
            right = self.infer(child(node, 'right'), environment)
            value_type = left.type if operator in {'<<', '>>'} else _combine_types(left.type, right.type)
            if operator in {'<<', '>>'} and right.type not in INTEGER_TYPES | {'untyped_int'}:
                value_type = None
            return _Value(value_type, left.reads | right.reads, [*left.calls, *right.calls],
                          left.may_panic or right.may_panic or operator in {'/', '%', '<<', '>>'},
                          left.reason or right.reason)
        if kind == 'call_expression':
            function, arguments = call_parts(node)
            name = self.source.text(function)
            if function is None or function.type != 'identifier' or name in environment:
                return _Value(None, reason='callee_binding_not_static')
            declarations = self.analysis.functions.get((self.group, name), [])
            if len(declarations) != 1:
                return _Value(None, reason='callee_declaration_not_unique')
            target_source, target = declarations[0]
            result = child(target, 'result')
            if result is not None and result.type == 'parameter_list':
                entries = [p for p in result.named_children if p.type == 'parameter_declaration']
                if len(entries) != 1 or len(entries[0].children_by_field_name('name')) > 1:
                    return _Value(None, reason='multiple_return_values_unsupported')
                result = child(entries[0], 'type')
            return_type = target_source.text(result)
            if (return_type not in INTEGER_TYPES
                    or return_type in self.analysis.package_names[self.group]
                    or child(target, 'type_parameters') is not None):
                return _Value(None, reason='callee_result_not_primitive_integer')
            if any('variadic' in arg.type or 'spread' in arg.type for arg in arguments):
                return _Value(None, reason='spread_call_arguments_unsupported')
            reads = {self.source.text(item) for argument in arguments for item in walk(argument)
                     if item.type == 'identifier' and self.source.text(item) in environment}
            if any(item.type in {'func_literal', 'receive_statement'}
                   or item.type == 'unary_expression' and self.source.text(child(item, 'operator')) == '<-'
                   for argument in arguments for item in walk(argument)):
                return _Value(None, reason='call_argument_order_or_capture_unknown')
            return _Value(return_type, reads, [dict(callee_span=_span(target_source, target),
                callee_source_sha256=_sha(target_source.data), call_span=_span(self.source, node),
                result_type=return_type)])
        return _Value(None, reason='unsupported_operand_syntax:' + kind)

    def declarations(self, node, environment):
        if node.type in {'var_spec', 'const_spec'}:
            names = node.children_by_field_name('name')
            explicit = child(node, 'type')
            values = _names(child(node, 'value'))
            # All RHS expressions use the environment preceding this declaration.
            inferred_values = [self.infer(value, environment).type for value in values]
            for index, name in enumerate(names):
                inferred = inferred_values[index] if len(values) == len(names) else None
                if explicit is not None:
                    value_type = None if self.source.text(explicit) in environment else self._primitive(explicit)
                elif node.type == 'var_spec' and inferred in _UNTYPED:
                    value_type = 'int' if inferred == 'untyped_int' else None
                else:
                    value_type = inferred
                environment[self.source.text(name)] = value_type
        elif node.type == 'short_var_declaration':
            names, values = _names(child(node, 'left')), _names(child(node, 'right'))
            inferred = [self.infer(value, environment).type for value in values]
            for index, name in enumerate(names):
                if name.type != 'identifier':
                    continue
                value_type = inferred[index] if len(names) == len(values) else None
                if value_type in _UNTYPED:
                    value_type = 'int' if value_type == 'untyped_int' else None
                environment[self.source.text(name)] = value_type
        elif node.type in {'type_spec', 'type_alias'}:
            # Type identifiers and function-valued aliases cannot be treated
            # as ordinary primitive values or same-package callable names.
            environment[self.source.text(child(node, 'name'))] = None

    def comparison(self, node, environment):
        operator = self.source.text(child(node, 'operator'))
        if operator not in COMPARATORS:
            return
        left_node, right_node = child(node, 'left'), child(node, 'right')
        left, right = self.infer(left_node, environment), self.infer(right_node, environment)
        value_type = _combine_types(left.type, right.type)
        reason = left.reason or right.reason
        if reason is None and value_type not in INTEGER_TYPES:
            reason = 'primitive_integer_comparison_type_unresolved'
        if reason is None and self.concurrent:
            reason = 'concurrent_function_scope_unsupported'
        if reason is None and (left.calls or right.calls):
            if (left.reads | right.reads) & self.escaped_names:
                reason = 'call_can_observe_or_change_escaped_scalar'
            elif left.may_panic or right.may_panic:
                reason = 'panic_and_call_evaluation_order_unknown'
        if reason is not None:
            self.analysis.unknowns.append(dict(function_span=_span(self.source, self.node),
                comparison_span=_span(self.source, node), reason=reason))
            return
        original = _span(self.source, node)
        identity = _sha(json.dumps([self.source.path, _sha(self.source.data),
                        node.start_byte, node.end_byte, operator], separators=(',', ':')).encode())
        prefix = self.analysis.prefixes[self.group]
        helper = prefix + value_type + '_' + COMPARATORS[operator]
        after = '{}({}, {}, "{}")'.format(helper, self.source.text(left_node), self.source.text(right_node), identity)
        self.analysis.comparisons.append(dict(id=identity, original_span=original,
            function_span=_span(self.source, self.node), source_sha256=_sha(self.source.data),
            operator=operator, primitive_type=value_type, before=self.source.text(node), after=after,
            left=dict(span=_span(self.source, left_node), code=self.source.text(left_node), type=left.type),
            right=dict(span=_span(self.source, right_node), code=self.source.text(right_node), type=right.type),
            calls=[*left.calls, *right.calls],
            binding_scope='lexical scalar types; same-package source result declarations',
            runtime_status='unobserved'))
        self.analysis.helpers[self.group].add((value_type, operator))

    def conditions(self, node, environment):
        if node is None:
            return
        # A closure has a separate lexical environment. Its body is not one
        # of the selected complete declarations and cannot reuse this scope.
        if node.type == 'func_literal':
            return
        if node.type == 'binary_expression':
            self.comparison(node, environment)
        for item in node.named_children:
            self.conditions(item, environment)

    def statement(self, node, environment):
        if node is None or node.type == 'func_literal':
            return
        if node.type == 'block':
            self.block(node, environment)
        elif node.type == 'statement_list':
            for item in node.named_children:
                self.statement(item, environment)
        elif node.type in {'var_spec', 'const_spec', 'short_var_declaration', 'type_spec', 'type_alias'}:
            self.declarations(node, environment)
        elif node.type in {'var_declaration', 'const_declaration', 'type_declaration', 'var_spec_list'}:
            for item in node.named_children:
                self.statement(item, environment)
        elif node.type == 'if_statement':
            scoped = dict(environment)
            self.statement(child(node, 'initializer'), scoped)
            self.conditions(child(node, 'condition'), scoped)
            self.statement(child(node, 'consequence'), scoped)
            self.statement(child(node, 'alternative'), scoped)
        elif node.type in {'for_statement', 'expression_switch_statement', 'type_switch_statement', 'select_statement'}:
            scoped = dict(environment)
            self.statement(child(node, 'initializer'), scoped)
            for item in node.named_children:
                if item.type in {'range_clause', 'for_clause'}:
                    if item.type == 'range_clause':
                        for name in _names(child(item, 'left')):
                            scoped[self.source.text(name)] = None
                    else:
                        self.statement(child(item, 'initializer'), scoped)
            for item in node.named_children:
                if item.type in {'block', 'expression_case', 'type_case', 'communication_case', 'default_case'}:
                    self.statement(item, scoped)
        elif node.type in {'expression_case', 'type_case', 'communication_case', 'default_case', 'labeled_statement'}:
            scoped = dict(environment)
            for item in node.named_children:
                self.statement(item, scoped)

    def block(self, node, environment):
        scoped = dict(environment)
        for item in node.named_children:
            self.statement(item, scoped)

    def run(self):
        self.block(self.body, self.environment)


class _Analysis:
    def __init__(self, sources):
        self.sources = {source.path: source for source in sources}
        self.functions, self.package_names, self.prefixes, self.helpers = {}, {}, {}, {}
        self.comparisons, self.unknowns = [], []
        groups = {}
        for source in sources:
            group = _group(source)
            groups.setdefault(group, []).append(source)
            self.package_names.setdefault(group, set())
            for node in source.root.named_children:
                if node.type == 'function_declaration':
                    name = source.text(child(node, 'name'))
                    self.functions.setdefault((group, name), []).append((source, node))
                    self.package_names[group].add(name)
                elif node.type in {'var_declaration', 'const_declaration', 'type_declaration'}:
                    for item in walk(node):
                        if item.type in {'var_spec', 'const_spec', 'type_spec', 'type_alias'}:
                            self.package_names[group].update(source.text(name) for name in item.children_by_field_name('name'))
        for group, rows in groups.items():
            digest = _sha(json.dumps([(source.path, _sha(source.data)) for source in sorted(rows, key=lambda s: s.path)]).encode())
            prefix = '__gc_' + digest[:12] + '_'
            names = {source.text(node) for source in rows for node in walk(source.root)
                     if node.type in {'identifier', 'type_identifier', 'package_identifier'}}
            while any(name.startswith(prefix) for name in names):
                prefix += 'x'
            self.prefixes[group] = prefix
            self.helpers[group] = set()


def _runtime_source(package, prefix, helpers):
    header = '''package {package}
import (
    {prefix}json "encoding/json"
    {prefix}os "os"
    {prefix}sync "sync"
)
var {prefix}mutex {prefix}sync.Mutex
func {prefix}record(id, operator, relation string) {{
    defer func() {{ _ = recover() }}()
    path := {prefix}os.Getenv("{env}")
    if path == "" {{ return }}
    {prefix}mutex.Lock()
    defer {prefix}mutex.Unlock()
    file, err := {prefix}os.OpenFile(path, {prefix}os.O_CREATE|{prefix}os.O_WRONLY|{prefix}os.O_APPEND, 0600)
    if err != nil {{ return }}
    defer file.Close()
    _ = {prefix}json.NewEncoder(file).Encode(struct {{
        ID string `json:"id"`
        Operator string `json:"operator"`
        Relation string `json:"relation"`
    }}{{id, operator, relation}})
}}
'''.format(package=package, prefix=prefix, env=TRACE_ENV)
    for value_type, operator in sorted(helpers):
        header += '''
func {name}(left, right {type}, id string) bool {{
    result := left {operator} right
    relation := "="
    if left < right {{ relation = "<" }} else if left > right {{ relation = ">" }}
    {prefix}record(id, "{operator}", relation)
    return result
}}
'''.format(name=prefix + value_type + '_' + COMPARATORS[operator], type=value_type,
           operator=operator, prefix=prefix)
    return header


def instrument_sources(sources, function_spans):
    """Rewrite selected complete Go functions and return deterministic source facts.

    ``sources`` are complete ``Source`` objects, grouped by source directory and
    package clause. ``function_spans`` must identify complete function/method
    declarations by exact original UTF-8 coordinates. Optional source_sha256 is
    checked. Runtime helpers are separate same-package files. Native compilation
    and actual trace presence remain separate checks, never inferred here.
    """
    sources, function_spans = list(sources), list(function_spans)
    if any(not isinstance(source, Source) or source.language != 'go' for source in sources):
        raise ValueError('complete Go Source objects required')
    if len({source.path for source in sources}) != len(sources):
        raise ValueError('duplicate source path')
    analysis = _Analysis(sources)
    seen = set()
    for extent in sorted(function_spans, key=_key):
        if _key(extent) in seen:
            continue
        seen.add(_key(extent))
        source = analysis.sources.get(extent['path'])
        reason = None
        if source is None:
            reason = 'selected_source_unavailable'
        elif source.root.has_error or _group(source)[1] is None:
            reason = 'selected_source_parse_error'
        elif extent.get('source_sha256', _sha(source.data)) != _sha(source.data):
            reason = 'selected_source_sha_mismatch'
        matches = [] if source is None else [node for node in source.root.named_children
            if node.type in {'function_declaration', 'method_declaration'}
            and (node.start_byte, node.end_byte) == (extent['start_byte'], extent['end_byte'])]
        if reason is None and len(matches) != 1:
            reason = 'selected_function_span_not_unique_declaration'
        if reason is None and child(matches[0], 'body') is None:
            reason = 'selected_function_body_unavailable'
        if reason is not None:
            analysis.unknowns.append(dict(function_span=dict(extent), reason=reason))
        else:
            _Function(analysis, source, matches[0]).run()
    files = {source.path: source.code for source in sources}
    comparisons = []
    for row in sorted(analysis.comparisons, key=lambda row: _key(row['original_span'])):
        extent = row['original_span']
        # Nested integer comparisons can occur in a call argument, e.g.
        # boolToInt(x < limit) < 3. Instrument the supported innermost
        # comparison; retain the outer overlap explicitly as unknown.
        if any(other['original_span']['path'] == extent['path']
               and extent['start_byte'] <= other['original_span']['start_byte']
               and other['original_span']['end_byte'] <= extent['end_byte']
               and other['id'] != row['id'] for other in analysis.comparisons):
            analysis.unknowns.append(dict(function_span=row['function_span'], comparison_span=extent,
                                          reason='nested_comparison_rewrite_overlap'))
        else:
            comparisons.append(row)
    for group in analysis.helpers:
        analysis.helpers[group] = set()
    for row in comparisons:
        analysis.helpers[_group(analysis.sources[row['original_span']['path']])].add(
            (row['primitive_type'], row['operator']))
    for path, source in analysis.sources.items():
        edits = [row for row in comparisons if row['original_span']['path'] == path]
        previous = -1
        delta = 0
        for row in edits:
            extent = row['original_span']
            if extent['start_byte'] < previous:
                raise ValueError('overlapping comparison rewrite')
            previous = extent['end_byte']
            row['modified_span'] = dict(path=path, start_byte=extent['start_byte'] + delta,
                end_byte=extent['start_byte'] + delta + len(row['after'].encode()))
            delta += len(row['after'].encode()) - (extent['end_byte'] - extent['start_byte'])
        data = source.data
        for row in reversed(edits):
            extent = row['original_span']
            data = data[:extent['start_byte']] + row['after'].encode() + data[extent['end_byte']:]
        files[path] = data.decode()
    runtime_files = {}
    for group, helpers in sorted(analysis.helpers.items()):
        if not helpers:
            continue
        prefix = analysis.prefixes[group]
        representative = min((source for source in sources if _group(source) == group), key=lambda s: s.path)
        # The Go tool ignores files whose basename starts with '_' or '.'.
        path = posixpath.join(posixpath.dirname(representative.path), prefix.lstrip('_') + 'probe.go')
        if path in files:
            raise ValueError('runtime source path collision')
        runtime_files[path] = _runtime_source(group[1], prefix, helpers)
    return dict(version=VERSION, status='instrumented' if comparisons else 'unknown',
        files=files, runtime_files=runtime_files, comparisons=comparisons, unknowns=analysis.unknowns,
        source_sha256={source.path: _sha(source.data) for source in sources}, trace_env=TRACE_ENV,
        limits=['primitive integers only; no named types or method-call dispatch',
                'source types are not native compilation or execution proof',
                'missing runtime events never imply a relation or branch outcome',
                'profiles guide selection, never supply expected test values'])


def read_trace(path, comparisons):
    """Read observed events; retain missing, malformed and mismatched evidence."""
    expected = {row['id']: row for row in comparisons}
    events, errors = [], []
    try:
        lines = Path(path).read_text().splitlines()
    except (OSError, UnicodeError) as error:
        return dict(status='unknown', events=[], missing_ids=sorted(expected),
                    errors=[type(error).__name__ + ': ' + str(error)])
    for number, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
            if (not isinstance(event, dict) or event.get('id') not in expected
                    or event.get('operator') != expected[event['id']]['operator']
                    or event.get('relation') not in {'<', '=', '>'}):
                raise ValueError('event does not match source comparison')
            events.append(event)
        except (ValueError, TypeError, KeyError) as error:
            errors.append('line {}: {}'.format(number, error))
    missing = sorted(set(expected) - {event['id'] for event in events})
    status = 'unknown' if not events or errors else 'partial' if missing else 'observed'
    return dict(status=status,
                events=events, missing_ids=missing, errors=errors)
