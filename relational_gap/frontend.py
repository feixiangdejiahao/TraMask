"""Deterministic source facts for bounded observation/relationship search.

The frontend extracts syntax and local *may* dependence, never runtime coverage
or an oracle's validity. Calls are opaque; only language and test-framework
syntax is interpreted. Every editable expression has a UTF-8 byte span and a
whole-test owner. Embedded programs in strings deliberately remain opaque.

``extract_frontend`` accepts the existing ``anchor_retrieval.syntax.Source``
objects. Its result is JSON serializable and uses the expression/span conventions
of ``generic_composition.corpus``. ``load_frontend`` is a convenience wrapper.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import posixpath
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from anchor_retrieval.index import Index
from anchor_retrieval.graph import Flow, _locally_rebound
from anchor_retrieval.syntax import (
    ATTRS, CALLS, FUNCTIONS, IDENTIFIERS, Source, Unit, attr_parts, call_parts,
    child, is_test_path, json_safe, literal, load_sources, walk,
)
from generic_composition.corpus import (
    ASSIGNMENTS, CONTAINERS, LITERALS, _assertion_nodes, _callee_identity,
    _identifier_reads, _local_binders, _oracle_value_spans,
    _support, _unit_parameters, span,
)


SCHEMA_VERSION = "relational_frontend.v1"
COMPARISON_OPERATORS = {"<", "<=", ">", ">=", "==", "!=", "===", "!==", "is", "is not", "in", "not in"}
ARITHMETIC_OPERATORS = {"+", "-", "*", "/", "//", "%", "<<", ">>", "&", "|", "^"}
CONTROL_NODES = {
    "if_statement", "elif_clause", "else_clause", "for_statement", "for_in_statement",
    "while_statement", "switch_statement", "expression_switch_statement", "case_statement",
    "expression_case", "default_case", "try_statement", "except_clause", "catch_clause",
    "finally_clause", "with_statement", "select_statement", "communication_case",
    "conditional_expression", "ternary_expression",
}
NESTED_FUNCTIONS = FUNCTIONS | {"arrow_function", "function_expression", "func_literal", "lambda"}
TRUSTED_RESOLUTIONS = {"local_symbol", "package_symbol", "import_symbol", "receiver_type", "constructor", "fixture",
                       "source_constructor_receiver", "source_this_receiver", "source_import_symbol"}


class _FrontendIndex(Index):
    """Apply only caller-supplied tsconfig path facts to module lookup."""
    def __init__(self, sources, patch, *, module_aliases=None, module_base_url=None, **kwargs):
        self.module_aliases = {}
        for pattern, targets in (module_aliases or {}).items():
            targets = [targets] if isinstance(targets, str) else targets
            if (not isinstance(pattern, str) or pattern.count("*") > 1 or not isinstance(targets, (list, tuple))
                    or any(not isinstance(target, str) or target.count("*") > 1 for target in targets)):
                raise ValueError("module_aliases must map single-wildcard patterns to explicit path strings")
            self.module_aliases[pattern] = list(targets)
        if module_base_url is not None and not isinstance(module_base_url, str):
            raise ValueError("module_base_url must be an explicit relative directory string")
        self.module_base_url = module_base_url
        super().__init__(sources, patch, **kwargs)

    def module_paths(self, source_path, module):
        original = super().module_paths(source_path, module)
        if self.sources[source_path].language != "typescript":
            return original
        def paths(base):
            base = posixpath.normpath(base)
            return [path for path in (base, base + ".ts", base + ".tsx", base + ".mts", base + ".cts",
                                      base + "/index.ts", base + "/index.tsx") if path in self.sources]
        if module.startswith("."):
            base = posixpath.join(posixpath.dirname(self.sources[source_path].lookup_path), module)
            return list(dict.fromkeys(original + paths(base)))
        matches = []
        for pattern, targets in self.module_aliases.items():
            if "*" in pattern:
                prefix, suffix = pattern.split("*")
                if not module.startswith(prefix) or not module.endswith(suffix) or len(module) < len(prefix) + len(suffix):
                    continue
                capture = module[len(prefix):len(module) - len(suffix) if suffix else None]
            elif module == pattern:
                capture = ""
            else:
                continue
            priority = ("*" not in pattern, len(pattern.split("*", 1)[0]))
            matches.append((priority, pattern, targets, capture))
        if matches:
            # TypeScript selects the most specific matching paths pattern.
            _, _, targets, capture = max(matches, key=lambda item: (item[0], item[1]))
            for target in targets:
                resolved = paths(posixpath.join(self.module_base_url or "", target.replace("*", capture)))
                if resolved:
                    return resolved
        if self.module_base_url is not None:
            return paths(posixpath.join(self.module_base_url, module))
        return original


def _id(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def expression(source, node):
    """Compact expression: source spans replace recursively duplicated ASTs."""
    if node is None:
        return None
    result = {"text": source.text(node), "kind": node.type, "language": source.language,
              "span": span(source, node),
              "free_identifiers": sorted(_identifier_reads(source, node) - _local_binders(source, node))}
    try:
        result["literal_value"] = json_safe(literal(result["text"]))
        result["literal_known"] = True
    except ValueError:
        result["literal_known"] = False
    if node.type in {"raw_string_literal", "interpreted_string_literal", "string", "template_string"}:
        result["embedded_language"] = "opaque"
    return result


def _compact(value):
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in value.items() if key != "ast"}
    if isinstance(value, list):
        return [_compact(item) for item in value]
    return value


def _contains(outer, inner) -> bool:
    return outer is not None and inner is not None and outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def _owned_walk(root):
    """Do not attribute uncalled nested function bodies to the enclosing test."""
    yield root
    for node in root.named_children:
        if node.type not in NESTED_FUNCTIONS:
            yield from _owned_walk(node)


def _test_walk(root):
    """Anonymous callback bodies retain whole-test ownership and unknown phase."""
    yield root
    for node in root.named_children:
        if node.type not in FUNCTIONS | {"lambda"}:
            yield from _test_walk(node)


def _flow_for_test(index, unit, nodes):
    base = index.flow(unit.id)
    callbacks = [n for n in nodes if n.type in {"arrow_function", "function_expression", "func_literal"}]
    if not callbacks:
        return base
    # Callback execution is not assumed. Their assertions are lexical facts,
    # with the callback context retained on each observation. Isolated local
    # flow graphs prevent captured names being equated with unrelated bindings.
    flow = copy.copy(base)
    flow.nodes = list(base.nodes)
    flow.edges = collections.defaultdict(set, {k: set(v) for k, v in base.edges.items()})
    flow.edge_kinds = dict(base.edge_kinds)
    flow.assertions = list(base.assertions)
    flow.calls = list(base.calls)
    for callback in callbacks:
        body = child(callback, "body")
        if body is None:
            continue
        nested = Unit(unit.source, callback, body, unit.name + ".<callback>", unit.owner, True)
        parameters = _parameters(nested)
        nested.params = [p["name"] for p in parameters if p["name"] is not None]
        nested.param_types = dict(unit.param_types)
        nested.param_types.update({p["name"]: p.get("type", "") for p in parameters if p["name"] is not None})
        extra = Flow(index, nested)
        offset = len(flow.nodes)
        flow.nodes.extend(dict(node, id=node["id"] + offset) for node in extra.nodes)
        for a, deps in extra.edges.items():
            flow.edges[a + offset].update(b + offset for b in deps)
        flow.edge_kinds.update({(a + offset, b + offset): kind for (a, b), kind in extra.edge_kinds.items()})
        flow.assertions.extend(replace(assertion, node=assertion.node + offset) for assertion in extra.assertions)
        def shifted(value):
            return replace(value, id=value.id + offset) if value is not None else None
        flow.calls.extend(replace(call, node=call.node + offset, args=[shifted(v) for v in call.args],
                                  keywords={k: shifted(v) for k, v in call.keywords.items()},
                                  receiver=shifted(call.receiver)) for call in extra.calls)
    return flow


def _exception_observations(unit, nodes):
    """Recognize source-proved pytest exception context managers."""
    if unit.source.language != "python":
        return
    source = unit.source
    for statement in nodes:
        if statement.type != "with_statement":
            continue
        body = child(statement, "body")
        if body is None:
            continue
        header = [n for n in walk(statement) if n.type in CALLS and n.end_byte <= body.start_byte]
        for call in header:
            fn, args = call_parts(call)
            name = source.text(fn)
            parts = name.split(".")
            imported = source.imports.get(parts[0])
            proven = (imported == ("pytest", None) and parts[1:] == ["raises"]
                      or imported == ("pytest", "raises") and len(parts) == 1)
            if not proven or parts[0] in unit.params or _locally_rebound(unit, parts[0]) or not args:
                continue
            expected = next((a for a in args if a.type != "keyword_argument"), None)
            if expected is None:
                continue
            operations = [n for n in _owned_walk(body) if n.type in CALLS]
            observed = operations[0] if len(operations) == 1 else body
            yield statement, observed, expected


def _diagnostic_call(unit, node):
    source = unit.source
    fn, _ = call_parts(node)
    if fn is None:
        return False
    if source.language == "go" and fn.type in ATTRS:
        receiver, method = attr_parts(fn)
        if receiver is None or receiver.type != "identifier":
            return False
        name = source.text(receiver)
        types = dict(unit.param_types)
        parent = node.parent
        while parent is not None and parent != unit.body:
            if parent.type == "func_literal":
                callback = Unit(source, parent, child(parent, "body"), "<callback>")
                for parameter in _parameters(callback):
                    if parameter["name"] is not None:
                        types[parameter["name"]] = parameter.get("type", "")
                break
            parent = parent.parent
        typename = types.get(name, "").lstrip("*").split(".")
        return (len(typename) == 2 and typename[1] in {"T", "B", "F", "TB"}
                and source.imports.get(typename[0], (None,))[0] == "testing"
                and source.text(method) in {"Fatal", "Fatalf", "Error", "Errorf", "Fail", "FailNow", "Log", "Logf", "Skip", "Skipf", "SkipNow"}
                and not _locally_rebound(unit, name))
    if source.language == "python":
        parts = source.text(fn).split(".")
        imported = source.imports.get(parts[0])
        return ((imported == ("pytest", None) and parts[1:] in [["fail"], ["skip"]])
                or imported in {("pytest", "fail"), ("pytest", "skip")} and len(parts) == 1)
    return False


def _assertion_message(unit, node):
    if unit.source.language != "python":
        return False
    parent = node.parent
    while parent is not None and parent != unit.body:
        if parent.type == "assert_statement":
            pieces = parent.named_children
            return len(pieces) > 1 and _contains(pieces[1], node)
        parent = parent.parent
    return False


def _whole_test(unit):
    node = unit.node
    if node.parent is not None and node.parent.type == "decorated_definition":
        node = node.parent
    if unit.source.language == "typescript" and node.parent is not None and node.parent.type == "expression_statement":
        node = node.parent
    return node


def _unwrap(node):
    while node is not None and node.type in {"parenthesized_expression", "expression_list", "literal_element"} and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


def _root_name(source, node):
    node = _unwrap(node)
    while node is not None:
        if node.type == "identifier":
            return source.text(node)
        if node.type in ATTRS:
            node = attr_parts(node)[0]
        elif node.type in {"subscript", "subscript_expression", "index_expression"}:
            node = child(node, "object", "value", "operand")
        else:
            return None
    return None


def _contexts(source, node, boundary):
    result = []
    current = node.parent
    while current is not None and current != boundary:
        if current.type in CONTROL_NODES or current.type in NESTED_FUNCTIONS:
            condition = child(current, "condition")
            branch = next((current.field_name_for_child(i) or n.type
                           for i, n in enumerate(current.children) if _contains(n, node)), None)
            result.append({"kind": current.type, "span": span(source, current),
                           "branch": branch, "condition": expression(source, condition)})
        current = current.parent
    return list(reversed(result))


def _parameters(unit):
    """Retain actual default expressions, including nonliteral defaults."""
    source = unit.source
    params = child(unit.node, "parameters")
    if params is None and unit.source.language == "typescript" and unit.test:
        _, args = call_parts(unit.node)
        callback = next((a for a in reversed(args) if a.type in NESTED_FUNCTIONS), None)
        params = child(callback, "parameters") if callback is not None else None
    result = []
    keyword_only = False
    for parameter in params.named_children if params is not None else []:
        if parameter.type == "comment":
            continue
        if parameter.type == "keyword_separator":
            keyword_only = True
            continue
        if parameter.type == "positional_separator":
            for item in result:
                item["positional_only"] = True
            continue
        default = child(parameter, "value")
        target = child(parameter, "name", "pattern")
        if parameter.type in {"identifier", "list_splat_pattern", "dictionary_splat_pattern"}:
            target = parameter
        variadic = ("variadic" in parameter.type or "splat" in parameter.type
                    or (target is not None and "rest" in target.type))
        names = parameter.children_by_field_name("name") if source.language == "go" else []
        if not names and target is not None:
            if target.type == "identifier":
                names = [target]
            elif target.type in {"list_splat_pattern", "dictionary_splat_pattern", "rest_pattern"}:
                names = [n for n in target.named_children if n.type == "identifier"]
        if not names:
            result.append({"name": None, "index": len(result), "span": span(source, parameter),
                           "pattern": source.text(target or parameter), "default": expression(source, default),
                           "variadic": variadic, "keyword_only": keyword_only,
                           "positional_only": False, "binding_status": "unsupported_pattern"})
        for name in names:
            result.append({"name": source.text(name), "index": len(result), "span": span(source, parameter),
                           "name_span": span(source, name), "default": expression(source, default),
                           "type": source.text(child(parameter, "type")), "variadic": variadic,
                           "keyword_only": keyword_only, "positional_only": False,
                           "binding_status": "direct_parameter"})
        if variadic:
            keyword_only = True
    return result


def _removal_span(source, items, index):
    """A single-item deletion span, preserving comments outside that item.

    Adjacent commas are lexical tokens, not characters inside strings/comments.
    Multiple deletions require a separate list-aware editor: these spans can
    overlap when adjacent elements are removed together.
    """
    node = items[index]
    parent = node.parent
    commas = [n for n in parent.children if n.type == ","] if parent is not None else []
    following = next((n for n in commas if n.start_byte >= node.end_byte), None)
    previous = next((n for n in reversed(commas) if n.end_byte <= node.start_byte), None)
    start, end = node.start_byte, node.end_byte
    if following is not None:
        end = following.end_byte
    elif previous is not None:
        start = previous.start_byte
    return {"path": source.path, "start_byte": start, "end_byte": end,
            "line": source.data[:start].count(b"\n") + 1,
            "end_line": source.data[:end].count(b"\n") + 1}


def _arguments(source, node):
    _, args = call_parts(node)
    args = [arg for arg in args if arg.type != "comment"]
    result = []
    positional = 0
    for i, arg in enumerate(args):
        keyword = source.text(child(arg, "name")) if arg.type == "keyword_argument" else None
        value = child(arg, "value") if keyword is not None else arg
        record = expression(source, value)
        record.update({"slot": i, "keyword": keyword, "argument_span": span(source, arg),
                       "removal_span": _removal_span(source, args, i),
                       "positional_index": positional if keyword is None else None,
                       "spread": "spread" in arg.type or "splat" in arg.type or "variadic" in arg.type})
        result.append(record)
        if keyword is None:
            positional += 1
    return result


def _structure(source, node):
    """Syntactic field presence; no schema/default/interval semantics inferred."""
    node = _unwrap(node)
    if node is None:
        return None
    original = node
    if node.type == "composite_literal":
        node = child(node, "body")
    if node is None or node.type not in CONTAINERS | {"literal_value", "set"}:
        return None
    entries = [item for item in node.named_children if item.type != "comment"]
    fields = []
    unknown = []
    sequence = node.type in {"list", "tuple", "array", "set"}
    for i, entry in enumerate(entries):
        key = None
        key_kind = "index" if sequence else "unknown"
        value = entry
        if sequence or (node.type == "literal_value" and entry.type == "literal_element"):
            key, value = i, _unwrap(entry)
        elif entry.type in {"pair", "keyed_element"}:
            key_node, value = _unwrap(child(entry, "key")), _unwrap(child(entry, "value"))
            if key_node is not None:
                try:
                    key = json_safe(literal(source.text(key_node)))
                    key_kind = "literal_key"
                except ValueError:
                    if source.language == "typescript" and key_node.type in IDENTIFIERS:
                        key, key_kind = source.text(key_node), "property_name"
                    elif source.language == "go" and key_node.type == "identifier":
                        key, key_kind = source.text(key_node), "field_or_dynamic_key"
                    else:
                        key, key_kind = source.text(key_node), "dynamic_key"
        elif entry.type == "shorthand_property_identifier":
            key, key_kind = source.text(entry), "property_name"
        else:
            unknown.append(span(source, entry))
        if value is not None:
            fields.append({"key": key, "key_kind": key_kind, "value": expression(source, value),
                           "entry_span": span(source, entry), "removal_span": _removal_span(source, entries, i)})
    return {"kind": "sequence" if sequence else "record_syntax", "span": span(source, original),
            "fields": fields, "explicit_count": len(fields), "unknown_entries": unknown,
            "complete_keys": not unknown and all(f["key_kind"] in {"literal_key", "property_name", "index"} for f in fields),
            "semantic_status": "syntax_only_no_schema_contract"}


def _expression_ir(source, node, depth=0):
    """Finite expression language for relation enumeration; unknown stays unknown."""
    node = _unwrap(node)
    if node is None or depth > 12:
        return {"kind": "unknown", "reason": "missing_or_depth_bound"}
    text = source.text(node)
    base = {"span": span(source, node), "text": text}
    try:
        value = literal(text)
        if isinstance(value, (int, float, str, bool)) or value is None:
            return dict(base, kind="literal", value=json_safe(value))
    except ValueError:
        pass
    if node.type == "identifier":
        return dict(base, kind="symbol", name=text)
    if node.type in ATTRS:
        obj, key = attr_parts(node)
        return dict(base, kind="field", object=_expression_ir(source, obj, depth + 1), field=source.text(key))
    if node.type in {"binary_expression", "binary_operator"}:
        operator = source.text(child(node, "operator"))
        if not operator:
            operator = " ".join(source.text(n) for n in node.children if not n.is_named)
        if operator in ARITHMETIC_OPERATORS:
            return dict(base, kind="binary", operator=operator,
                        left=_expression_ir(source, child(node, "left"), depth + 1),
                        right=_expression_ir(source, child(node, "right"), depth + 1))
    if node.type in {"unary_expression", "unary_operator"}:
        operator = source.text(child(node, "operator"))
        operand = child(node, "operand", "argument") or (node.named_children[-1] if node.named_children else None)
        if operator in {"+", "-", "~", "!", "not"}:
            return dict(base, kind="unary", operator=operator, operand=_expression_ir(source, operand, depth + 1))
    return dict(base, kind="unknown", reason="unsupported_expression", syntax_kind=node.type)


def _comparison_parts(source, node):
    if node.type == "comparison_operator":
        values = node.named_children
        operators = [source.text(n) for n in node.children if not n.is_named]
        if len(operators) == len(values) - 1:
            return [(a, op, b) for a, op, b in zip(values, operators, values[1:]) if op in COMPARISON_OPERATORS]
    if node.type in {"binary_expression", "binary_operator"}:
        operator = source.text(child(node, "operator"))
        if operator in COMPARISON_OPERATORS:
            return [(child(node, "left"), operator, child(node, "right"))]
    return []


def _bindings(unit, nodes):
    source = unit.source
    records = []
    for node in nodes:
        if node.type not in ASSIGNMENTS | {"assignment_expression", "augmented_assignment_expression"}:
            continue
        left, right = child(node, "left", "name"), child(node, "right", "value")
        if left is None or right is None:
            continue
        lefts = left.named_children if left.type in {"expression_list", "pattern_list"} else [left]
        rights = right.named_children if right.type == "expression_list" else [right]
        exact = len(lefts) == len(rights)
        for i, target in enumerate(lefts):
            value = _unwrap(rights[i]) if exact else right
            name = source.text(target)
            records.append({"id": _id(unit.id, "binding", target.start_byte), "test_id": unit.id,
                            "name": name, "target": expression(source, target), "value": expression(source, value),
                            "span": span(source, node), "definition_end": node.end_byte,
                            "simple_name": target.type == "identifier", "projection_known": exact,
                            "alias_name": source.text(value) if exact and value.type == "identifier" else None,
                            "contexts": _contexts(source, node, unit.body),
                            "identity_status": "same_value_assignment_only; object_identity_not_proved"})
    return records


def _binding_for(unit, node, bindings):
    """Versioned local binding; conditional writes conservatively block alias proof."""
    name = _root_name(unit.source, node)
    if name is None:
        return None
    before = node.start_byte
    active = [b for b in bindings if b["simple_name"] and b["name"] == name and b["definition_end"] <= before]
    current = max(active, key=lambda b: b["definition_end"]) if active else None
    origin = current
    seen = set()
    while origin is not None and origin["alias_name"] and not origin["contexts"] and origin["id"] not in seen:
        seen.add(origin["id"])
        previous = [b for b in bindings if b["simple_name"] and b["name"] == origin["alias_name"]
                    and b["definition_end"] <= origin["span"]["start_byte"]]
        if not previous:
            break
        origin = max(previous, key=lambda b: b["definition_end"])
    uncertain = current is not None and bool(current["contexts"])
    return {"name": name, "binding_id": current["id"] if current is not None else None,
            "origin_binding_id": origin["id"] if origin is not None and not uncertain else None,
            "scope_id": unit.id, "resolution": "conditional_write_unknown" if uncertain else
            "local_value_binding" if current is not None else "parameter_or_external_binding",
            "object_identity": "unknown"}


def _bind_arguments(unit, arguments, targets, functions):
    result = []
    for target in targets:
        fn = functions[target["function_id"]]
        parameters = fn["parameters"]
        if unit.source.language == "python" and parameters and parameters[0]["name"] in {"self", "cls"} and fn["owner"]:
            parameters = parameters[1:]
        position = 0
        spread_seen = False
        for arg in arguments:
            if arg["keyword"] is not None:
                matches = [p for p in parameters if p["name"] == arg["keyword"]]
                parameter = matches[0] if len(matches) == 1 else None
            elif not spread_seen:
                positional = [p for p in parameters if not p["keyword_only"]]
                parameter = positional[position] if position < len(positional) else None
                position += 1
            else:
                parameter = None
            spread_seen |= arg["spread"]
            if parameter is not None:
                result.append({"slot": arg["slot"], "parameter": parameter["name"],
                               "parameter_index": parameter["index"], "function_id": target["function_id"],
                               "resolution": target["reason"],
                               "binding_status": "unknown_spread_or_variadic" if arg["spread"] or parameter["variadic"] else "direct_actual_formal"})
    return result


def _function_record(unit):
    receiver = child(unit.node, "receiver")
    return {"id": unit.id, "name": unit.name, "owner": unit.owner, "language": unit.source.language,
            "span": span(unit.source, unit.node), "body_span": span(unit.source, unit.body),
            "parameters": _parameters(unit), "receiver": expression(unit.source, receiver),
            "test": unit.test, "production": not unit.test and not is_test_path(unit.source.path)}


def _ts_symbols(index, path, name, *, exported=False, seen=None):
    """Resolve explicit ES import/export aliases without same-name fallback."""
    seen = set() if seen is None else set(seen)
    key = (path, name, exported)
    if key in seen or path not in index.sources:
        return []
    seen.add(key)
    source = index.sources[path]
    found = []
    if not exported:
        for node in source.root.named_children:
            declaration = child(node, "declaration") if node.type == "export_statement" else node
            if declaration is not None and declaration.type == "class_declaration" and source.text(child(declaration, "name")) == name:
                found.append(("class", path, name))
        found.extend(("function", unit.id) for unit in index.by_file_name.get((path, name), []) if not unit.test and not unit.owner)
        if name in source.imports:
            module, member = source.imports[name]
            if member:
                for target in index.module_paths(path, module):
                    found.extend(_ts_symbols(index, target, member, exported=True, seen=seen))
        return sorted(set(found))
    for statement in source.root.named_children:
        if statement.type != "export_statement":
            continue
        declaration = child(statement, "declaration")
        if declaration is not None:
            declared = source.text(child(declaration, "name"))
            is_default = any(n.type == "default" for n in statement.children)
            if (name == "default" and is_default) or (name == declared and not is_default):
                found.extend(_ts_symbols(index, path, declared, seen=seen))
            if declaration.type in {"lexical_declaration", "variable_declaration"} and not is_default:
                if any(source.text(child(n, "name")) == name for n in declaration.named_children if n.type == "variable_declarator"):
                    found.extend(_ts_symbols(index, path, name, seen=seen))
        module_node = child(statement, "source")
        try:
            module = literal(source.text(module_node)) if module_node is not None else None
        except ValueError:
            module = None
        specifiers = [n for n in walk(statement) if n.type == "export_specifier"]
        for specifier in specifiers:
            original = source.text(child(specifier, "name"))
            alias = source.text(child(specifier, "alias")) or original
            if alias != name:
                continue
            if module is None:
                found.extend(_ts_symbols(index, path, original, seen=seen))
            else:
                for target in index.module_paths(path, module):
                    found.extend(_ts_symbols(index, target, original, exported=True, seen=seen))
        if module is not None and not specifiers and any(n.type == "*" for n in statement.children) and name != "default":
            for target in index.module_paths(path, module):
                found.extend(_ts_symbols(index, target, name, exported=True, seen=seen))
    return sorted(set(found))


def _ts_name_symbols(index, unit, name):
    if unit.source.language == "python":
        return _python_name_symbols(index, unit, name)
    parts = name.split(".")
    if not parts or parts[0] in unit.params or _locally_rebound(unit, parts[0]):
        return []
    if len(parts) == 1:
        return _ts_symbols(index, unit.source.path, name)
    imported = unit.source.imports.get(parts[0])
    if len(parts) == 2 and imported and imported[1] is None:
        return sorted({symbol for path in index.module_paths(unit.source.path, imported[0])
                       for symbol in _ts_symbols(index, path, parts[1], exported=True)})
    return []


def _python_symbols(index, path, name, seen=None):
    seen = set() if seen is None else set(seen)
    if (path, name) in seen or path not in index.sources:
        return []
    seen.add((path, name))
    source = index.sources[path]
    result = []
    for node in source.root.named_children:
        declaration = child(node, "definition") if node.type == "decorated_definition" else node
        if declaration is not None and declaration.type == "class_definition" and source.text(child(declaration, "name")) == name:
            result.append(("class", path, name))
    result.extend(("function", unit.id) for unit in index.by_file_name.get((path, name), []) if not unit.owner and not unit.test)
    imported = source.imports.get(name)
    if imported and imported[1]:
        for target in index.module_paths(path, imported[0]):
            result.extend(_python_symbols(index, target, imported[1], seen))
    return sorted(set(result))


def _python_name_symbols(index, unit, name):
    parts = name.split(".")
    if not parts or parts[0] in unit.params or _locally_rebound(unit, parts[0]):
        return []
    if len(parts) == 1:
        return _python_symbols(index, unit.source.path, name)
    imported = unit.source.imports.get(parts[0])
    if imported and imported[1] is None:
        written_module = ".".join(parts[:-1])
        module = (written_module if written_module == imported[0] or written_module.startswith(imported[0] + ".")
                  else imported[0] + ("." + ".".join(parts[1:-1]) if len(parts) > 2 else ""))
        return sorted({symbol for path in index.module_paths(unit.source.path, module)
                       for symbol in _python_symbols(index, path, parts[-1])})
    return []


def _ts_receiver_class(index, unit, receiver, before, seen=None):
    receiver = _unwrap(receiver)
    if receiver is None:
        return []
    source = unit.source
    if receiver.type == "this" and unit.owner:
        return [("class", source.path, unit.owner)]
    if source.language == "python" and receiver.type == "identifier" and source.text(receiver) in {"self", "cls"} and unit.owner:
        if not _locally_rebound(unit, source.text(receiver)):
            return [("class", source.path, unit.owner)]
    if receiver.type == "new_expression" or (source.language == "python" and receiver.type == "call"):
        constructor, _ = call_parts(receiver)
        return [s for s in _ts_name_symbols(index, unit, source.text(constructor)) if s[0] == "class"]
    if receiver.type != "identifier":
        return []
    name = source.text(receiver)
    seen = set() if seen is None else set(seen)
    if name in seen:
        return []
    seen.add(name)
    bindings = []
    for node in _test_walk(unit.body):
        if node.type not in ASSIGNMENTS | {"assignment_expression"} or node.end_byte > before:
            continue
        target, value = child(node, "name", "left"), child(node, "value", "right")
        if target is not None and target.type == "identifier" and source.text(target) == name:
            if node.type == "variable_declarator":
                lexical = node.parent
                while lexical is not None and lexical.type not in {"program", "module", "statement_block", "block"} | NESTED_FUNCTIONS:
                    lexical = lexical.parent
                if lexical is not None and not _contains(lexical, receiver):
                    continue
            bindings.append((node, value))
    if not bindings:
        # Captured setup variables may live in a surrounding suite/module.
        parent = unit.node.parent
        while parent is not None:
            if parent.type in {"program", "module", "statement_block", "block"}:
                for statement in parent.named_children:
                    if statement.end_byte > unit.node.start_byte or statement.type not in {"lexical_declaration", "variable_declaration", "expression_statement"}:
                        continue
                    for node in statement.named_children:
                        target, value = child(node, "name", "left"), child(node, "value", "right")
                        if target is not None and target.type == "identifier" and source.text(target) == name:
                            bindings.append((node, value))
            parent = parent.parent
    if not bindings:
        return []
    definition, value = max(bindings, key=lambda pair: pair[0].end_byte)
    if value is None:
        return []
    # Branches, loops, deferred callbacks, and captures can have other reaching
    # definitions; an unqualified latest-text binding is not a type proof.
    contexts = _contexts(source, definition, unit.body)
    if any(c["kind"] in CONTROL_NODES or (c["kind"] in NESTED_FUNCTIONS
                                         and not c["span"]["start_byte"] <= receiver.start_byte < c["span"]["end_byte"])
           for c in contexts):
        return []
    return _ts_receiver_class(index, unit, value, definition.start_byte, seen)


def _resolved_targets(index, unit, node, flow_call=None):
    fn, _ = call_parts(node)
    base = list(flow_call.targets if flow_call is not None else index.resolve(unit, unit.source.text(fn)))
    if unit.source.language not in {"typescript", "python"} or fn is None:
        return base
    if fn.type in ATTRS:
        receiver, method = attr_parts(fn)
        classes = _ts_receiver_class(index, unit, receiver, node.start_byte)
        if classes:
            found = [(target.id, "source_this_receiver" if receiver.type == "this" or unit.source.text(receiver) in {"self", "cls"} else "source_constructor_receiver")
                     for _, path, owner in classes for target in index.by_file_name.get((path, unit.source.text(method)), [])
                     if target.owner == owner]
            if found:
                return sorted(set(found))
        if receiver is not None and receiver.type == "identifier":
            name = unit.source.text(receiver)
            uncertain_writes = [n for n in _test_walk(unit.body)
                                if n.type in ASSIGNMENTS | {"assignment_expression"}
                                and n.end_byte <= node.start_byte and unit.source.text(child(n, "left", "name")) == name
                                and _contexts(unit.source, n, unit.body)]
            if uncertain_writes:
                # The legacy Flow joins possible class types while dropping an
                # unknown alternative. Such a join is not constructor proof.
                base = [(uid, reason) for uid, reason in base if reason != "receiver_type"]
    if not any(reason in TRUSTED_RESOLUTIONS for _, reason in base):
        targets = [(s[1], "source_import_symbol") for s in _ts_name_symbols(index, unit, unit.source.text(fn)) if s[0] == "function"]
        if targets:
            return sorted(set(targets))
    return base


def _call_identity(index, unit, node, flow_call, targets):
    proven = [(uid, reason) for uid, reason in targets if reason in TRUSTED_RESOLUTIONS]
    if len(proven) == 1:
        target = index.units[proven[0][0]]
        fn, _ = call_parts(node)
        return {"canonical": target.source.path + "::" + target.owner + "." + target.name,
                "resolution": proven[0][1], "display": unit.source.text(fn)}
    return _callee_identity(index, unit, node, flow_call)


def _add_assigned_functions(index, sources):
    """Extend declaration discovery to named TypeScript function values."""
    present = {(u.source.path, u.node.start_byte, u.node.end_byte) for u in index.units.values()}
    for source in sources:
        if source.language != "typescript":
            continue
        for declaration in walk(source.root):
            if declaration.type != "variable_declarator":
                continue
            name, node = child(declaration, "name"), _unwrap(child(declaration, "value"))
            if (name is None or name.type != "identifier" or node is None
                    or node.type not in {"arrow_function", "function_expression"}
                    or (source.path, node.start_byte, node.end_byte) in present):
                continue
            body = child(node, "body")
            if body is None:
                continue
            unit = Unit(source, node, body, source.text(name))
            parameters = _parameters(unit)
            unit.params = [p["name"] for p in parameters if p["name"] is not None]
            unit.param_types = {p["name"]: p.get("type", "") for p in parameters if p["name"] is not None}
            index.units[unit.id] = unit
            index.by_name[unit.name].append(unit)
            index.by_file_name[source.path, unit.name].append(unit)
            if (source.origin == "repository" and not is_test_path(source.path)
                    and any(node.start_point.row + 1 <= line <= node.end_point.row + 1
                            for line in index.changed_lines.get(source.path, ()))):
                index.changed.add(unit.id)


def _field_defaults(unit, function):
    """JavaScript property defaults from executable syntax, not schema guesses."""
    if unit.source.language != "typescript":
        return []
    source = unit.source
    result = []
    parameters = function["parameters"]
    parameter_nodes = child(unit.node, "parameters")
    parameter_nodes = [n for n in parameter_nodes.named_children if n.type != "comment"] if parameter_nodes is not None else []
    def record(node, field_path, default, source_node, parameter_index, mechanism):
        if not field_path or default is None:
            return
        parameter = parameters[parameter_index]["name"] if parameter_index is not None and parameter_index < len(parameters) else None
        result.append({"id": _id(unit.id, "field_default", node.start_byte), "function_id": unit.id,
                       "field": field_path[-1], "field_path": field_path, "default": expression(source, default),
                       "span": span(source, node), "source_expression": expression(source, source_node),
                       "parameter": parameter, "parameter_index": parameter_index,
                       "mechanism": mechanism, "caller_bindings": [],
                       "applicability": "source_default_not_proved_on_all_paths"})
    def visit_pattern(pattern, source_node, parameter_index, path=()):
        if pattern is None or pattern.type != "object_pattern":
            return
        for entry in pattern.named_children:
            if entry.type == "object_assignment_pattern":
                left, default = child(entry, "left"), child(entry, "right")
                record(entry, [*path, source.text(left)], default, source_node, parameter_index, "destructuring_default")
            elif entry.type == "pair_pattern":
                key, value = child(entry, "key"), child(entry, "value")
                if key is None or value is None:
                    continue
                try:
                    field = literal(source.text(key))
                except ValueError:
                    field = source.text(key) if key.type in IDENTIFIERS else None
                if not isinstance(field, str):
                    continue
                if value.type == "assignment_pattern":
                    record(entry, [*path, field], child(value, "right"), source_node, parameter_index, "destructuring_default")
                elif value.type == "object_pattern":
                    visit_pattern(value, source_node, parameter_index, (*path, field))
    for i, parameter in enumerate(parameter_nodes):
        visit_pattern(child(parameter, "pattern"), None, i)
    nodes = list(_owned_walk(unit.body))
    def parameter_for(name):
        if _locally_rebound(unit, name):
            return None
        matches = [p["index"] for p in parameters if p["name"] == name]
        return matches[0] if len(matches) == 1 else None
    for node in nodes:
        if node.type == "variable_declarator":
            target, origin = child(node, "name"), _unwrap(child(node, "value"))
            index = parameter_for(source.text(origin)) if origin is not None and origin.type == "identifier" else None
            visit_pattern(target, origin, index)
        if node.type == "binary_expression" and source.text(child(node, "operator")) == "??":
            left, right = _unwrap(child(node, "left")), child(node, "right")
            if left is None or left.type not in ATTRS:
                continue
            path, root = [], left
            while root is not None and root.type in ATTRS:
                root, field = attr_parts(root)
                path.insert(0, source.text(field))
            if root is not None and root.type == "identifier":
                record(node, path, right, root, parameter_for(source.text(root)), "nullish_coalescing")
    return result


def _propagate_field_defaults(defaults, calls, functions, max_depth):
    """Trace exact whole-object actual/formal forwarding back to test slots.

    This is a bounded syntactic path, not proof that all branches normalize a
    field, nor proof a test's expected value survives omission of that field.
    """
    incoming = collections.defaultdict(list)
    for call in calls:
        for binding in call["argument_bindings"]:
            if binding["binding_status"] == "direct_actual_formal":
                incoming[binding["function_id"], binding["parameter_index"]].append((call, binding))
    for default in defaults:
        if default["parameter_index"] is None:
            continue
        queue = collections.deque([(default["function_id"], default["parameter_index"], (), 0)])
        seen = set()
        while queue:
            function_id, parameter_index, path, depth = queue.popleft()
            key = (function_id, parameter_index)
            if key in seen or depth > max_depth:
                continue
            seen.add(key)
            for call, binding in incoming[key]:
                if binding["resolution"] not in TRUSTED_RESOLUTIONS:
                    continue
                argument = next(a for a in call["arguments"] if a["slot"] == binding["slot"])
                edge = {"call_id": call["id"], "function_id": function_id, "parameter_index": parameter_index,
                        "slot": argument["slot"], "argument_span": argument["span"], "resolution": binding["resolution"]}
                edges = (edge, *path)
                if call.get("test_id") is not None:
                    default["caller_bindings"].append({"test_id": call["test_id"], "call_id": call["id"],
                                                        "slot": argument["slot"], "argument_span": argument["span"],
                                                        "path": list(edges), "resolution": "resolved_actual_formal_path",
                                                        "applicability": "source_default_not_proved_on_all_paths"})
                elif argument["kind"] == "identifier":
                    owner = functions[call["function_id"]]
                    params = [p for p in owner["parameters"] if p["name"] == argument["text"]]
                    if len(params) == 1:
                        queue.append((owner["id"], params[0]["index"], edges, depth + 1))


def extract_frontend(
    sources: Iterable[Source], *, patch: str = "", test_ids: Iterable[str] | None = None,
    max_production_depth: int = 3, max_production_units: int = 256, max_tests: int | None = None,
    module_aliases: dict | None = None, module_base_url: str | None = None,
) -> dict:
    """Extract exact source facts; stable ordering is by path/byte position.

    Sources, including historical snippets, must be supplied by the caller.
    Merely supplying a test does not establish it was executed. Changed functions
    and reachable functions supply production predicates even when current
    candidate behavior has removed a dependence into the observation.
    """
    if max_production_depth < 0 or max_production_units < 0 or (max_tests is not None and max_tests < 0):
        raise ValueError("frontend bounds must be nonnegative")
    sources = sorted(list(sources), key=lambda s: s.path)
    if len({s.path for s in sources}) != len(sources):
        raise ValueError("source paths must be unique")
    index = _FrontendIndex(sources, patch, max_depth=max_production_depth, max_reachable=max_production_units,
                           module_aliases=module_aliases, module_base_url=module_base_url)
    _add_assigned_functions(index, sources)
    # A trajectory can contain a complete validation program instead of a test
    # registration. Preserve its owner; the emitter adapter labels the wrapper
    # requirement rather than pretending the module already is a test function.
    for source in sources:
        if source.origin != "trajectory" or source.language != "python":
            continue
        if any(u.test and u.source.path == source.path for u in index.units.values()):
            continue
        if any(n.type in CALLS and source.text(call_parts(n)[0]) == "print" for n in _owned_walk(source.root)):
            unit = Unit(source, source.root, source.root, "<script>", test=True)
            index.units[unit.id] = unit
    selected_ids = set(test_ids) if test_ids is not None else None
    tests = sorted((u for u in index.units.values() if u.test and not u.source.type_only and (selected_ids is None or u.id in selected_ids)),
                   key=lambda u: (u.source.path, u.node.start_byte))
    available_tests = len(tests)
    if max_tests is not None:
        tests = tests[:max_tests]
    result = {"schema_version": SCHEMA_VERSION,
              "module_resolution": {"aliases": index.module_aliases, "base_url": index.module_base_url,
                                    "evidence": "caller_supplied_explicit_config"},
              "sources": {s.path: {"code": s.code, "language": s.language, "origin": s.origin,
                                   "step": s.step, "written_path": s.written_path, "parse_error": s.root.has_error}
                          for s in sources},
              "tests": [], "observations": [], "calls": [], "values": [], "bindings": [], "events": [],
              "functions": [], "comparisons": [], "guards": [], "field_defaults": [],
              "production_calls": [], "unknowns": [],
              "coverage_status": "static_only_execution_and_assertion_validity_unknown"}
    functions = {u.id: _function_record(u) for u in index.units.values()}
    production_reasons = collections.defaultdict(list)
    for uid in sorted(index.changed):
        production_reasons[uid].append({"kind": "changed_function", "test_id": None, "depth": 0})
    reached = set()
    for unit in tests:
        source = unit.source
        nodes = list(_test_walk(unit.body))
        node_map = {(n.start_byte, n.end_byte): n for n in nodes}
        flow = _flow_for_test(index, unit, nodes)
        whole = _whole_test(unit)
        enclosing_scope = whole.parent
        while enclosing_scope is not None and enclosing_scope.type not in {"module", "program", "source_file", "block", "statement_block", "class_definition"}:
            enclosing_scope = enclosing_scope.parent
        bindings = _bindings(unit, nodes)
        result["bindings"].extend(bindings)
        test_record = {"id": unit.id, "name": unit.name, "language": source.language,
                       "span": span(source, whole), "test_span": span(source, whole),
                       "definition_span": span(source, unit.node),
                       "enclosing_scope_span": span(source, enclosing_scope),
                       "insertion_after_byte": whole.end_byte,
                       "owner_kind": "module_script" if unit.node == source.root else "registered_test",
                       "emission_status": "wrapper_required" if unit.node == source.root else "clone_supported",
                       "body_span": span(source, unit.body), "parameters": functions[unit.id]["parameters"],
                       "parameter_rows": _compact(_unit_parameters(unit)), "support": _support(index, unit, flow),
                       "scope_bindings": sorted(_local_binders(source, unit.body) | set(unit.params)),
                       "execution_status": "unknown", "observation_ids": [], "call_ids": [],
                       "unknowns": ["fixtures_and_heap_effects_not_proved", "source_presence_is_not_execution"]}
        if source.root.has_error:
            test_record["unknowns"].append("source_parse_error")
        result["tests"].append(test_record)
        observations = []
        oracle_spans = []
        for assertion in flow.assertions:
            statement, observed, expected, predicate = _assertion_nodes(source, assertion, unit)
            if statement is None:
                statement = node_map.get((flow.nodes[assertion.node]["start_byte"], flow.nodes[assertion.node]["end_byte"]))
            if statement is None or observed is None:
                result["unknowns"].append({"test_id": unit.id, "reason": "assertion_source_span_not_recovered"})
                continue
            sliced = flow.slice([assertion.node])
            oracle_spans.extend(_oracle_value_spans(source, expected, flow, unit))
            oid = _id(unit.id, "observation", statement.start_byte, statement.end_byte)
            record = {"id": oid, "test_id": unit.id, "span": span(source, statement),
                      "test_span": span(source, whole), "predicate": predicate,
                      "assertion_span": span(source, statement), "kind": "assertion",
                      "observed": expression(source, observed), "expected": expression(source, expected),
                      "observed_binding": _binding_for(unit, observed, bindings),
                      "adapter": assertion.assertion_adapter, "incidental": assertion.incidental,
                      "contexts": _contexts(source, statement, unit.body), "source_call_ids": [],
                      "before_call_ids": [], "after_call_ids": [],
                      "oracle_status": "existing_assertion_unvalidated_for_new_relation",
                      "coverage_status": "static_observation_only"}
            observations.append((record, statement, observed, expected, sliced))
            result["observations"].append(record)
            test_record["observation_ids"].append(oid)
        for statement, observed, expected in _exception_observations(unit, nodes):
            oid = _id(unit.id, "exception", statement.start_byte, statement.end_byte)
            roots = [n["id"] for n in flow.nodes if observed.start_byte <= n["start_byte"] and n["end_byte"] <= observed.end_byte]
            record = {"id": oid, "test_id": unit.id, "span": span(source, statement),
                      "assertion_span": span(source, statement), "test_span": span(source, whole),
                      "kind": "assertion", "observation_type": "exception", "predicate": "raises",
                      "observed": expression(source, observed), "expected": expression(source, expected),
                      "observed_binding": _binding_for(unit, observed, bindings), "adapter": "pytest_raises",
                      "incidental": False, "contexts": _contexts(source, statement, unit.body),
                      "source_call_ids": [], "before_call_ids": [], "after_call_ids": [],
                      "oracle_status": "existing_assertion_unvalidated_for_new_relation", "coverage_status": "static_observation_only"}
            oracle_spans.extend(_oracle_value_spans(source, expected, flow, unit))
            observations.append((record, statement, observed, expected, flow.slice(roots)))
            result["observations"].append(record)
            test_record["observation_ids"].append(oid)
        for statement in (n for n in nodes if n.type in CALLS and source.language == "python"
                          and source.text(call_parts(n)[0]) == "print"):
            _, args = call_parts(statement)
            if not args:
                continue
            observed = args[0] if len(args) == 1 else statement
            oid = _id(unit.id, "output", statement.start_byte, statement.end_byte)
            record = {"id": oid, "test_id": unit.id, "span": span(source, statement),
                      "test_span": span(source, whole), "assertion_span": None, "predicate": None,
                      "kind": "output", "observed": expression(source, observed), "expected": None,
                      "observed_binding": _binding_for(unit, observed, bindings), "adapter": "python_print",
                      "incidental": False, "contexts": _contexts(source, statement, unit.body),
                      "source_call_ids": [], "before_call_ids": [], "after_call_ids": [],
                      "oracle_status": "unchecked_output_no_assertion", "coverage_status": "static_observation_only"}
            roots = [item["id"] for item in flow.nodes if item["start_byte"] == statement.start_byte and item["end_byte"] == statement.end_byte]
            observations.append((record, statement, observed, None, flow.slice(roots)))
            result["observations"].append(record)
            test_record["observation_ids"].append(oid)
        calls = []
        diagnostic_spans = [n for n in nodes if n.type in CALLS and _diagnostic_call(unit, n)]
        input_slots = collections.defaultdict(list)
        flow_calls = {(flow.nodes[c.node]["start_byte"], flow.nodes[c.node]["end_byte"]): c for c in flow.calls}
        for node in (n for n in nodes if n.type in CALLS):
            fn, _ = call_parts(node)
            fcall = flow_calls.get((node.start_byte, node.end_byte))
            receiver = attr_parts(fn)[0] if fn is not None and fn.type in ATTRS else None
            target_pairs = _resolved_targets(index, unit, node, fcall)
            targets = [{"function_id": uid, "reason": reason, "resolved": reason in TRUSTED_RESOLUTIONS}
                       for uid, reason in target_pairs]
            arguments = _arguments(source, node)
            cid = _id(unit.id, "call", node.start_byte, node.end_byte)
            record = {"id": cid, "test_id": unit.id, "span": span(source, node), "callee": source.text(fn),
                      "callee_identity": _call_identity(index, unit, node, fcall, target_pairs),
                      "receiver": expression(source, receiver), "receiver_binding": _binding_for(unit, receiver, bindings),
                      "arguments": arguments, "targets": targets,
                      "argument_bindings": _bind_arguments(unit, arguments, targets, functions),
                      "contexts": _contexts(source, node, unit.body),
                      "role": ("diagnostic" if node in diagnostic_spans or _assertion_message(unit, node)
                               else "assertion_context" if any(r.get("observation_type") == "exception"
                                     and statement.start_byte <= node.start_byte and node.end_byte <= child(statement, "body").start_byte
                                     for r, statement, _, _, _ in observations)
                               else next((r["kind"] for r, statement, _, _, _ in observations if statement == node), "operation")),
                      "observation_ids": []}
            for argument in arguments:
                argument["structure"] = _structure(source, node_map.get((argument["span"]["start_byte"], argument["span"]["end_byte"])))
                argument["binding"] = _binding_for(unit, node_map.get((argument["span"]["start_byte"], argument["span"]["end_byte"])), bindings)
            if fcall is not None:
                position = iter(fcall.args)
                for argument in arguments:
                    value = fcall.keywords.get(argument["keyword"]) if argument["keyword"] is not None else next(position, None)
                    if value is None:
                        continue
                    for nid in flow.slice([value.id]):
                        item = flow.nodes[nid]
                        if item["kind"] in {"join", "may_effect", "unknown", "parameter", "receiver"}:
                            continue
                        input_slots[item["start_byte"], item["end_byte"]].append({"call_id": cid, "slot": argument["slot"],
                                                                                "keyword": argument["keyword"]})
            calls.append((record, node))
            result["calls"].append(record)
            test_record["call_ids"].append(cid)
            for observation, statement, observed, expected, sliced in observations:
                if fcall is not None and fcall.node in sliced:
                    observation["source_call_ids"].append(cid)
                    record["observation_ids"].append(observation["id"])
                if node.end_byte <= statement.start_byte:
                    observation["before_call_ids"].append(cid)
                elif node.start_byte >= statement.end_byte:
                    observation["after_call_ids"].append(cid)
        # Calls are events with lexical positions, not an invented total runtime order.
        events = [(n.start_byte, n.end_byte, "call", r["id"], n) for r, n in calls]
        events += [(n.start_byte, n.end_byte, "observation", r["id"], n) for r, n, _, _, _ in observations]
        for ordinal, (_, _, kind, ref, node) in enumerate(sorted(events, key=lambda e: e[:4])):
            result["events"].append({"id": _id(unit.id, "event", kind, ref), "test_id": unit.id,
                                     "kind": kind, "ref_id": ref, "lexical_index": ordinal,
                                     "span": span(source, node), "contexts": _contexts(source, node, unit.body),
                                     "ordering_status": "lexical_only_not_runtime_happens_before"})
        value_nodes = {(n.start_byte, n.end_byte): n for n in nodes if n.type in LITERALS | CONTAINERS}
        for call, _ in calls:
            for argument in call["arguments"]:
                key = (argument["span"]["start_byte"], argument["span"]["end_byte"])
                if key in node_map:
                    value_nodes[key] = node_map[key]
        for key, node in sorted(value_nodes.items()):
            record = expression(source, node)
            expected_in = [r["id"] for r, _, _, expected, _ in observations if _contains(expected, node)]
            observed_in = [r["id"] for r, _, observed, _, _ in observations if _contains(observed, node)]
            argument_slots = [{"call_id": r["id"], "slot": a["slot"], "keyword": a["keyword"]}
                              for r, _ in calls for a in r["arguments"]
                              if a["span"]["start_byte"] <= node.start_byte and node.end_byte <= a["span"]["end_byte"]]
            record.update({"id": _id(unit.id, "value", *key), "test_id": unit.id,
                           "expected_in": expected_in, "observed_in": observed_in, "argument_slots": argument_slots,
                           "input_slots": input_slots[key],
                           "oracle_dependency": any(s["start_byte"] <= node.start_byte and node.end_byte <= s["end_byte"]
                                                    or node.start_byte <= s["start_byte"] and s["end_byte"] <= node.end_byte
                                                    for s in oracle_spans),
                           "role": "expected" if expected_in else "observed" if observed_in else "input" if argument_slots else "setup",
                           "structure": _structure(source, node)})
            if _assertion_message(unit, node) or any(_contains(diagnostic, node) for diagnostic in diagnostic_spans):
                record["role"] = "diagnostic"
                record["diagnostic"] = True
            result["values"].append(record)
        # Start from every setup/action call, not solely the candidate's current
        # value slice: deleted effects would otherwise exclude precisely the gap.
        queue = collections.deque([(unit.id, 0, ())])
        seen = set()
        while queue:
            uid, depth, path = queue.popleft()
            if uid in seen:
                continue
            seen.add(uid)
            if depth >= max_production_depth:
                continue
            current_flow = flow if uid == unit.id else index.flow(uid)
            current_unit = index.units[uid]
            call_sites = {(current_flow.nodes[c.node]["start_byte"], current_flow.nodes[c.node]["end_byte"]): c.targets
                          for c in current_flow.calls}
            graph_calls = {(current_flow.nodes[c.node]["start_byte"], current_flow.nodes[c.node]["end_byte"]): c
                           for c in current_flow.calls}
            for call_node in (n for n in (nodes if uid == unit.id else _owned_walk(current_unit.body)) if n.type in CALLS):
                key = (call_node.start_byte, call_node.end_byte)
                call_sites[key] = _resolved_targets(index, current_unit, call_node, graph_calls.get(key))
            for (call_start, call_end), targets in sorted(call_sites.items()):
                for target, reason in targets:
                    target_unit = index.units[target]
                    if target_unit.test or target in seen:
                        continue
                    edge = {"caller_id": uid, "callee_id": target, "reason": reason,
                            "call_span": {"path": index.units[uid].source.path,
                                          "start_byte": call_start, "end_byte": call_end}}
                    if target not in reached and len(reached) >= max_production_units:
                        continue
                    reached.add(target)
                    production_reasons[target].append({"kind": "test_call_reachability", "test_id": unit.id,
                                                        "depth": depth + 1, "path": list(path + (edge,)),
                                                        "resolved": all(e["reason"] in TRUSTED_RESOLUTIONS for e in path + (edge,))})
                    queue.append((target, depth + 1, path + (edge,)))
    relevant = sorted(production_reasons, key=lambda uid: (index.units[uid].source.path, index.units[uid].node.start_byte))
    used_function_ids = {u.id for u in tests} | set(relevant)
    used_function_ids.update(t["function_id"] for c in result["calls"] for t in c["targets"])
    result["functions"] = [functions[uid] for uid in sorted(used_function_ids)]
    for uid in relevant:
        unit = index.units[uid]
        source = unit.source
        result["field_defaults"].extend(_field_defaults(unit, functions[uid]))
        production_flow = index.flow(uid)
        flow_calls = {(production_flow.nodes[c.node]["start_byte"], production_flow.nodes[c.node]["end_byte"]): c for c in production_flow.calls}
        for node in (n for n in _owned_walk(unit.body) if n.type in CALLS):
            fn, _ = call_parts(node)
            call = flow_calls.get((node.start_byte, node.end_byte))
            arguments = _arguments(source, node)
            targets = [{"function_id": target, "reason": reason, "resolved": reason in TRUSTED_RESOLUTIONS}
                       for target, reason in _resolved_targets(index, unit, node, call)]
            result["production_calls"].append({"id": _id(uid, "call", node.start_byte, node.end_byte),
                                                "function_id": uid, "test_id": None, "span": span(source, node),
                                                "callee": source.text(fn), "arguments": arguments, "targets": targets,
                                                "argument_bindings": _bind_arguments(unit, arguments, targets, functions),
                                                "contexts": _contexts(source, node, unit.body)})
        parameter_names = {p["name"] for p in functions[uid]["parameters"] if p["name"] is not None}
        for node in _owned_walk(unit.body):
            condition = child(node, "condition") if node.type in CONTROL_NODES else None
            if condition is not None:
                result["guards"].append({"id": _id(uid, "guard", condition.start_byte), "function_id": uid,
                                          "span": span(source, node), "condition": expression(source, condition),
                                          "contexts": _contexts(source, node, unit.body),
                                          "relevance": production_reasons[uid]})
            for i, (left, operator, right) in enumerate(_comparison_parts(source, node)):
                contexts = _contexts(source, node, unit.body)
                guard = next((c for c in reversed(contexts) if c["condition"] is not None), None)
                left_record, right_record = expression(source, left), expression(source, right)
                result["comparisons"].append({"id": _id(uid, "comparison", node.start_byte, i),
                                               "function_id": uid, "span": span(source, node), "operator": operator,
                                               "left": left_record, "right": right_record,
                                               "left_ir": _expression_ir(source, left), "right_ir": _expression_ir(source, right),
                                               "parameter_names": sorted(parameter_names & set(left_record["free_identifiers"] + right_record["free_identifiers"])),
                                               "guard_span": guard["span"] if guard else None, "contexts": contexts,
                                               "relevance": production_reasons[uid], "semantic_status": "syntactic_comparison"})
    _propagate_field_defaults(result["field_defaults"], result["calls"] + result["production_calls"], functions, max_production_depth)
    result["stats"] = {"available_tests": available_tests, "tests": len(result["tests"]),
                       "observations": len(result["observations"]), "calls": len(result["calls"]),
                       "values": len(result["values"]), "comparisons": len(result["comparisons"]),
                       "test_budget_exhausted": available_tests > len(tests),
                       "production_units": len(relevant), "production_budget_reached": len(reached) >= max_production_units,
                       "production_depth": max_production_depth, "parse_errors": index.parse_errors}
    return result


def to_emitter_corpus(frontend: dict) -> dict:
    """Compact adapter for the existing emitter and syntax transform interface.

    Module scripts remain marked ``wrapper_required``. They must be wrapped by
    a runner-aware caller before passing candidates to the cloning emitter.
    No AST trees or repeated flow graphs are reconstructed by this adapter.
    """
    languages = {s["language"] for s in frontend["sources"].values()}
    corpus = {"schema_version": "relational_emitter_corpus.v1", "language": next(iter(languages)) if len(languages) == 1 else "mixed",
              "sources": frontend["sources"], "tests": {}, "capsules": [], "donors": [],
              "coverage": frontend["stats"]}
    for test in frontend["tests"]:
        record = dict(test)
        record["parameters"] = [p["name"] for p in test["parameters"] if p["name"] is not None]
        record["retrieval_rank"] = None
        record["parameterization_status"] = "expanded_literal_rows" if record["parameter_rows"] else "none_detected"
        corpus["tests"][test["id"]] = record
    calls = {call["id"]: call for call in frontend["calls"]}
    def port(item):
        call = calls[item["call_id"]]
        arg = next(a for a in call["arguments"] if a["slot"] == item["slot"])
        return {"callee": call["callee"], "callee_identity": call["callee_identity"],
                "argument_slot": arg["slot"], "keyword": arg["keyword"],
                "call_span": call["span"], "argument_span": arg["argument_span"],
                "dependence": "local_may_value_flow"}
    for observation in frontend["observations"]:
        if observation["kind"] != "assertion":
            continue
        test = corpus["tests"][observation["test_id"]]
        record = dict(observation)
        record.update({"assertion": source_text(frontend, observation["assertion_span"]),
                       "language": test["language"], "retrieval_rank": None,
                       "calls": [calls[cid] for cid in observation["source_call_ids"]],
                       "bindings": {}, "expected_atoms": [], "helper_assertions": [],
                       "parameter_rows": test["parameter_rows"], "unknowns": ["static_only_no_oracle_transfer_proof"]})
        corpus["capsules"].append(record)
    for value in frontend["values"]:
        if value.get("diagnostic"):
            continue
        direct_ports = [port(p) for p in value["argument_slots"] if calls[p["call_id"]]["role"] == "operation"]
        record = dict(value)
        record.update({"call_context": min(direct_ports, key=lambda p: p["call_span"]["end_byte"] - p["call_span"]["start_byte"]) if direct_ports else None,
                       "input_slots": [port(p) for p in value["input_slots"] if calls[p["call_id"]]["role"] == "operation"],
                       "retrieval_rank": None, "observation_dependency": bool(value["observed_in"]),
                       "dependency_role": "expected_only" if value["oracle_dependency"] else "observed_only" if value["observed_in"] else "neither",
                       "role": "expected" if value["oracle_dependency"] else "test_expression", "context_parent": None})
        corpus["donors"].append(record)
    return corpus


def load_frontend(repository: str | Path, language: str, *, trajectory: dict | None = None, **kwargs) -> dict:
    """Load repository syntax and optional recovered historical source snippets."""
    return extract_frontend(load_sources(Path(repository), language, trajectory), **kwargs)


def source_text(frontend: dict, source_span: dict) -> str:
    """Recover exactly the original UTF-8 source bytes for an emitted span."""
    data = frontend["sources"][source_span["path"]]["code"].encode()
    return data[source_span["start_byte"]:source_span["end_byte"]].decode()
