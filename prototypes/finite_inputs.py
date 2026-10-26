"""Expose row-specific Python inputs using bounded, call-free evaluation.

Sources and existing corpus structures remain untouched. Each added donor is
still edited at its original expression span and carries one complete original
parameter row. The consumer must fix that row when materializing its proposal.
Rows must be immutable, JSON-exact literals with no syntactic parameter
rebinding; locale formatting, calls and additional decorators are excluded.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import copy
import hashlib
import json
import math
import re


MAX_TEXT = 32768
MAX_NODES = 512
MAX_DEPTH = 32
MAX_INT_BITS = 4096
MAX_EXPANSIONS = 8192
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
           ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)


class Unsupported(ValueError):
    pass


def _id(*values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def _bounded(value, *, json_row=False):
    nodes, characters = 0, 0

    def check(item, depth):
        nonlocal nodes, characters
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise Unsupported('literal_budget')
        kind = type(item)
        if kind is str:
            characters += len(item)
        elif kind is bytes and not json_row:
            characters += len(item)
        elif kind is int:
            if item.bit_length() > MAX_INT_BITS:
                raise Unsupported('integer_budget')
        elif kind is float:
            if not math.isfinite(item):
                raise Unsupported('nonfinite_number')
        elif kind in {bool, type(None)}:
            pass
        elif kind is list or (kind is tuple and not json_row):
            for nested in item:
                check(nested, depth + 1)
        elif kind is dict:
            for key, nested in item.items():
                if json_row and type(key) is not str:
                    raise Unsupported('row_type_not_preserved_by_corpus')
                check(key, depth + 1)
                check(nested, depth + 1)
        else:
            raise Unsupported('row_type_not_preserved_by_corpus' if json_row else 'unsupported_literal_type')
        if characters > MAX_TEXT:
            raise Unsupported('literal_text_budget')

    check(value, 0)
    return value


def _immutable(value):
    return type(value) in {str, bytes, int, float, bool, type(None)} or (
        type(value) is tuple and all(_immutable(item) for item in value))


def _evaluate(text, bindings):
    """Interpret a small AST grammar; never eval/compile/execute source."""
    if len(text) > MAX_TEXT:
        raise Unsupported('expression_text_budget')
    try:
        tree = ast.parse(text, mode='eval')
    except (SyntaxError, ValueError):
        raise Unsupported('expression_parse_error') from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise Unsupported('expression_node_budget')
    used = set()

    def evaluate(node, depth=0):
        if depth > MAX_DEPTH:
            raise Unsupported('expression_depth_budget')
        if isinstance(node, ast.Constant):
            result = node.value
        elif isinstance(node, ast.Name):
            if node.id not in bindings:
                raise Unsupported('unknown_expression_name')
            result = bindings[node.id]
            if not _immutable(result):
                raise Unsupported('mutable_parameter_value')
            used.add(node.id)
        elif isinstance(node, (ast.List, ast.Tuple)):
            values = [evaluate(value, depth + 1) for value in node.elts]
            result = tuple(values) if isinstance(node, ast.Tuple) else values
        elif isinstance(node, ast.Dict) and all(key is not None for key in node.keys):
            result = {evaluate(key, depth + 1): evaluate(value, depth + 1)
                      for key, value in zip(node.keys, node.values)}
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand, depth + 1)
            if type(value) not in {int, float, bool}:
                raise Unsupported('unsupported_unary_operand')
            result = +value if isinstance(node.op, ast.UAdd) else -value
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
            if type(left) in {str, bytes, list, tuple} and type(left) is type(right):
                if len(left) + len(right) > MAX_TEXT:
                    raise Unsupported('concatenation_budget')
            elif not (type(left) in {int, float, bool} and type(right) in {int, float, bool}):
                raise Unsupported('unsupported_add_operands')
            result = left + right
        elif isinstance(node, ast.JoinedStr):
            parts, length = [], 0
            for value in node.values:
                part = evaluate(value, depth + 1)
                if type(part) is not str:
                    raise Unsupported('nonstring_fstring_part')
                length += len(part)
                if length > MAX_TEXT:
                    raise Unsupported('formatted_text_budget')
                parts.append(part)
            result = ''.join(parts)
        elif isinstance(node, ast.FormattedValue):
            value = evaluate(node.value, depth + 1)
            if node.conversion == 115:
                value = str(value)
            elif node.conversion == 114:
                value = repr(value)
            elif node.conversion == 97:
                value = ascii(value)
            elif node.conversion != -1:
                raise Unsupported('unsupported_format_conversion')
            specification = evaluate(node.format_spec, depth + 1) if node.format_spec is not None else ''
            if specification.endswith('n'):
                raise Unsupported('locale_dependent_format')
            # Only exact built-in values reach format; widths/precisions are
            # bounded before calling the built-in to prevent huge allocation.
            for digits in re.findall(r'[0-9]+', specification):
                if len(digits) > 5 or int(digits) > MAX_TEXT:
                    raise Unsupported('format_width_budget')
            result = format(value, specification)
        else:
            raise Unsupported('unsupported_expression_node')
        return _bounded(result)

    try:
        return evaluate(tree.body), used
    except (TypeError, OverflowError, ValueError) as exc:
        if isinstance(exc, Unsupported):
            raise
        raise Unsupported('invalid_pure_expression') from None


def _positions(code):
    offsets, offset = [], 0
    for line in code.encode().splitlines(keepends=True):
        offsets.append(offset)
        offset += len(line)
    offsets.append(offset)

    def position(node):
        if not hasattr(node, 'lineno') or not hasattr(node, 'end_lineno'):
            return None
        return offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset

    return position


def _source_facts(code):
    try:
        module = ast.parse(code)
    except (SyntaxError, ValueError):
        raise Unsupported('source_parse_error') from None
    position = _positions(code)
    functions = {position(node)[0]: node for node in ast.walk(module)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return position, functions, _pytest_bindings(module)


def _function_facts(source_facts, definition):
    position, functions, _ = source_facts
    function = functions.get(definition['start_byte'])
    if function is None:
        raise Unsupported('test_definition_missing')
    by_span, parents, writes = defaultdict(list), {}, defaultdict(list)
    for node in ast.walk(function):
        location = position(node)
        if location is not None:
            by_span[location].append(node)
        for nested in ast.iter_child_nodes(node):
            parents[nested] = node
        name = None
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            name = node.id
        elif node is not function and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.ExceptHandler):
            name = node.name
        elif isinstance(node, ast.alias):
            name = node.asname or node.name.split('.')[0]
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)):
            name = node.name
        elif isinstance(node, ast.MatchMapping):
            name = node.rest
        if name and location is not None:
            writes[name].append(location[0])
    return function, by_span, parents, writes


def _pytest_bindings(module):
    """Index direct pytest imports and possible rebindings once per source.

    Import/module monkeypatching is outside this local analysis, as in the
    corpus import resolver. Merely spelling an attribute ``parametrize`` does
    not establish its binding identity.
    """
    imports, bindings = defaultdict(list), defaultdict(list)
    for statement in module.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name == 'pytest':
                    imports[alias.asname or alias.name].append(alias)
    for node in ast.walk(module):
        bound = None
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound = node.id
        elif isinstance(node, ast.arg):
            bound = node.arg
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound = node.name
        elif isinstance(node, ast.alias):
            bound = node.asname or node.name.split('.')[0]
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            bound = node.name
        elif isinstance(node, ast.MatchMapping):
            bound = node.rest
        elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            root = node.value
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(root, ast.Name):
                bound = root.id
        if bound:
            bindings[bound].append(node)
    return {name: ('known' if len(nodes) == 1 and bindings[name] == nodes else 'may_have_changed')
            for name, nodes in imports.items()}


def _pytest_decorator(decorator, imports):
    callee = decorator.func
    if not (isinstance(callee, ast.Attribute) and callee.attr == 'parametrize'
            and isinstance(callee.value, ast.Attribute) and callee.value.attr == 'mark'
            and isinstance(callee.value.value, ast.Name)):
        raise Unsupported('parameter_decorator_binding_unknown')
    identity = imports.get(callee.value.value.id, 'unknown')
    if identity != 'known':
        raise Unsupported('parameter_decorator_binding_' + identity)


def _table(function, imports):
    decorators = [node for node in function.decorator_list if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == 'parametrize']
    if len(decorators) != 1:
        raise Unsupported('complete_single_parameter_table_required')
    if len(function.decorator_list) != 1:
        raise Unsupported('additional_decorator_binding_effects_unknown')
    decorator = decorators[0]
    _pytest_decorator(decorator, imports)
    if len(decorator.args) < 2:
        raise Unsupported('parameter_table_arguments_missing')
    try:
        for keyword in decorator.keywords:
            if keyword.arg == 'indirect' and ast.literal_eval(keyword.value):
                raise Unsupported('indirect_parameter_values_unknown')
            if keyword.arg is None:
                raise Unsupported('dynamic_parameter_options')
        names = ast.literal_eval(decorator.args[0])
        names = [name.strip() for name in names.split(',')] if isinstance(names, str) else list(names)
        values = ast.literal_eval(decorator.args[1])
    except Unsupported:
        raise
    except (ValueError, TypeError, SyntaxError):
        raise Unsupported('parameter_table_not_literal') from None
    if (not names or any(type(name) is not str or not name.isidentifier() for name in names)
            or len(set(names)) != len(names) or type(values) not in {tuple, list}):
        raise Unsupported('invalid_parameter_table')
    return names, values


def _row_values(row, names, values, source):
    if row.get('table') != 0 or type(row.get('row')) is not int or not 0 <= row['row'] < len(values):
        raise Unsupported('parameter_row_position_mismatch')
    raw = values[row['row']]
    cells = [raw] if len(names) == 1 else raw
    if type(cells) not in {list, tuple} or len(cells) != len(names):
        raise Unsupported('incomplete_parameter_row')
    known = dict(zip(names, cells))
    if set(row.get('parameter_bindings', {})) != set(names) or set(row.get('binding_sources', {})) != set(names):
        raise Unsupported('incomplete_parameter_row')
    for name, value in known.items():
        _bounded(value, json_row=True)
        metadata = row['binding_sources'].get(name)
        if metadata is None or not metadata.get('literal_known'):
            raise Unsupported('parameter_cell_not_literal')
        location = metadata['span']
        text = source[location['start_byte']:location['end_byte']].decode()
        if text != metadata['text']:
            raise Unsupported('parameter_cell_source_mismatch')
        try:
            actual = ast.literal_eval(text)
        except (ValueError, TypeError, SyntaxError):
            raise Unsupported('parameter_cell_not_literal') from None
        encode = lambda item: json.dumps(item, sort_keys=True, ensure_ascii=True, allow_nan=False)
        if type(actual) is not type(value) or encode(actual) != encode(value) or encode(value) != encode(row['parameter_bindings'][name]):
            raise Unsupported('parameter_binding_value_mismatch')
    return known


def augment_corpus(corpus):
    """Return a shallow corpus copy plus additional row-specific input donors."""
    output = dict(corpus, donors=list(corpus['donors']))
    skipped, rows_by_test, expressions = Counter(), defaultdict(list), defaultdict(list)
    existing = {donor['id'] for donor in output['donors']}
    if corpus['language'] != 'python':
        return output
    for donor in corpus['donors']:
        if donor['kind'] == 'parameter_row':
            rows_by_test[donor['test_id']].append(donor)
        elif (not donor.get('literal_known') and not donor.get('finite_input')
              and (donor.get('input_slots') or donor.get('call_context'))
              and not (donor.get('oracle_dependency') and not donor.get('observation_dependency'))):
            expressions[donor['test_id']].append(donor)
    added, attempts, source_cache = 0, 0, {}
    for test_id in sorted(rows_by_test.keys() & expressions.keys()):
        test = corpus['tests'][test_id]
        metadata = corpus['sources'][test['span']['path']]
        if not metadata.get('complete_file', True) or metadata.get('parse_error'):
            skipped['incomplete_or_unparseable_source'] += 1
            continue
        try:
            path = test['span']['path']
            if path not in source_cache:
                source_cache[path] = _source_facts(metadata['code'])
            function, by_span, parents, writes = _function_facts(source_cache[path], test['definition_span'])
            names, values = _table(function, source_cache[path][2])
        except Unsupported as exc:
            skipped[str(exc)] += 1
            continue
        raw = metadata['code'].encode()
        rows = []
        for row in sorted(rows_by_test[test_id], key=lambda item: (item['table'], item['row'], item['id'])):
            try:
                rows.append((row, _row_values(row, names, values, raw)))
            except Unsupported as exc:
                skipped[str(exc)] += 1
        for donor in expressions[test_id]:
            location = donor['span']
            if raw[location['start_byte']:location['end_byte']].decode() != donor['text']:
                skipped['donor_source_mismatch'] += 1
                continue
            nodes = by_span.get((location['start_byte'], location['end_byte']), [])
            if not nodes:
                skipped['expression_scope_missing'] += 1
                continue
            node, scope = nodes[0], parents.get(nodes[0])
            loops = []
            while scope is not None and not isinstance(scope, _SCOPES):
                if isinstance(scope, _LOOPS):
                    loops.append(source_cache[path][0](scope))
                scope = parents.get(scope)
            if scope is not function:
                skipped['nested_expression_scope'] += 1
                continue
            for row, bindings in rows:
                if attempts >= MAX_EXPANSIONS:
                    skipped['expansion_budget'] += 1
                    output['finite_inputs'] = {'added': added, 'attempts': attempts, 'skipped': dict(skipped), 'budget_exhausted': True}
                    return output
                attempts += 1
                try:
                    value, used = _evaluate(donor['text'], bindings)
                    if not used:
                        raise Unsupported('expression_not_parameter_dependent')
                    if any(any(position < location['end_byte'] for position in writes[name]) for name in used):
                        raise Unsupported('parameter_binding_may_have_changed')
                    # A later textual write in an enclosing loop can precede
                    # the same expression on the next iteration.
                    if any(start <= position < end for name in used
                           for position in writes[name] for start, end in loops):
                        raise Unsupported('parameter_binding_may_change_on_loop_backedge')
                    # Downstream row materialization uses the complete row
                    # for both input bindings and the oracle pre-value. Keep
                    # that contract conservative even for parameters not
                    # referenced by this particular input expression.
                    if any(writes[name] for name in bindings):
                        raise Unsupported('parameter_row_bindings_may_change')
                    if any(not _immutable(item) for item in bindings.values()):
                        raise Unsupported('mutable_parameter_row_value')
                    # Keep the established corpus value encoding exact. Rows
                    # involving tuples/bytes/sets are rejected above instead
                    # of quietly materializing their JSON representations.
                    _bounded(value, json_row=True)
                except Unsupported as exc:
                    skipped[str(exc)] += 1
                    continue
                identifier = _id('finite_input', donor['id'], row['id'])
                if identifier in existing:
                    continue
                enriched = dict(donor, id=identifier, literal_known=True, literal_value=value,
                    parameter_row={'table': row['table'], 'row': row['row'],
                                   'name': next(iter(used)) if len(used) == 1 else None,
                                   'bindings': copy.deepcopy(bindings)},
                    finite_input={'source_donor_id': donor['id'], 'row_donor_id': row['id'],
                                  'referenced_parameters': sorted(used),
                                  'binding_sources': copy.deepcopy(row['binding_sources'])})
                output['donors'].append(enriched)
                existing.add(identifier)
                added += 1
    output['finite_inputs'] = {'added': added, 'attempts': attempts, 'skipped': dict(skipped), 'budget_exhausted': False}
    return output
