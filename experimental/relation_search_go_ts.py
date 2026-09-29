"""Deterministic source neighbours for Go/TypeScript validation programs.

This module proposes input edits, not expected results.  A generated assertion
is retained as a hypothesis and must be reviewed independently.  No repository,
issue, API, task identifier, or expected defect is built into the operators.

The receiver-routing operator learns a call shape ``owner.path.m(value, ...)``
from a donor test.  It can apply that shape to ``value.m(...)`` in another test
only when value is created by the same owner factory and the owner's creator
resolves to the same import binding.  This makes existing ordinary-path tests
available in wrapper contexts without synthesising a new fixture or oracle.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import difflib
import hashlib
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from typing import Iterable

from anchor_retrieval.syntax import (
    ATTRS, CALLS, Source, Unit, attr_parts, call_parts, child, is_test_path, literal, units, walk,
)


VERSION = "source-neighbours-v1"
OPERATORS = ("record_delete", "argument_omit", "receiver_route", "expression_rebind",
             "constructor_wrap", "constructor_field_lift", "guest_result_container", "owner_prefix_rebind",
             "guest_alias_route", "sequence_interval_extend", "structured_literal_route", "numeric_context_route")
_SCOPES = {"program", "source_file", "statement_block", "block", "statement_list"}
_PAIRS = {"pair", "keyed_element"}
_ASSERTION_METHODS = {
    "toBe", "toEqual", "toStrictEqual", "toMatchObject", "toContain",
    "toHaveLength", "toThrow", "toBeInstanceOf", "Equal", "EqualValues",
    "NotEqual", "Greater", "GreaterOrEqual", "Less", "LessOrEqual", "Contains",
    "Error", "NoError", "True", "False", "Nil", "NotNil", "Fatal", "Fatalf",
    "Errorf", "assert", "expect",
}


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:20]


def _span(source: Source, node) -> dict:
    return {"path": source.path, "start_byte": node.start_byte, "end_byte": node.end_byte,
            "start_line": node.start_point.row + 1, "end_line": node.end_point.row + 1}


def _path(source: Source, node) -> tuple[str, ...] | None:
    if node is None:
        return None
    if node.type in {"identifier", "field_identifier", "property_identifier"}:
        return (source.text(node),)
    if node.type in ATTRS:
        obj, prop = attr_parts(node)
        prefix = _path(source, obj)
        if prefix is not None and prop is not None and prop.type in {
            "identifier", "field_identifier", "property_identifier"
        }:
            return (*prefix, source.text(prop))
    return None


def _scope(node):
    parent = node.parent
    while parent is not None and parent.type not in _SCOPES:
        parent = parent.parent
    return parent


def _contains(outer, inner) -> bool:
    return outer is not None and outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def _bindings(source: Source):
    if hasattr(source, "_rs_binding_cache"):
        return source._rs_binding_cache
    result = defaultdict(list)
    for node in walk(source.root):
        if node.type == "variable_declarator":
            name, value = child(node, "name"), child(node, "value")
            if name is not None and name.type == "identifier" and value is not None:
                result[source.text(name)].append((name, value, _scope(node)))
        elif node.type in {"short_var_declaration", "var_spec"}:
            left, right = child(node, "left", "name"), child(node, "right", "value")
            if left is None or right is None:
                continue
            names = [left] if left.type == "identifier" else list(left.named_children)
            values = [right] if right.type != "expression_list" else list(right.named_children)
            if len(names) == len(values):
                for name, value in zip(names, values):
                    if name.type == "identifier":
                        result[source.text(name)].append((name, value, _scope(node)))
            elif len(values) == 1 and values[0].type in CALLS:
                for name in names:
                    if name.type == "identifier":
                        result[source.text(name)].append((name, values[0], _scope(node)))
    source._rs_binding_cache = result
    return result


def _resolve(bindings, name: str, at):
    candidates = [(n, v, scope) for n, v, scope in bindings.get(name, [])
                  if n.start_byte < at.start_byte and _contains(scope, at)]
    if not candidates:
        return None
    # The smallest enclosing lexical scope wins; latest declaration within it.
    return min(candidates, key=lambda item: (
        item[2].end_byte - item[2].start_byte, -item[0].start_byte))


def _import_signature(source: Source, path: tuple[str, ...]) -> tuple:
    imported = source.imports.get(path[0])
    if imported:
        module, name = imported
        if module.startswith("."):
            module = posixpath.normpath(posixpath.join(posixpath.dirname(source.path), module))
        return ("import", module, name, *path[1:])
    return ("unresolved_source_binding", source.path, *path)


def _creator(source: Source, bindings, owner: str, at):
    binding = _resolve(bindings, owner, at)
    if binding is None or binding[1].type not in CALLS:
        return None
    fn, _ = call_parts(binding[1])
    path = _path(source, fn)
    if path is None:
        return None
    return _import_signature(source, path)


def _carrier(source: Source, bindings, identifier: str, at):
    binding = _resolve(bindings, identifier, at)
    if binding is None or binding[1].type not in CALLS:
        return None
    fn, _ = call_parts(binding[1])
    path = _path(source, fn)
    if path is None or len(path) < 2:
        return None
    creator = _creator(source, bindings, path[0], binding[1])
    if creator is None:
        return None
    return {"owner": path[0], "factory": path[1:], "creator": creator,
            "binding_span": _span(source, binding[0]),
            "initializer": source.text(binding[1])}


def _tests(source: Source) -> list[Unit]:
    return [unit for unit in units(source)[0] if unit.test]


def _test_at(tests: list[Unit], node) -> Unit | None:
    containing = [unit for unit in tests if _contains(unit.body, node)]
    return min(containing, key=lambda unit: unit.node.end_byte - unit.node.start_byte) if containing else None


def _assertion_call(source: Source, node) -> bool:
    fn, _ = call_parts(node)
    name = _path(source, fn)
    if name and name[-1] in _ASSERTION_METHODS:
        return True
    # Chained matchers have a call expression at the receiver root.
    if fn is not None and fn.type in ATTRS:
        _, prop = attr_parts(fn)
        return source.text(prop) in _ASSERTION_METHODS
    return False


def _constant(source: Source, node):
    try:
        value = literal(source.text(node))
    except ValueError:
        return False, None
    return type(value) in {str, int, float, bool, type(None)}, value


def _record_items(source: Source, node):
    if source.language == "typescript" and node.type == "object":
        container = node
    elif source.language == "go" and node.type == "composite_literal":
        container = child(node, "body")
    else:
        return None
    if container is None:
        return None
    items = [n for n in container.named_children if n.type != "comment"]
    if any(n.type not in _PAIRS for n in items):
        return None  # computed/shorthand/spread entries need other semantics
    records = []
    for item in items:
        key, value = child(item, "key"), child(item, "value")
        # Go wraps expression keys/values in literal_element nodes.
        if key is not None and key.type == "literal_element" and len(key.named_children) == 1:
            key = key.named_children[0]
        if value is not None and value.type == "literal_element" and len(value.named_children) == 1:
            value = value.named_children[0]
        if key is None or value is None:
            return None
        key_ok, key_value = _constant(source, key)
        if not key_ok and key.type not in {"property_identifier", "identifier", "field_identifier"}:
            return None
        records.append((item, str(key_value) if key_ok else source.text(key), value))
    return container, records


def _pure_numeric(source: Source, node, bindings, at, depth=0):
    if depth > 3:
        return False
    ok, value = _constant(source, node)
    if ok:
        return type(value) in {int, float}
    if node.type == "identifier":
        # A binding can return a numeric API value; arithmetic use supplies the
        # syntactic numeric evidence. Compiler/runtime validates its real type.
        return _resolve(bindings, source.text(node), at) is not None
    if node.type in {"binary_expression", "unary_expression", "parenthesized_expression"}:
        if any(source.text(n) not in {"+", "-", "*", "/", "%", "(", ")"}
               for n in node.children if not n.is_named):
            return False
        return all(_pure_numeric(source, n, bindings, at, depth + 1)
                   for n in node.named_children)
    return False


def routing_templates(sources: Iterable[Source]) -> list[dict]:
    templates = {}
    for source in sources:
        bindings, tests = _bindings(source), _tests(source)
        for node in walk(source.root):
            if node.type not in CALLS or _test_at(tests, node) is None:
                continue
            fn, args = call_parts(node)
            path = _path(source, fn)
            if path is None or len(path) < 3 or not args or args[0].type != "identifier":
                continue
            carrier = _carrier(source, bindings, source.text(args[0]), node)
            if carrier is None or carrier["owner"] != path[0]:
                continue
            key = (carrier["creator"], carrier["factory"], path[1:-1], path[-1])
            row = {"owner_creator": list(carrier["creator"]), "carrier_factory": list(carrier["factory"]),
                   "wrapper_path": list(path[1:-1]), "method": path[-1],
                   "source": _span(source, node), "source_call": source.text(node),
                   "carrier": carrier, "source_sha256": hashlib.sha256(source.data).hexdigest()}
            templates.setdefault(key, row)
    return [templates[key] for key in sorted(templates, key=repr)]


def _local_in_expression(source: Source, identifier, expression) -> bool:
    """Recognise lexical binders inside a transported expression only."""
    name = source.text(identifier)
    parent = identifier.parent
    while parent is not None and _contains(expression, parent):
        if parent.type in {"arrow_function", "function_expression"}:
            parameters = child(parent, "parameters", "parameter")
            if parameters is not None and any(n.type == "identifier" and source.text(n) == name
                                               for n in walk(parameters)):
                return True
            # A body-local declaration is accepted only if the usual lexical
            # lookup resolves to a declaration inside this exact expression.
            binding = _resolve(_bindings(source), name, identifier)
            if binding is not None and _contains(expression, binding[0]):
                return True
        parent = parent.parent
    return False


def constructor_templates(sources: Iterable[Source]) -> list[dict]:
    """Imported call contexts whose non-hole free names are all imports.

    This includes contexts appearing only in type tests.  Transferring them
    changes an input constructor, not a type assertion into a runtime oracle.
    """
    templates = {}
    for source in sources:
        if source.language != "typescript":
            continue
        tests = _tests(source)
        for outer in walk(source.root):
            if outer.type not in CALLS or _test_at(tests, outer) is None or _assertion_call(source, outer):
                continue
            fn, args = call_parts(outer)
            fn_path = _path(source, fn)
            if fn_path is None or len(fn_path) != 1 or fn_path[0] not in source.imports:
                continue
            if len(source.text(outer)) > 4096:
                continue
            for hole_index, hole in enumerate(args):
                if hole.type not in CALLS:
                    continue
                hole_fn, _ = call_parts(hole)
                hole_path = _path(source, hole_fn)
                if hole_path is None or len(hole_path) != 1 or hole_path[0] not in source.imports:
                    continue
                free = {}
                unsupported = False
                for item in walk(outer):
                    if item.type != "identifier" or _contains(hole, item):
                        continue
                    if _local_in_expression(source, item, outer):
                        continue
                    name = source.text(item)
                    if name not in source.imports:
                        unsupported = True
                        break
                    free[name] = _import_signature(source, (name,))
                if unsupported:
                    continue
                text = source.text(outer)
                a, b = hole.start_byte - outer.start_byte, hole.end_byte - outer.start_byte
                shape = text.encode()[:a].decode() + "$HOLE" + text.encode()[b:].decode()
                row = {"source": source, "node": outer, "hole": hole,
                       "hole_key": _import_signature(source, hole_path), "free_imports": free,
                       "hole_index": hole_index, "shape": shape,
                       "type_only": source.type_only}
                key = (row["hole_key"], shape, tuple(sorted(free.items())))
                templates.setdefault(key, row)
    return [templates[key] for key in sorted(templates, key=repr)]


def _transport_constructor(template, target: Source, hole, extra_changes=()):
    donor, outer = template["source"], template["node"]
    replacement = target.text(hole)
    changes = [{"span": _span(donor, template["hole"]),
                "before": donor.text(template["hole"]), "after": replacement}]
    changes.extend(extra_changes)
    imports = []
    identifiers = {target.text(node) for node in walk(target.root) if node.type == "identifier"}
    mapping = {}
    for name, signature in template["free_imports"].items():
        existing = next((alias for alias in target.imports
                         if _import_signature(target, (alias,)) == signature
                         and _resolve(_bindings(target), alias, hole) is None), None)
        if existing is None:
            alias = name
            if alias in identifiers:
                alias = "rs_import_" + _digest(signature)[:8]
            module, imported = donor.imports[name]
            if module.startswith("."):
                absolute = posixpath.normpath(posixpath.join(posixpath.dirname(donor.path), module))
                module = posixpath.relpath(absolute, posixpath.dirname(target.path) or ".")
                if not module.startswith("."):
                    module = "./" + module
            imports.append({"name": alias, "module": module, "imported_name": imported,
                            "source_path": donor.path, "source_binding": name})
            existing = alias
        mapping[name] = existing
    for node in walk(outer):
        if (node.type == "identifier" and not _contains(template["hole"], node)
            and not _local_in_expression(donor, node, outer)
            and not any(change["span"]["start_byte"] <= node.start_byte
                        and node.end_byte <= change["span"]["end_byte"] for change in extra_changes)):
            name = donor.text(node)
            if mapping.get(name, name) != name:
                changes.append({"span": _span(donor, node), "before": name, "after": mapping[name]})
    code = _edit_bytes(donor.data[outer.start_byte:outer.end_byte], changes, offset=outer.start_byte).decode()
    return code, imports


def _lift_constructor_fields(template, target: Source, constructor):
    """Lift a unary scalar callback through a field of a record constructor.

    For a callback f and record field k, the generated callback is the ordinary
    JavaScript expression r => ({...r, [k]: f(r[k])}).  The scalar constructor in
    the source template must match the constructor used at k by import identity.
    This is a proposed input operation, not an inferred universal API law.
    """
    donor, outer = template["source"], template["node"]
    _, outer_arguments = call_parts(outer)
    # Lifting a single callback does not lift arbitrary additional validators
    # or other actions from the scalar domain into the record domain.
    if len(outer_arguments) != 2 or template["hole_index"] != 0:
        return []
    callbacks = [n for n in walk(outer) if n.type == "arrow_function"
                 and not _contains(template["hole"], n)]
    if len(callbacks) != 1:
        return []
    callback = callbacks[0]
    parameters = child(callback, "parameter", "parameters")
    body = child(callback, "body")
    if parameters is None or body is None:
        return []
    parameter_names = [n for n in walk(parameters) if n.type == "identifier"]
    if len(parameter_names) != 1 or body.type == "statement_block":
        return []
    param = donor.text(parameter_names[0])
    allowed = {"identifier", "property_identifier", "member_expression", "subscript_expression",
               "binary_expression", "unary_expression", "parenthesized_expression", "number",
               "string", "string_fragment", "true", "false", "null"}
    if any(n.type not in allowed for n in walk(body)):
        return []
    if any(n.type == "identifier" and donor.text(n) != param for n in walk(body)):
        return []
    _, args = call_parts(constructor)
    result = []
    for argument in args:
        record = _record_items(target, argument)
        if record is None:
            continue
        _, items = record
        for _, key, scalar in items:
            if scalar.type not in CALLS:
                continue
            fn, _ = call_parts(scalar)
            path = _path(target, fn)
            if path is None or _import_signature(target, path) != template["hole_key"]:
                continue
            changes = [{"span": _span(donor, n), "before": param,
                        "after": param + "[" + json.dumps(key) + "]"}
                       for n in walk(body) if n.type == "identifier"]
            scalar_body = _edit_bytes(donor.data[body.start_byte:body.end_byte], changes,
                                      offset=body.start_byte).decode()
            lifted = "({..." + param + ", " + json.dumps(key) + ": " + scalar_body + "})"
            edit = {"span": _span(donor, body), "before": donor.text(body), "after": lifted}
            code, imports = _transport_constructor(template, target, constructor, [edit])
            result.append((code, imports, key, donor.text(body), lifted))
    return result


_GUEST_TOKEN = re.compile(r'''\s+|//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_]\w*|:=|\.\.\.|[^\s]''')


def _guest_factories(text):
    """Bounded lexical fragment of Go-like guest languages with func literals.

    Only named, non-variadic factories directly returning a function literal
    are admitted. Delimiters are matched while quoted strings/comments remain
    atomic. No subject guest program is executed during extraction.
    """
    tokens = [(m.group(), m.start(), m.end()) for m in _GUEST_TOKEN.finditer(text)
              if not m.group().isspace() and not m.group().startswith(("//", "/*"))]
    stack, ends = [], {}
    for i, (token, _, _) in enumerate(tokens):
        if token in {"(", "[", "{"}:
            stack.append((token, i))
        elif token in {")", "]", "}"}:
            if not stack or {"(": ")", "[": "]", "{": "}"}[stack[-1][0]] != token:
                return []
            _, start = stack.pop()
            ends[start] = i
    if stack:
        return []
    result = []
    for i in range(2, len(tokens) - 1):
        if tokens[i][0] != "func" or tokens[i - 1][0] != ":=" or tokens[i + 1][0] != "(":
            continue
        name = tokens[i - 2][0]
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            continue
        param_end = ends.get(i + 1)
        if param_end is None or param_end + 1 >= len(tokens) or tokens[param_end + 1][0] != "{":
            continue
        body_end = ends.get(param_end + 1)
        if body_end is None:
            continue
        parameter_tokens = [t[0] for t in tokens[i + 2:param_end]]
        parameters = parameter_tokens[::2]
        if (any(not re.fullmatch(r"[A-Za-z_]\w*", n) for n in parameters)
            or any(t != "," for t in parameter_tokens[1::2])
            or len(parameter_tokens) not in {0, 2 * len(parameters) - 1}):
            continue
        # Find a direct return in the factory body, not a return nested inside
        # another closure or conditional. A returned literal may itself nest.
        cursor, returned = param_end + 2, None
        while cursor < body_end:
            if tokens[cursor][0] == "return" and cursor + 1 < body_end and tokens[cursor + 1][0] == "func":
                returned = cursor + 1
                break
            if tokens[cursor][0] in {"(", "[", "{"}:
                cursor = ends[cursor] + 1
            else:
                cursor += 1
        if returned is not None:
            inner_parameters = returned + 1
            inner_parameter_end = ends.get(inner_parameters)
            inner_body = inner_parameter_end + 1 if inner_parameter_end is not None else None
            inner_end = ends.get(inner_body) if inner_body is not None else None
            if inner_end is None:
                continue
            result.append({"name": name, "parameters": parameters,
                           "start": tokens[i - 2][1], "end": tokens[body_end][2],
                           "return_start": tokens[returned][1], "return_end": tokens[inner_end][2]})
    return result


def _go_array_views(sources):
    templates = {}
    for source in sources:
        if source.language != "go":
            continue
        bindings = _bindings(source)
        for node in walk(source.root):
            if node.type != "index_expression":
                continue
            operand, index = child(node, "operand"), child(node, "index")
            index_known, index_value = _constant(source, index) if index is not None else (False, None)
            if (operand is None or operand.type != "selector_expression" or not index_known
                or type(index_value) not in {int, str}):
                continue
            root, field = attr_parts(operand)
            if root is None:
                continue
            assertion = root
            if root.type == "identifier":
                binding = _resolve(bindings, source.text(root), root)
                assertion = binding[1] if binding else root
            if assertion.type != "type_assertion_expression":
                continue
            assertion_operand = child(assertion, "operand")
            if assertion_operand is None:
                continue
            type_suffix = source.data[assertion_operand.end_byte:assertion.end_byte].decode()
            base_suffix = type_suffix + "." + source.text(field)
            suffix = base_suffix + "[" + json.dumps(index_value) + "]"
            # Only imported qualified pointer types, not private donor types.
            names = re.findall(r"\b([A-Za-z_]\w*)\.", type_suffix)
            required = {name: source.imports[name] for name in names if name in source.imports}
            if not required or any(name not in source.imports for name in names):
                continue
            row = {"suffix": suffix, "base_suffix": base_suffix, "index": index_value,
                   "container_kind": "sequence" if type(index_value) is int else "mapping",
                   "imports": required, "source": _span(source, node),
                   "source_text": source.text(node)}
            templates.setdefault((suffix, tuple(sorted(required.items()))), row)
    return list(templates.values())


def _go_results(source, declaration):
    if declaration.type != "short_var_declaration":
        return [], None
    left, right = child(declaration, "left"), child(declaration, "right")
    if left is None or right is None:
        return [], None
    names = list(left.named_children)
    values = list(right.named_children)
    return names, values[0] if len(values) == 1 and values[0].type in CALLS else None


def _guest_container_neighbors(source: Source, donors):
    if source.language != "go":
        return []
    views = _go_array_views([source, *donors])
    bindings, result = _bindings(source), []
    source_hash = hashlib.sha256(source.data).hexdigest()
    for unit in _tests(source):
        declarations = [n for n in walk(unit.body) if n.type == "short_var_declaration"]
        for literal_node in walk(unit.body):
            if literal_node.type != "raw_string_literal":
                continue
            program = source.text(literal_node)[1:-1]
            for factory in _guest_factories(program):
                factory_name = factory["name"]
                # Host lookups are discovered by their literal guest symbol,
                # rather than by a hard-coded Get/Call/NewScript API name.
                for lookup_declaration in declarations:
                    names, rhs = _go_results(source, lookup_declaration)
                    if rhs is None or not names:
                        continue
                    symbol_nodes = [n for n in walk(rhs) if n.type == "interpreted_string_literal"
                                    and _constant(source, n) == (True, factory_name)]
                    if len(symbol_nodes) != 1:
                        continue
                    fn, _ = call_parts(rhs)
                    products = []
                    if len(names) >= 2 and fn is not None and fn.type == "selector_expression":
                        products.append((lookup_declaration, names[0]))
                    else:
                        bound_name = source.text(names[0])
                        for invocation in declarations:
                            out_names, out_rhs = _go_results(source, invocation)
                            if out_rhs is None or len(out_names) < 2 or invocation.start_byte <= lookup_declaration.end_byte:
                                continue
                            out_fn, _ = call_parts(out_rhs)
                            path = _path(source, out_fn)
                            if path is not None and len(path) == 2 and path[0] == bound_name:
                                products.append((invocation, out_names[0]))
                    for product_declaration, value_node in products:
                        value_name = source.text(value_node)
                        if value_name == "_":
                            continue
                        declaration_scope = _scope(product_declaration)
                        uses = []
                        for node in walk(unit.body):
                            if node.type != "identifier" or source.text(node) != value_name or node.start_byte <= product_declaration.end_byte:
                                continue
                            binding = _resolve(bindings, value_name, node)
                            if binding is None or binding[0].start_byte != value_node.start_byte:
                                continue
                            parent = node.parent
                            if parent is not None and parent.type == "expression_list" and parent.parent is not None:
                                assignment = parent.parent
                                if assignment.type in {"assignment_statement", "short_var_declaration"} and child(assignment, "left") == parent:
                                    break
                            uses.append(node)
                        if not uses:
                            continue
                        view_contexts = []
                        for view in views:
                            if view["container_kind"] == "sequence":
                                view_contexts.extend((view, index, "[" + "0, " * index, "]") for index in range(2))
                            else:
                                view_contexts.append((view, view["index"], "{" + json.dumps(view["index"]) + ": ", "}"))
                        for view, index, context_before, context_after in view_contexts:
                            suffix = view["base_suffix"] + "[" + json.dumps(index) + "]"
                            supported = True
                            for alias, imported in view["imports"].items():
                                matched = next((name for name, item in source.imports.items() if item == imported), None)
                                if matched is None:
                                    supported = False
                                    break
                                suffix = re.sub(r"\b" + re.escape(alias) + r"\.", matched + ".", suffix)
                            if not supported:
                                continue
                            fresh = "rs_box_" + _digest([factory_name, literal_node.start_byte])[:8]
                            if re.search(r"\b" + fresh + r"\b", program):
                                continue
                            # Clone the source factory body rather than adding
                            # a delegating call: a new intermediate guest frame
                            # can hide bugs in the original producer boundary.
                            start, end = factory["start"], factory["end"]
                            a, b = factory["return_start"], factory["return_end"]
                            definition = (fresh + program[start + len(factory_name):a]
                                          + context_before + program[a:b] + context_after + program[b:end])
                            declaration = "\n" + definition + "\n"
                            edits = [{"span": _span(source, literal_node), "before": source.text(literal_node),
                                      "after": "`" + program + declaration + "`", "role": "input"},
                                     {"span": _span(source, symbol_nodes[0]), "before": source.text(symbol_nodes[0]),
                                      "after": json.dumps(fresh), "role": "binding"}]
                            edits.extend({"span": _span(source, n), "before": value_name,
                                          "after": "(" + value_name + ")" + suffix, "role": "projection"} for n in uses)
                            identifier = _digest([VERSION, source_hash, "guest_result_container", edits])
                            result.append({"id": identifier, "operator": "guest_result_container", "language": "go",
                                           "path": source.path, "source_sha256": source_hash,
                                           "test_name": unit.name, "test_span": _span(source, unit.node), "edits": edits,
                                           "imports": [], "relation_target": {"kind": "guest_result_container",
                                               "producer_symbol": factory_name, "container_depth": 1,
                                               "container_kind": view["container_kind"], "member": index},
                                           "evidence": {"factory": factory, "host_view": view,
                                               "producer_call": source.text(product_declaration),
                                               "rule": "wrap_factory_result_and_project_host_uses"},
                                           "oracle_status": "retained_source_assertions_require_contract_review",
                                           "priority": (0, 0, literal_node.start_byte, len(edits)),
                                           "generated_test_name": "rs_" + identifier})
    return result


def _go_getter_projection(source, invocation):
    """Inline a same-file getter's final type assertion, preserving its API.

    The admitted helper has one returned expression and straight-line local
    bindings. Its status assertions are not copied: the emitted projection is
    a Go checked type assertion and remains a runtime validity obligation.
    """
    function, args = call_parts(invocation)
    if function is None or function.type != "identifier":
        return None
    helper = next((unit for unit in units(source)[0]
                   if not unit.test and unit.name == source.text(function)), None)
    if helper is None or len(helper.params) != len(args):
        return None
    if any(node.type in {"if_statement", "for_statement", "expression_switch_statement", "type_switch_statement",
                         "select_statement", "defer_statement", "go_statement"} for node in walk(helper.body)):
        return None
    returns = [node for node in walk(helper.body) if node.type == "return_statement"]
    if len(returns) != 1:
        return None
    values = list(returns[0].named_children)
    if len(values) == 1 and values[0].type == "expression_list":
        values = list(values[0].named_children)
    if len(values) != 1:
        return None
    substitutions = dict(zip(helper.params, (source.text(arg) if arg.type in {
        "identifier", "interpreted_string_literal", "raw_string_literal", "int_literal", "float_literal"
    } else "(" + source.text(arg) + ")" for arg in args)))
    local = {}
    for statement in _statements(helper):
        if statement.type != "short_var_declaration":
            continue
        left, right = child(statement, "left"), child(statement, "right")
        if left is None or right is None or len(right.named_children) != 1:
            continue
        names = list(left.named_children)
        if names:
            local[source.text(names[0])] = right.named_children[0]
    returned = values[0]
    if returned.type == "identifier":
        returned = local.get(source.text(returned), returned)
    if returned.type != "type_assertion_expression":
        return None
    operand = child(returned, "operand")
    if operand is None:
        return None

    def inline(node, seen=()):
        replacements = []
        for part in walk(node):
            if part.type != "identifier":
                continue
            name = source.text(part)
            if name in substitutions:
                after = substitutions[name]
            elif name in local and name not in seen:
                after = inline(local[name], (*seen, name))
            else:
                continue
            replacements.append({"span": _span(source, part), "before": name, "after": after})
        return _edit_bytes(source.data[node.start_byte:node.end_byte], replacements,
                           offset=node.start_byte).decode()

    return {"operand": inline(operand), "suffix": source.data[operand.end_byte:returned.end_byte].decode(),
            "helper": _span(source, helper.node)}


def _guest_alias_neighbors(source: Source, donors):
    """Duplicate a guest closure's identity across a transported container.

    Source facts determine the producer, transfer call, typed host getter,
    container projection and later call. The operator changes the object graph
    and call receiver; it does not invent an expected result. In particular,
    rerouted stateful observations need a fresh contract review.
    """
    if source.language != "go":
        return []
    views = [view for view in _go_array_views([source, *donors]) if view["container_kind"] == "sequence"]
    result, source_hash = [], hashlib.sha256(source.data).hexdigest()
    for unit in _tests(source):
        declarations = [node for node in walk(unit.body) if node.type == "short_var_declaration"]
        for literal_node in walk(unit.body):
            if literal_node.type != "raw_string_literal":
                continue
            program = source.text(literal_node)[1:-1]
            factories = _guest_factories(program)
            if not factories:
                continue
            owner_statement = _statement_at(unit, literal_node)
            owner_names, owner_rhs = _go_results(source, owner_statement) if owner_statement is not None else ([], None)
            if not owner_names or owner_rhs is None:
                continue
            source_owner = source.text(owner_names[0])
            for factory in factories:
                pattern = r"\b([A-Za-z_]\w*)\s*:=\s*" + re.escape(factory["name"]) + r"\s*\("
                for match in re.finditer(pattern, program):
                    if any(f["start"] <= match.start() < f["end"] for f in factories):
                        continue
                    symbol = match.group(1)
                    for transfer in walk(unit.body):
                        if transfer.type not in CALLS or _assertion_call(source, transfer):
                            continue
                        transfer_fn, transfer_args = call_parts(transfer)
                        transfer_path = _path(source, transfer_fn)
                        if transfer_path is None or len(transfer_path) != 2 or len(transfer_args) != 2:
                            continue
                        destination = transfer_path[0]
                        slot_known, slot = _constant(source, transfer_args[0])
                        payload = transfer_args[1]
                        payload_symbols = [node for node in walk(payload)
                                           if node.type == "interpreted_string_literal" and _constant(source, node) == (True, symbol)]
                        if (not slot_known or not isinstance(slot, str) or len(payload_symbols) != 1
                            or not any(node.type == "identifier" and source.text(node) == source_owner for node in walk(payload))):
                            continue
                        getters = []
                        for declaration in declarations:
                            names, rhs = _go_results(source, declaration)
                            if not names or rhs is None:
                                continue
                            _, args = call_parts(rhs)
                            if not any(_constant(source, arg) == (True, slot) for arg in args):
                                continue
                            if not any(arg.type == "identifier" and source.text(arg) == destination for arg in args):
                                continue
                            projection = _go_getter_projection(source, rhs)
                            if projection:
                                getters.append((declaration, names[0], rhs, projection))
                        source_names = set()
                        for declaration in declarations:
                            names, rhs = _go_results(source, declaration)
                            if not names or rhs is None:
                                continue
                            _, args = call_parts(rhs)
                            if (any(_constant(source, arg) == (True, symbol) for arg in args)
                                and any(arg.type == "identifier" and source.text(arg) == source_owner for arg in args)):
                                source_names.add(source.text(names[0]))
                        for declaration, destination_name, getter, projection in getters:
                            if declaration.start_byte <= transfer.end_byte:
                                continue
                            routes = []
                            for later in walk(unit.body):
                                if later.type not in CALLS or later.start_byte <= declaration.end_byte:
                                    continue
                                later_fn, _ = call_parts(later)
                                later_path = _path(source, later_fn)
                                if later_path is not None and len(later_path) == 2 and later_path[0] in source_names:
                                    receiver, _ = attr_parts(later_fn)
                                    routes.append(receiver)
                            for view in views:
                                suffix = view["base_suffix"]
                                supported = True
                                for alias, imported in view["imports"].items():
                                    matched = next((name for name, value in source.imports.items() if value == imported), None)
                                    if matched is None:
                                        supported = False
                                        break
                                    suffix = re.sub(r"\b" + re.escape(alias) + r"\.", matched + ".", suffix)
                                if not supported:
                                    continue
                                fresh = "rs_pair_" + _digest([symbol, literal_node.start_byte])[:8]
                                if re.search(r"\b" + fresh + r"\b", program):
                                    continue
                                for route in routes:
                                    edits = [{"span": _span(source, literal_node), "before": source.text(literal_node),
                                              "after": "`" + program + "\n" + fresh + " := [" + symbol + ", " + symbol + "]\n`", "role": "input"},
                                             {"span": _span(source, payload_symbols[0]), "before": source.text(payload_symbols[0]),
                                              "after": json.dumps(fresh), "role": "binding"},
                                             {"span": _span(source, getter), "before": source.text(getter),
                                              "after": projection["operand"] + suffix + "[0]" + projection["suffix"], "role": "projection"},
                                             {"span": _span(source, route), "before": source.text(route),
                                              "after": projection["operand"] + suffix + "[1]" + projection["suffix"], "role": "receiver"}]
                                    identifier = _digest([VERSION, source_hash, "guest_alias_route", edits])
                                    result.append({"id": identifier, "operator": "guest_alias_route", "language": "go",
                                                   "path": source.path, "source_sha256": source_hash, "test_name": unit.name,
                                                   "test_span": _span(source, unit.node), "edits": edits, "imports": [],
                                                   "relation_target": {"kind": "shared_identity_through_transport", "members": 2},
                                                   "evidence": {"factory": factory, "guest_symbol": symbol,
                                                                "transfer": _span(source, transfer), "host_view": view,
                                                                "getter": projection["helper"], "rerouted_call": _span(source, route),
                                                                "rule": "duplicate_reference_container_then_route_later_source_call_to_second_destination_member"},
                                                   "oracle_status": "retained_source_assertions_require_contract_review",
                                                   "priority": (0, 0, literal_node.start_byte, route.start_byte),
                                                   "generated_test_name": "rs_" + identifier})
    return result


def _sequence_interval_neighbors(source):
    """Extend source-derived replacement intervals in repeated keyed inputs.

    A common keyed sequence supplies the coordinate system; two later values
    must each differ by one replacement. Each endpoint can extend by one source
    token. Joint endpoint-order profiles deduplicate the finite neighbourhood.
    The profile is an input model: the program's own diff/parse representation
    must still be measured at runtime before a reached relation is claimed.
    """
    result, source_hash = [], hashlib.sha256(source.data).hexdigest()
    for unit in _tests(source):
        keyed = defaultdict(list)
        for node in walk(unit.body):
            record = _record_items(source, node)
            if record is None:
                continue
            parent = node.parent
            observed = False
            while parent is not None and _contains(unit.body, parent):
                if parent.type in CALLS and _assertion_call(source, parent):
                    observed = True
                    break
                parent = parent.parent
            if observed:
                continue
            for _, key, value in record[1]:
                known, content = _constant(source, value)
                if known and isinstance(content, str) and 2 <= len(content.splitlines()) <= 32:
                    keyed[key].append((value, content.splitlines(keepends=True)))
        for key, members in keyed.items():
            # Bounded within one test and one key, never arbitrary corpus-wide
            # string Cartesian products. Earliest input supplies the ancestor.
            if not 3 <= len(members) <= 8:
                continue
            base_node, base = members[0]
            changed = []
            for node, lines in members[1:]:
                operations = [op for op in difflib.SequenceMatcher(a=base, b=lines, autojunk=False).get_opcodes()
                              if op[0] != "equal"]
                if len(operations) == 1 and operations[0][0] == "replace":
                    _, start, end, out_start, out_end = operations[0]
                    changed.append((node, start, end, lines[out_start:out_end]))
            for left_index, left in enumerate(changed):
                for right in changed[left_index + 1:]:
                    seen = set()
                    def ranges(item):
                        _, start, end, _ = item
                        return [(a, b) for a, b in ((start, end), (start - 1, end), (start, end + 1))
                                if 0 <= a < b <= len(base)]
                    for a, b in ranges(left):
                        for c, d in ranges(right):
                            if (a, b, c, d) == (left[1], left[2], right[1], right[2]):
                                continue
                            profile = tuple((x > y) - (x < y) for x, y in ((a, c), (a, d), (b, c), (b, d)))
                            if profile in seen:
                                continue
                            seen.add(profile)
                            edits = []
                            for item, start, end in ((left, a, b), (right, c, d)):
                                node, old_start, old_end, replacement = item
                                if (start, end) == (old_start, old_end):
                                    continue
                                text = "".join(base[:start] + replacement + base[end:])
                                edits.append({"span": _span(source, node), "before": source.text(node),
                                              "after": json.dumps(text, ensure_ascii=False), "role": "input"})
                            identifier = _digest([VERSION, source_hash, "sequence_interval_extend", edits])
                            result.append({"id": identifier, "operator": "sequence_interval_extend", "language": source.language,
                                           "path": source.path, "source_sha256": source_hash, "test_name": unit.name,
                                           "test_span": _span(source, unit.node), "edits": edits, "imports": [],
                                           "relation_target": {"kind": "sequence_edit_order", "key": key,
                                                               "intervals": [[a, b], [c, d]], "profile": list(profile)},
                                           "evidence": {"base": _span(source, base_node),
                                                        "source_intervals": [[left[1], left[2]], [right[1], right[2]]],
                                                        "source_values": [_span(source, left[0]), _span(source, right[0])],
                                                        "rule": "extend_existing_replacement_endpoint_by_one_source_token",
                                                        "runtime_relation_confirmed": False},
                                           "oracle_status": "retained_source_assertions_require_contract_review",
                                           "priority": (0, len(edits), base_node.start_byte, left[0].start_byte),
                                           "generated_test_name": "rs_" + identifier})
    return result


def _structured_literal(text):
    """Closed JSON/XML literals as path-indexed values, never subject code."""
    values = {}
    try:
        if text.lstrip().startswith("<"):
            root = ET.fromstring(text)
            def xml(node, path):
                values[path + ("#present",)] = node.tag
                values[path + ("#text",)] = node.text or ""
                for key, value in node.attrib.items():
                    values[path + ("@" + key,)] = value
                counts = defaultdict(int)
                for sub in node:
                    index = counts[sub.tag]
                    counts[sub.tag] += 1
                    xml(sub, path + ((sub.tag, index),))
            xml(root, ((root.tag, 0),))
            signature = ("xml", root.tag)
        elif text.lstrip().startswith(("{", "[")):
            root = json.loads(text)
            def record(value, path):
                if isinstance(value, dict):
                    values[path + ("#present",)] = "record"
                    for key, sub in sorted(value.items()):
                        record(sub, path + (key,))
                elif isinstance(value, list):
                    values[path + ("#present",)] = "sequence"
                    for index, sub in enumerate(value):
                        record(sub, path + (index,))
                else:
                    values[path + ("#value",)] = value
            record(root, ())
            signature = ("json", type(root).__name__)
        else:
            return None
    except (ET.ParseError, json.JSONDecodeError, RecursionError, ValueError):
        return None
    return (signature, values) if len(values) <= 96 else None


def _structured_literal_neighbors(source):
    """Route existing structured input through another peer input position.

    Exactly three calls to the same constructor/argument position give a local
    common-input context. Existing source literals with the same grammar/root
    are candidates. Changed-path kinds and their prefix relations to the other
    peer bound the search; no repository-specific element/key names are used.
    This is syntactic input feedback, not proof that two changes commute.
    """
    literals, groups = defaultdict(list), []
    for unit in _tests(source):
        by_constructor = defaultdict(list)
        for call in walk(unit.body):
            if call.type not in CALLS or _assertion_call(source, call):
                continue
            fn, args = call_parts(call)
            path = _path(source, fn)
            if path is None:
                continue
            for index, argument in enumerate(args):
                known, text = _constant(source, argument)
                parsed = _structured_literal(text) if known and isinstance(text, str) else None
                if parsed is None:
                    continue
                signature, values = parsed
                key = (_import_signature(source, path), index, signature)
                row = {"node": argument, "text": text, "values": values, "unit": unit}
                by_constructor[key].append(row)
                literals[key].append(row)
        groups.extend((unit, key, rows) for key, rows in by_constructor.items() if len(rows) == 3)
    result, source_hash = [], hashlib.sha256(source.data).hexdigest()
    def delta(base, values):
        return {path: ("add" if path not in base else "delete" if path not in values else "change", str(path[-1]))
                for path in base.keys() | values.keys()
                if path not in base or path not in values or base[path] != values[path]}
    for unit, key, rows in groups:
        base = rows[0]["values"]
        for target_index, peer_index in ((1, 2), (2, 1)):
            target, peer = rows[target_index], rows[peer_index]
            peer_changes = delta(base, peer["values"])
            if not peer_changes or len(peer_changes) > 8:
                continue
            seen = set()
            for donor in literals[key]:
                if donor["text"] in {row["text"] for row in rows}:
                    continue
                changes = delta(base, donor["values"])
                if not changes or len(changes) > 8:
                    continue
                relationships = set()
                for a in changes:
                    for b in peer_changes:
                        left, right = a[:-1], b[:-1]
                        relationships.add("equal" if left == right else "ancestor" if right[:len(left)] == left
                                          else "descendant" if left[:len(right)] == right else "disjoint")
                profile = (tuple(sorted(set(changes.values()))), tuple(sorted(relationships)))
                if profile in seen:
                    continue
                seen.add(profile)
                edit = {"span": _span(source, target["node"]), "before": source.text(target["node"]),
                        "after": source.text(donor["node"]), "role": "input"}
                identifier = _digest([VERSION, source_hash, "structured_literal_route", edit])
                result.append({"id": identifier, "operator": "structured_literal_route", "language": source.language,
                               "path": source.path, "source_sha256": source_hash, "test_name": unit.name,
                               "test_span": _span(source, unit.node), "edits": [edit], "imports": [],
                               "relation_target": {"kind": "structured_input_footprint", "grammar": key[2][0],
                                                   "path_relations": sorted(relationships), "change_kinds": list(profile[0])},
                               "evidence": {"base": _span(source, rows[0]["node"]), "peer": _span(source, peer["node"]),
                                            "donor": _span(source, donor["node"]), "donor_test": donor["unit"].name,
                                            "changed_paths": [repr(path) for path in sorted(changes, key=repr)],
                                            "peer_paths": [repr(path) for path in sorted(peer_changes, key=repr)],
                                            "rule": "same_constructor_literal_route_deduplicated_by_changed_path_profile"},
                               "oracle_status": "retained_source_assertions_require_contract_review",
                               "priority": (1, len(changes), target["node"].start_byte, donor["node"].start_byte),
                               "generated_test_name": "rs_" + identifier})
    return result


def _numeric_context_neighbors(source):
    """Transport tested numeric choices across method/option-type contexts.

    Numeric arguments are aligned from the final typed option argument, so an
    existing receiver method and its explicit-input wrapper can share choices.
    This establishes a syntactic family only; oracle equivalence is not assumed.
    """
    if source.language != "go":
        return []
    groups = defaultdict(list)
    for unit in _tests(source):
        for call in walk(unit.body):
            if call.type not in CALLS or _assertion_call(source, call):
                continue
            fn, args = call_parts(call)
            path = _path(source, fn)
            if path is None or not args or args[-1].type != "composite_literal":
                continue
            type_node = child(args[-1], "type")
            if type_node is None:
                continue
            option_type = source.text(type_node)
            for index, argument in enumerate(args[:-1]):
                known, value = _constant(source, argument)
                if not known or type(value) not in {int, float}:
                    continue
                key = (path[-1], option_type, len(args) - 1 - index)
                groups[key].append((unit, call, argument, value))
    result, source_hash = [], hashlib.sha256(source.data).hexdigest()
    for key, rows in groups.items():
        for unit, call, argument, original in rows:
            seen = set()
            for donor_unit, donor_call, donor, value in rows:
                if donor_unit is unit or value == original or value in seen:
                    continue
                seen.add(value)
                edit = {"span": _span(source, argument), "before": source.text(argument),
                        "after": source.text(donor), "role": "input"}
                identifier = _digest([VERSION, source_hash, "numeric_context_route", edit])
                result.append({"id": identifier, "operator": "numeric_context_route", "language": "go",
                               "path": source.path, "source_sha256": source_hash, "test_name": unit.name,
                               "test_span": _span(source, unit.node), "edits": [edit], "imports": [],
                               "relation_target": {"kind": "numeric_choice_across_option_context", "from": original, "to": value},
                               "evidence": {"method": key[0], "option_type": key[1], "offset_from_options": key[2],
                                            "source_call": _span(source, donor_call), "source_test": donor_unit.name,
                                            "target_call": _span(source, call),
                                            "rule": "align_numeric_slot_by_method_and_trailing_option_type"},
                               "oracle_status": "retained_source_assertions_require_contract_review",
                               "priority": (1, 0, argument.start_byte, abs(original - value)),
                               "generated_test_name": "rs_" + identifier})
    return result


def _statements(unit):
    body = unit.body
    listing = next((n for n in body.named_children if n.type == "statement_list"), body)
    return [n for n in listing.named_children if n.type != "comment"]


def _statement_at(unit, node):
    return next((statement for statement in _statements(unit) if _contains(statement, node)), None)


def _closed_numeric(source, node):
    allowed = {"int_literal", "float_literal", "number", "binary_expression",
               "unary_expression", "parenthesized_expression"}
    return all(n.type in allowed for n in walk(node))


def _observed_numeric_bindings(source, unit):
    names = set()
    comparison_names = {"Greater", "GreaterOrEqual", "Less", "LessOrEqual"}
    for node in walk(unit.body):
        if node.type in CALLS:
            fn, args = call_parts(node)
            path = _path(source, fn)
            if path is not None and path[-1] in comparison_names:
                for argument in args[1:]:
                    if argument.type == "identifier":
                        names.add(source.text(argument))
        elif node.type == "binary_expression":
            op = child(node, "operator")
            if source.text(op) in {"<", "<=", ">", ">=", "==", "!="}:
                left, right = child(node, "left"), child(node, "right")
                for operand, other in ((left, right), (right, left)):
                    if operand is not None and operand.type == "identifier" and other is not None and _closed_numeric(source, other):
                        names.add(source.text(operand))
    return names


def _owner_prefix_neighbors(source: Source):
    """Bind a consumer input to an observed result on the same fixture owner.

    The complete source prefix after owner construction is retained, including
    state operations; def-use alone must not discard calls such as writes or
    commits that establish the returned value.  This version stays within one
    Go file, so helper/import identity is exact rather than guessed by spelling.
    """
    if source.language != "go":
        return []
    tests, bindings = _tests(source), _bindings(source)
    producers, result = [], []
    for unit in tests:
        numeric = _observed_numeric_bindings(source, unit)
        statements = _statements(unit)
        for index, statement in enumerate(statements):
            names, rhs = _go_results(source, statement)
            if rhs is None or not names or source.text(names[0]) not in numeric:
                continue
            fn, _ = call_parts(rhs)
            path = _path(source, fn)
            if path is None or len(path) != 2:
                continue
            owner = _resolve(bindings, path[0], rhs)
            if owner is None:
                continue
            owner_statement = _statement_at(unit, owner[0])
            if owner_statement is None or owner_statement.end_byte >= statement.start_byte:
                continue
            end = statement.end_byte
            # Include the original immediate status check for tuple-returning
            # calls, preserving error handling and avoiding an unread error.
            if index + 1 < len(statements):
                following = statements[index + 1]
                calls = [n for n in walk(following) if n.type in CALLS]
                if calls and _assertion_call(source, calls[0]):
                    end = following.end_byte
            producers.append({"unit": unit, "owner": path[0], "owner_creator": _creator(source, bindings, path[0], rhs),
                              "start": owner_statement.end_byte, "end": end, "result": source.text(names[0]),
                              "result_span": _span(source, names[0]), "call": source.text(rhs)})
        # Arithmetic terms already present in an observation are independent
        # producer-derived inputs too. Follow receiver bindings to the fixture
        # root and copy through the last value definition, not through the
        # assertion itself: that assertion may describe a different observer.
        for assertion in walk(unit.body):
            if assertion.type not in CALLS or not _assertion_call(source, assertion):
                continue
            _, arguments = call_parts(assertion)
            for expression in arguments:
                if expression.type != "binary_expression":
                    continue
                allowed = {"identifier", "int_literal", "float_literal", "binary_expression", "unary_expression", "parenthesized_expression"}
                if any(node.type not in allowed for node in walk(expression)):
                    continue
                identifiers = [node for node in walk(expression) if node.type == "identifier"]
                if not identifiers:
                    continue
                roots, definitions = [], []
                for identifier in identifiers:
                    binding = _resolve(bindings, source.text(identifier), identifier)
                    if binding is None or binding[1].type not in CALLS:
                        break
                    definitions.append(binding[0])
                    at, fn = binding[1], call_parts(binding[1])[0]
                    path = _path(source, fn)
                    visited = set()
                    while path is not None and len(path) == 2 and path[0] not in visited:
                        name = path[0]
                        visited.add(name)
                        owner = _resolve(bindings, name, at)
                        if owner is None or owner[1].type not in CALLS:
                            break
                        next_path = _path(source, call_parts(owner[1])[0])
                        if (next_path is None or len(next_path) != 2
                            or _resolve(bindings, next_path[0], owner[1]) is None):
                            roots.append((name, owner, _creator(source, bindings, name, at)))
                            break
                        at, path = owner[1], next_path
                if len(roots) != len(identifiers) or len({root[0] for root in roots}) != 1:
                    continue
                owner_name, owner, creator = roots[0]
                owner_statement = _statement_at(unit, owner[0])
                latest = max(definitions, key=lambda node: node.start_byte)
                definition_statement = _statement_at(unit, latest)
                if owner_statement is None or definition_statement is None:
                    continue
                end = definition_statement.end_byte
                index = statements.index(definition_statement)
                if index + 1 < len(statements):
                    following = statements[index + 1]
                    calls = [node for node in walk(following) if node.type in CALLS]
                    if calls and _assertion_call(source, calls[0]):
                        end = following.end_byte
                producers.append({"unit": unit, "owner": owner_name, "owner_creator": creator,
                                  "start": owner_statement.end_byte, "end": end,
                                  "result": source.text(expression), "result_node": expression,
                                  "result_span": _span(source, expression), "call": source.text(expression)})
    source_hash = hashlib.sha256(source.data).hexdigest()
    for unit in tests:
        for node in walk(unit.body):
            if node.type not in CALLS or _assertion_call(source, node):
                continue
            fn, args = call_parts(node)
            path = _path(source, fn)
            if path is None or len(path) != 2:
                continue
            owner_creator = _creator(source, bindings, path[0], node)
            statement = _statement_at(unit, node)
            if owner_creator is None or statement is None:
                continue
            for argument_index, argument in enumerate(args):
                if not _closed_numeric(source, argument):
                    continue
                for producer in producers:
                    if producer["unit"] is unit or producer["owner_creator"] != owner_creator:
                        continue
                    start, end = producer["start"], producer["end"]
                    mapping = {producer["owner"]: path[0]}
                    donor_unit = producer["unit"]
                    if donor_unit.param_types != unit.param_types:
                        if len(donor_unit.params) != len(unit.params):
                            continue
                        if list(donor_unit.param_types.values()) != list(unit.param_types.values()):
                            continue
                    mapping.update(zip(donor_unit.params, unit.params))
                    token = _digest([source_hash, start, end, statement.start_byte, argument_index])[:8]
                    for name, definitions in bindings.items():
                        if any(start <= n.start_byte < end for n, _, _ in definitions):
                            mapping[name] = "rs_" + token + "_" + name
                    substitutions = []
                    for item in walk(donor_unit.body):
                        if item.type != "identifier" or not start <= item.start_byte < item.end_byte <= end:
                            continue
                        name = source.text(item)
                        if name in mapping and mapping[name] != name:
                            substitutions.append({"span": _span(source, item), "before": name, "after": mapping[name]})
                    prefix = _edit_bytes(source.data[start:end], substitutions, offset=start).decode()
                    if "result_node" in producer:
                        node = producer["result_node"]
                        result_edits = [{"span": _span(source, part), "before": source.text(part),
                                         "after": mapping[source.text(part)]}
                                        for part in walk(node) if part.type == "identifier" and source.text(part) in mapping]
                        produced = _edit_bytes(source.data[node.start_byte:node.end_byte], result_edits,
                                               offset=node.start_byte).decode()
                    else:
                        produced = mapping[producer["result"]]
                    insertion = {"path": source.path, "start_byte": statement.start_byte,
                                 "end_byte": statement.start_byte, "start_line": statement.start_point.row + 1,
                                 "end_line": statement.start_point.row + 1}
                    edits = [{"span": insertion, "before": "", "after": prefix + "\n", "role": "state_prefix"},
                             {"span": _span(source, argument), "before": source.text(argument),
                              "after": produced, "role": "binding"}]
                    identifier = _digest([VERSION, source_hash, "owner_prefix_rebind", edits])
                    result.append({"id": identifier, "operator": "owner_prefix_rebind", "language": "go",
                                   "path": source.path, "source_sha256": source_hash, "test_name": unit.name,
                                   "test_span": _span(source, unit.node), "edits": edits, "imports": [],
                                   "relation_target": {"kind": "same_owner_produced_value", "argument": argument_index,
                                                       "producer_call": producer["call"]},
                                   "evidence": {"source_test": donor_unit.name, "source_test_span": _span(source, donor_unit.node),
                                                "prefix_span": {"path": source.path, "start_byte": start, "end_byte": end},
                                                "producer_result": producer["result_span"], "renaming": mapping,
                                                "owner_creator": list(owner_creator)},
                                   "oracle_status": "retained_source_assertions_require_contract_review",
                                   "priority": (1, 0, node.start_byte, end - start),
                                   "generated_test_name": "rs_" + identifier})
    return result


def analyze_source(path: str, code: str, language: str) -> dict:
    source = Source(path, code, language)
    tests = _tests(source)
    return {"version": VERSION, "path": path, "language": language,
            "source_sha256": hashlib.sha256(source.data).hexdigest(), "parse_error": source.root.has_error,
            "tests": [{"name": unit.name, "definition_span": _span(source, unit.node),
                       "body_span": _span(source, unit.body)} for unit in tests],
            "routing_templates": routing_templates([source])}


def propose_neighbors(source: Source, donors: Iterable[Source] = (), *, budget=128,
                      operators: Iterable[str] = OPERATORS,
                      _routing=None, _contexts=None) -> list[dict]:
    """Return bounded edits with original anchors; never infer expected values."""
    enabled = set(operators)
    unknown = enabled - set(OPERATORS)
    if unknown:
        raise ValueError("Unknown operators: " + repr(sorted(unknown)))
    if source.language not in {"go", "typescript"}:
        raise ValueError("Only Go and TypeScript are supported")
    if source.root.has_error:
        return []
    tests, bindings = _tests(source), _bindings(source)
    all_sources = [source, *donors]
    templates = (routing_templates(all_sources) if _routing is None else _routing) if "receiver_route" in enabled else []
    contexts = (constructor_templates(all_sources) if _contexts is None else _contexts) if {
        "constructor_wrap", "constructor_field_lift"} & enabled else []
    proposals = []
    source_hash = hashlib.sha256(source.data).hexdigest()

    def offer(unit, target, after, operator, relation, evidence, priority, imports=None):
        before = source.text(target)
        if before == after:
            return
        edit = {"span": _span(source, target), "before": before, "after": after}
        identifier = _digest([VERSION, source_hash, operator, edit])
        proposals.append({"id": identifier, "operator": operator, "language": source.language,
                          "path": source.path, "source_sha256": source_hash,
                          "test_name": unit.name, "test_span": _span(source, unit.node),
                          "edits": [edit], "relation_target": relation, "evidence": evidence,
                          "imports": imports or [],
                          "oracle_status": "retained_source_assertions_require_contract_review",
                          "priority": priority, "generated_test_name": "rs_" + identifier})

    for unit in tests:
        numeric = []
        for node in walk(unit.body):
            if node.type == "binary_expression" and _pure_numeric(source, node, bindings, node):
                numeric.append(node)
        for node in walk(unit.body):
            if node.type not in CALLS or _assertion_call(source, node):
                continue
            fn, args = call_parts(node)
            path = _path(source, fn)
            if fn is None:
                continue
            if ("constructor_wrap" in enabled and path is not None and len(path) == 1
                and path[0] in source.imports and _resolve(bindings, path[0], node) is None):
                for template in contexts:
                    if _import_signature(source, path) != template["hole_key"]:
                        continue
                    # Do not wrap a context into itself in one step.  The
                    # driver may explicitly permit deeper shapes later.
                    if template["source"].path == source.path and _contains(template["node"], node):
                        continue
                    after, imports = _transport_constructor(template, source, node)
                    offer(unit, node, after, "constructor_wrap",
                          {"kind": "constructor_context", "hole_binding": list(template["hole_key"]),
                           "source_type_only": template["type_only"]},
                          {"template_span": _span(template["source"], template["node"]),
                           "template_text": template["source"].text(template["node"]),
                           "hole_span": _span(template["source"], template["hole"]),
                           "free_imports": {name: list(key) for name, key in template["free_imports"].items()}},
                          (2, 0 if template["type_only"] else 1, node.start_byte, len(after)), imports)
            if ("constructor_field_lift" in enabled and path is not None and len(path) == 1
                and path[0] in source.imports and _resolve(bindings, path[0], node) is None):
                for template in contexts:
                    for after, imports, key, scalar, lifted in _lift_constructor_fields(template, source, node):
                        offer(unit, node, after, "constructor_field_lift",
                              {"kind": "constructor_field_context", "field": key,
                               "source_type_only": template["type_only"]},
                              {"template_span": _span(template["source"], template["node"]),
                               "template_text": template["source"].text(template["node"]),
                               "scalar_callback_body": scalar, "lifted_callback_body": lifted,
                               "rule": "unary_callback_lift_through_matching_record_field"},
                              (1, 0 if template["type_only"] else 1, node.start_byte, len(after)), imports)
            if not args:
                continue
            for index, arg in enumerate(args):
                record = _record_items(source, arg)
                if record is not None:
                    container, items = record
                    all_constant = all(_constant(source, value)[0] for _, _, value in items)
                    if "record_delete" in enabled:
                        for item, key, _ in items:
                            remaining = [source.text(other) for other, _, _ in items if other != item]
                            body = "{" + ", ".join(remaining) + "}"
                            prefix = source.data[arg.start_byte:container.start_byte].decode()
                            suffix = source.data[container.end_byte:arg.end_byte].decode()
                            offer(unit, arg, prefix + body + suffix, "record_delete",
                                  {"kind": "presence", "argument": index, "removed_key": key,
                                   "before_keys": [k for _, k, _ in items],
                                   "after_keys": [k for other, k, _ in items if other != item]},
                                  {"call": source.text(fn), "input_span": _span(source, arg)},
                                  (0 if all_constant and len(items) == 1 else 2, len(items), node.start_byte, index))
                    if "argument_omit" in enabled and index == len(args) - 1:
                        # Optionality is an execution/typecheck obligation, not
                        # guessed from a record shape or a parameter name.
                        after = source.text(fn) + "(" + ", ".join(source.text(a) for a in args[:-1]) + ")"
                        offer(unit, node, after, "argument_omit",
                              {"kind": "argument_presence", "argument": index, "present": False},
                              {"call": source.text(fn), "argument_span": _span(source, arg),
                               "optional_parameter_verified": False},
                              (1 if all_constant and len(items) == 1 else 3, len(items), node.start_byte, index))
                if "expression_rebind" in enabled and arg.type in {"identifier", "binary_expression", "number", "int_literal"}:
                    names = {source.text(n) for n in walk(arg) if n.type == "identifier"}
                    for expression in numeric:
                        expression_names = {source.text(n) for n in walk(expression) if n.type == "identifier"}
                        if not names or not names.intersection(expression_names):
                            continue
                        if not _pure_numeric(source, expression, bindings, node):
                            continue
                        offer(unit, arg, source.text(expression), "expression_rebind",
                              {"kind": "source_expression_equality", "expression": source.text(expression)},
                              {"source_expression": _span(source, expression),
                               "shared_bindings": sorted(names & expression_names)},
                              (4, len(source.text(expression)), node.start_byte, index))
            if "receiver_route" in enabled and path is not None and len(path) == 2:
                receiver = path[0]
                carrier = _carrier(source, bindings, receiver, node)
                if carrier is None:
                    continue
                for template in templates:
                    if (template["method"] != path[-1]
                        or tuple(template["carrier_factory"]) != carrier["factory"]
                        or tuple(template["owner_creator"]) != carrier["creator"]):
                        continue
                    routed_fn = ".".join([carrier["owner"], *template["wrapper_path"], path[-1]])
                    after = routed_fn + "(" + ", ".join([receiver, *(source.text(a) for a in args)]) + ")"
                    offer(unit, node, after, "receiver_route",
                          {"kind": "receiver_context", "before": source.text(fn), "after": routed_fn,
                           "receiver_becomes_argument": 0},
                          {"template": template, "carrier": carrier},
                          (0, 0, node.start_byte, len(args)))
    unique = {p["id"]: p for p in proposals}
    if "guest_result_container" in enabled:
        unique.update({p["id"]: p for p in _guest_container_neighbors(source, all_sources)})
    if "owner_prefix_rebind" in enabled:
        unique.update({p["id"]: p for p in _owner_prefix_neighbors(source)})
    if "guest_alias_route" in enabled:
        unique.update({p["id"]: p for p in _guest_alias_neighbors(source, donors)})
    if "sequence_interval_extend" in enabled:
        unique.update({p["id"]: p for p in _sequence_interval_neighbors(source)})
    if "structured_literal_route" in enabled:
        unique.update({p["id"]: p for p in _structured_literal_neighbors(source)})
    if "numeric_context_route" in enabled:
        unique.update({p["id"]: p for p in _numeric_context_neighbors(source)})
    return sorted(unique.values(), key=lambda p: (p["priority"], p["id"]))[:budget]


def _edit_bytes(data: bytes, edits: list[dict], *, offset=0) -> bytes:
    last_end = -1
    for edit in sorted(edits, key=lambda e: e["span"]["start_byte"]):
        start, end = edit["span"]["start_byte"] - offset, edit["span"]["end_byte"] - offset
        if not 0 <= start <= end <= len(data) or start < last_end:
            raise ValueError("Invalid or overlapping edit")
        if data[start:end].decode() != edit["before"]:
            raise ValueError("Edit source mismatch")
        last_end = end
    for edit in sorted(edits, key=lambda e: e["span"]["start_byte"], reverse=True):
        start, end = edit["span"]["start_byte"] - offset, edit["span"]["end_byte"] - offset
        data = data[:start] + edit["after"].encode() + data[end:]
    return data


def emit_neighbors(source: Source, proposals: Iterable[dict]) -> tuple[str, list[dict]]:
    """Clone edited tests beside their existing lexical context and imports."""
    proposals = list(proposals)
    inventory = {unit.node.start_byte: unit for unit in _tests(source)}
    insertions = defaultdict(list)
    emitted = []
    for proposal in proposals:
        if proposal["source_sha256"] != hashlib.sha256(source.data).hexdigest():
            raise ValueError("Frozen source changed")
        unit = inventory.get(proposal["test_span"]["start_byte"])
        if unit is None:
            raise ValueError("Original test missing")
        if source.language == "typescript":
            _, args = call_parts(unit.node)
            title = args[0]
            new_name = proposal["generated_test_name"]
            rename = {"span": _span(source, title), "before": source.text(title), "after": json.dumps(new_name)}
        else:
            title = child(unit.node, "name")
            new_name = "TestRS_" + proposal["id"]
            rename = {"span": _span(source, title), "before": source.text(title), "after": new_name}
        data = source.data[unit.node.start_byte:unit.node.end_byte]
        body = _edit_bytes(data, [*proposal["edits"], rename], offset=unit.node.start_byte).decode()
        if source.language == "typescript":
            body += ";"
        insertions[unit.node.end_byte].append("\n\n" + body + "\n")
        emitted.append({"id": proposal["id"], "test_name": new_name, "source_test": unit.name,
                        "operator": proposal["operator"], "oracle_status": proposal["oracle_status"]})
    data = source.data
    for position, texts in sorted(insertions.items(), reverse=True):
        data = data[:position] + "".join(texts).encode() + data[position:]
    code = data.decode()
    imports = {}
    for proposal in proposals:
        for item in proposal.get("imports", []):
            imports[(item["name"], item["module"], item.get("imported_name"))] = item
    if imports:
        if source.language != "typescript":
            raise ValueError("Constructor import transport only supports TypeScript")
        lines = []
        for (name, module, imported), item in sorted(imports.items()):
            if imported == "default":
                line = "import " + name + " from " + json.dumps(module) + ";"
            elif imported:
                symbol = imported if imported == name else imported + " as " + name
                line = "import { " + symbol + " } from " + json.dumps(module) + ";"
            else:
                line = "import * as " + name + " from " + json.dumps(module) + ";"
            lines.append(line)
        code = "\n".join(lines) + "\n" + code
    if Source(source.path, code, source.language).root.has_error:
        raise ValueError("Emitted source contains a syntax error")
    return code, emitted


def enrich(corpus: dict, frontend=None, budget=128) -> list[dict]:
    """Adapt neighbours to generic_composition.emitter's candidate contract.

    Only tests already present in the supplied corpus are admitted.  The input
    corpus is not modified.  ``frontend`` is reserved for a caller's shared
    index; this version obtains its bounded facts directly from source ASTs.
    """
    language = corpus.get("language")
    if language not in {"go", "typescript"}:
        return []
    by_path = defaultdict(list)
    for identifier, test in corpus.get("tests", {}).items():
        span = test.get("definition_span", test.get("span", {}))
        if span.get("path") in corpus.get("sources", {}):
            by_path[span["path"]].append((identifier, test))
    sources, donors = [], []
    for path in sorted(corpus.get("sources", {})):
        if path not in by_path and not is_test_path(path):
            continue
        metadata = corpus["sources"][path]
        if metadata.get("parse_error") or not metadata.get("complete_file", True):
            continue
        source = Source(path, metadata["code"], metadata.get("language", language),
                        metadata.get("origin", "repository"))
        donors.append(source)
        if path in by_path:
            sources.append(source)
    proposals = []
    routing = routing_templates(donors)
    contexts = constructor_templates(donors)
    dedup_contexts = {}
    def canonical_tokens(source, node):
        tokens = []
        def visit(part):
            if part.type == "comment":
                return
            if not part.children:
                token = source.text(part)
                if source.origin == "trajectory" and part.type in {"identifier", "type_identifier", "field_identifier"}:
                    # This is the namespace inserted by relational_gap.history,
                    # not a subject-program naming convention.
                    token = re.sub(r"_rh_[0-9a-f]{12}$", "", token)
                tokens.append((part.type, token))
            else:
                for sub in part.children:
                    visit(sub)
        visit(node)
        return tokens
    def equivalent_key(source, row):
        if source.language != "go":
            return row["id"]
        if source.path not in dedup_contexts:
            test_ranges = {(unit.node.start_byte, unit.node.end_byte) for unit in _tests(source)}
            # Keep every non-test declaration, including helper bodies, global
            # initializers and imports. Similar tests with different helper
            # semantics are intentionally not collapsed.
            context = [canonical_tokens(source, node) for node in source.root.named_children
                       if (node.start_byte, node.end_byte) not in test_ranges]
            written = corpus["sources"][source.path].get("written_path") or source.path
            dedup_contexts[source.path] = (posixpath.dirname(written), context)
        span = row["test_span"]
        transformed = _edit_bytes(source.data[span["start_byte"]:span["end_byte"]], row["edits"],
                                  offset=span["start_byte"]).decode()
        temporary = Source("dedup_test.go", "package dedup\n" + transformed, "go", source.origin)
        return _digest([dedup_contexts[source.path], canonical_tokens(temporary, temporary.root)])
    for source in sources:
        by_start = {test.get("definition_span", test["span"])["start_byte"]: (identifier, test)
                    for identifier, test in by_path[source.path]}
        for row in propose_neighbors(source, budget=max(256, budget), _routing=routing, _contexts=contexts):
            matched = by_start.get(row["test_span"]["start_byte"])
            if matched is None:
                continue
            identifier, test = matched
            proposals.append({
                "id": row["id"], "base_test_id": identifier, "source_test_ids": [identifier],
                "edits": [{**edit, "role": edit.get("role", "input")} for edit in row["edits"]],
                "imports": row.get("imports", []), "kind": "source_relation_neighbour", "relation": row["relation_target"],
                "operator": row["operator"], "source_evidence": row["evidence"],
                "oracle_status": row["oracle_status"], "priority": list(row["priority"]),
                "generator": VERSION, "source_sha256": row["source_sha256"],
                "source_retrieval_rank": test.get("retrieval_rank", 100000),
                "equivalence_key": equivalent_key(source, row),
            })
    unique = {}
    for row in sorted(proposals, key=lambda item: (item["source_retrieval_rank"], item["priority"], item["id"])):
        key = row["equivalence_key"]
        if key in unique:
            unique[key].setdefault("equivalent_candidates", []).append({
                "id": row["id"], "base_test_id": row["base_test_id"], "source_sha256": row["source_sha256"]})
        else:
            unique[key] = row
    proposals = list(unique.values())
    # Deterministic round-robin across original observations.  A large fixture
    # does not consume the complete budget before another test is considered.
    groups = defaultdict(list)
    for row in sorted(proposals, key=lambda r: (r["priority"], r["id"])):
        groups[row["base_test_id"]].append(row)
    ordered = sorted(groups, key=lambda key: (
        groups[key][0]["priority"][:2], groups[key][0]["source_retrieval_rank"], key))
    result = []
    while ordered and len(result) < budget:
        remaining = []
        for key in ordered:
            if len(result) >= budget:
                break
            result.append(groups[key].pop(0))
            if groups[key]:
                remaining.append(key)
        ordered = remaining
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--source-path", help="Repository-relative path; needed for import identities")
    parser.add_argument("--donor", action="append", default=[], type=Path)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--language", required=True, choices=["go", "typescript"])
    parser.add_argument("--operators", default=",".join(OPERATORS))
    parser.add_argument("--budget", type=int, default=128)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    def name(path):
        return str(path.resolve().relative_to(args.repository.resolve())) if args.repository else str(path)
    source = Source(args.source_path or name(args.source), args.source.read_text(), args.language)
    donors = [Source(name(path), path.read_text(), args.language) for path in args.donor]
    proposals = propose_neighbors(source, donors, budget=args.budget, operators=args.operators.split(","))
    code, emitted = emit_neighbors(source, proposals)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "proposals.json").write_text(json.dumps(proposals, indent=2) + "\n")
    (args.output / "inventory.json").write_text(json.dumps(analyze_source(source.path, source.code, source.language), indent=2) + "\n")
    (args.output / "emission.json").write_text(json.dumps(emitted, indent=2) + "\n")
    (args.output / Path(source.path).name).write_text(code)
    print(json.dumps({"proposals": len(proposals), "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
