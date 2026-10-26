"""Small source summaries, built on the repository's Tree-sitter frontend.

No subject code is imported. Resource identities and field projections are
static hypotheses; they are not runtime alias or test-adequacy proofs.
"""
from __future__ import annotations

import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from anchor_retrieval.syntax import (
    ATTRS, CALLS, FUNCTIONS, SKIP, Source, attr_parts, call_parts, child,
    diff_lines, is_test_path, literal, units, walk,
)
from relational_gap.frontend import extract_frontend

EXTENSIONS = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".go": "go"}
NESTED = FUNCTIONS | {"arrow_function", "function_expression", "func_literal", "lambda"}
ASSIGNMENTS = {"assignment", "assignment_expression", "augmented_assignment", "augmented_assignment_expression",
               "assignment_statement", "short_var_declaration", "variable_declarator"}
READ_METHODS = {"get", "has", "values", "keys", "items", "entries"}
WRITE_METHODS = {"set", "add", "append", "push", "update", "insert"}
REMOVE_METHODS = {"clear", "delete", "pop", "remove", "discard"}


def stable_id(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:20]


def span(source, node):
    return {"path": source.path, "line": node.start_point.row + 1,
            "end_line": node.end_point.row + 1, "start_byte": node.start_byte,
            "end_byte": node.end_byte}


def text_at(sources, location):
    return sources[location["path"]].data[location["start_byte"]:location["end_byte"]].decode()


def owned_walk(node):
    yield node
    for item in node.named_children:
        if item.type not in NESTED:
            yield from owned_walk(item)


def load_repository(root):
    root = Path(root).resolve()
    result, skipped = [], []
    # Prune directories before traversal. Do not follow links into other trees.
    import os
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith(".")
                         and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix not in EXTENSIONS:
                continue
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                skipped.append({"path": relative, "reason": "symbolic_link"})
                continue
            try:
                code = path.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                skipped.append({"path": relative, "reason": "unreadable_source"})
                continue
            result.append(Source(relative, code, EXTENSIONS[path.suffix]))
    return sorted(result, key=lambda s: s.path), skipped


def _access(source, node):
    """Return the written access path, without claiming heap identity."""
    if node is None:
        return None
    if node.type in {"identifier", "this", "self"}:
        return source.text(node)
    if node.type in ATTRS:
        obj, field = attr_parts(node)
        base = _access(source, obj)
        return base + "." + source.text(field) if base and field else None
    if node.type in {"subscript", "subscript_expression", "index_expression"}:
        return _access(source, child(node, "value", "object", "operand"))
    if node.type in {"parenthesized_expression", "await", "await_expression"} and node.named_children:
        return _access(source, node.named_children[-1])
    return None


def _assignment(node):
    if node.type not in ASSIGNMENTS:
        return None, None
    return child(node, "left", "name"), child(node, "right", "value")


def _literal_node(source, node):
    if node is None:
        return False, None
    try:
        value = literal(source.text(node))
        json.dumps(value)
        return True, value
    except (ValueError, TypeError):
        pass
    if node.type in {"object", "dictionary"}:
        result = {}
        for pair in node.named_children:
            if pair.type not in {"pair", "pair_pattern"}:
                return False, None
            key, value = child(pair, "key"), child(pair, "value")
            ok, decoded = _literal_node(source, value)
            if key is None or not ok:
                return False, None
            raw = source.text(key)
            try:
                raw = literal(raw)
            except ValueError:
                if key.type not in {"property_identifier", "identifier"}:
                    return False, None
            if not isinstance(raw, str):
                return False, None
            result[raw] = decoded
        return True, result
    if node.type in {"array", "list", "tuple"}:
        values = [_literal_node(source, n) for n in node.named_children]
        if all(ok for ok, _ in values):
            return True, [v for _, v in values]
    return False, None


def _canonical_access(function, access):
    if not access:
        return None
    root, *fields = access.split(".")
    parameters = [p["name"] for p in function.get("parameters", [])]
    receiver = function.get("receiver") or {}
    receiver_name = receiver.get("name") if isinstance(receiver, dict) else None
    if root in {"self", "this", receiver_name} and function.get("owner") and fields:
        return function["span"]["path"] + "::" + function["owner"] + "." + ".".join(fields)
    if root in parameters:
        return "parameter::" + function["id"] + "::" + access
    # Globals are scoped to a source module. Local variables are removed below.
    return function["span"]["path"] + "::" + access


def _body_node(source, function):
    location = function["span"]
    node = source.root.named_descendant_for_byte_range(location["start_byte"], location["end_byte"] - 1)
    body = child(node, "body")
    if body is not None:
        return body
    location = function["body_span"]
    return source.root.named_descendant_for_byte_range(location["start_byte"], max(location["start_byte"], location["end_byte"] - 1))


def summarize_function(source, function):
    body = _body_node(source, function)
    nodes = list(owned_walk(body))
    parameters = {p["name"] for p in function.get("parameters", []) if p.get("name")}
    locals_ = {source.text(lhs) for n in nodes for lhs, rhs in [_assignment(n)]
               if lhs is not None and lhs.type == "identifier"}
    fields = defaultdict(set)
    effects = []
    returns = set()
    returns_value = body.type not in {"block", "statement_block", "statement_list"}

    def add_effect(access, mode, node, key=None, assumption="direct_access"):
        if not access or access.split(".")[0] in locals_:
            return
        resource = _canonical_access(function, access)
        if resource:
            effects.append({"resource": resource, "access": access, "mode": mode,
                            "key": key, "span": span(source, node), "assumption": assumption,
                            "parameter": access.split(".")[0] if resource.startswith("parameter::") else None})

    for node in nodes:
        if node.type in ATTRS:
            obj, field = attr_parts(node)
            root = _access(source, obj)
            if root and root.split(".")[0] in parameters and field:
                # A method name is not a projected data field.
                if not (node.parent is not None and node.parent.type in CALLS
                        and child(node.parent, "function") == node):
                    parts = root.split(".")
                    fields[parts[0]].add(".".join(parts[1:] + [source.text(field)]))
            parent = node.parent
            if parent is not None and parent.type in ATTRS:
                continue
            if parent is not None and parent.type in CALLS and child(parent, "function") == node:
                continue
            lhs, _ = _assignment(parent) if parent is not None else (None, None)
            mode = "write" if lhs == node else "read"
            if parent is not None and parent.type in {"subscript", "subscript_expression", "index_expression"}:
                continue  # The complete indexed access is recorded below.
            add_effect(_access(source, node), mode, node)
        if node.type in {"subscript", "subscript_expression", "index_expression"}:
            obj = child(node, "value", "object", "operand")
            index = child(node, "subscript", "index")
            parent = node.parent
            lhs, _ = _assignment(parent) if parent is not None else (None, None)
            mode = "write" if lhs == node else "remove" if parent is not None and parent.type == "delete_statement" else "read"
            add_effect(_access(source, obj), mode, node, source.text(index) or None)
            if obj is not None and source.text(obj) in parameters and index is not None:
                ok, value = _literal_node(source, index)
                if ok and isinstance(value, str):
                    fields[source.text(obj)].add(value)
        if node.type in CALLS:
            fn, args = call_parts(node)
            if fn is not None and fn.type in ATTRS:
                obj, method = attr_parts(fn)
                name = source.text(method)
                mode = "read" if name in READ_METHODS else "write" if name in WRITE_METHODS else "remove" if name in REMOVE_METHODS else None
                if mode:
                    add_effect(_access(source, obj), mode, node, source.text(args[0]) if args and name != "clear" else None,
                               "container_method_name_requires_type_review")
        if node.type == "return_statement":
            returns_value |= bool(node.named_children) and source.text(node.named_children[0]) not in {"None", "null", "undefined"}
            for value in node.named_children:
                if value.type in {"dictionary", "object"}:
                    for pair in value.named_children:
                        key = child(pair, "key")
                        if key is not None:
                            raw = source.text(key)
                            try:
                                raw = literal(raw)
                            except ValueError:
                                pass
                            if isinstance(raw, str):
                                returns.add(raw)
    unique = {stable_id(e["resource"], e["mode"], e["span"]): e for e in effects}
    return {"function_id": function["id"], "parameter_fields": {k: sorted(v) for k, v in sorted(fields.items())},
            "effects": list(unique.values()), "return_fields": sorted(returns), "returns_value": returns_value}


def _result_binding(source, call, test):
    node = source.root.named_descendant_for_byte_range(call["span"]["start_byte"], call["span"]["end_byte"] - 1)
    parent = node.parent
    while parent is not None and parent.type in {"await", "await_expression", "parenthesized_expression"}:
        node, parent = parent, parent.parent
    lhs, rhs = _assignment(parent) if parent is not None else (None, None)
    if lhs is None or rhs is None or lhs.type != "identifier":
        return None
    return {"name": source.text(lhs), "definition_end": parent.end_byte,
            "awaited": any(n.type in {"await", "await_expression"} for n in walk(rhs))}


def _direct_observations(source, call, test, observations):
    """Version-sensitive local result use. This is deliberately not a heap slice."""
    direct, fields, whole_fields = [], set(), set()
    binding = _result_binding(source, call, test)
    for observation in observations:
        if observation["kind"] != "assertion":
            continue
        loc = observation["span"]
        expected = observation.get("expected") or {}
        expected_loc = expected.get("span")
        whole_keys = set()
        if expected_loc and observation.get("predicate") in {"==", "===", "toEqual", "toStrictEqual"}:
            node = source.root.named_descendant_for_byte_range(expected_loc["start_byte"], expected_loc["end_byte"] - 1)
            ok, value = _literal_node(source, node)
            if ok and isinstance(value, dict):
                whole_keys = set(value)
        if loc["start_byte"] <= call["span"]["start_byte"] and call["span"]["end_byte"] <= loc["end_byte"]:
            direct.append(observation["id"])
            observed = observation.get("observed") or {}
            if observed.get("span") == call["span"]:
                whole_fields.update(whole_keys)
            continue
        if not binding or loc["start_byte"] < binding["definition_end"]:
            continue
        name = binding["name"]
        boundary = source.root.named_descendant_for_byte_range(test["body_span"]["start_byte"], test["body_span"]["end_byte"] - 1)
        killed = any(lhs is not None and source.text(lhs) == name
                     and binding["definition_end"] <= n.start_byte < loc["start_byte"]
                     for n in owned_walk(boundary) for lhs, _ in [_assignment(n)])
        if killed:
            continue
        observed = observation.get("observed") or {}
        # Expected values can contain arbitrary setup names; only examine the observed expression.
        expr = observed.get("text", "")
        if name in observed.get("free_identifiers", []):
            direct.append(observation["id"])
            expr_span = observed["span"]
            expr_node = source.root.named_descendant_for_byte_range(expr_span["start_byte"], expr_span["end_byte"] - 1)
            for part in owned_walk(expr_node):
                if part.type in ATTRS:
                    obj, field = attr_parts(part)
                    if source.text(obj) == name:
                        fields.add(source.text(field))
                elif part.type in {"subscript", "subscript_expression", "index_expression"}:
                    obj = child(part, "value", "object", "operand")
                    key = child(part, "subscript", "index")
                    ok, field = _literal_node(source, key)
                    if source.text(obj) == name and ok and isinstance(field, str):
                        fields.add(field)
            if expr == name:
                whole_fields.update(whole_keys)
    return {"observation_ids": direct, "fields": sorted(fields), "whole_fields": sorted(whole_fields), "result_binding": binding}


def _literal_argument(frontend, call, argument, sources):
    source = sources[call["span"]["path"]]
    loc = argument["span"]
    node = source.root.named_descendant_for_byte_range(loc["start_byte"], loc["end_byte"] - 1)
    ok, value = _literal_node(source, node)
    if ok:
        return {"known": True, "value": value}
    binding = argument.get("binding") or {}
    record = next((b for b in frontend["bindings"] if b["id"] == binding.get("binding_id")), None)
    if record and not record.get("contexts"):
        loc = record["value"]["span"]
        node = source.root.named_descendant_for_byte_range(loc["start_byte"], loc["end_byte"] - 1)
        ok, value = _literal_node(source, node)
        if ok:
            return {"known": True, "value": value}
    return {"known": False}


def build_program(sources, patch, *, max_depth=6):
    sources = {s.path: s for s in sources}
    frontend = extract_frontend(sources.values(), patch=patch, max_production_depth=max_depth,
                                max_production_units=100000)
    functions = {f["id"]: f for f in frontend["functions"]}
    # Include otherwise-unreached state readers/writers, not just callees of selected tests.
    for source in sources.values():
        if source.origin != "repository":
            continue
        for unit in units(source)[0]:
            if unit.id not in functions and not unit.test and not is_test_path(source.path):
                functions[unit.id] = {"id": unit.id, "name": unit.name, "owner": unit.owner,
                    "span": span(source, unit.node), "body_span": span(source, unit.body),
                    "parameters": [{"name": p, "index": i} for i, p in enumerate(unit.params)],
                    "production": True, "test": False}
    _resolve_go_package_calls(frontend, functions, sources)
    changed_lines = diff_lines(patch)
    changed = {fid for fid, f in functions.items() if f.get("production") and
               any(f["span"]["line"] <= line <= f["span"]["end_line"]
                   for line in changed_lines.get(f["span"]["path"], ())) }
    summaries = {fid: summarize_function(sources[f["span"]["path"]], f)
                 for fid, f in functions.items() if f.get("production")}
    tests = {t["id"]: t for t in frontend["tests"]}
    observations = defaultdict(list)
    for row in frontend["observations"]:
        observations[row["test_id"]].append(row)
    calls = []
    for original in frontend["calls"]:
        call = dict(original)
        call["targets"] = [t["function_id"] for t in original["targets"] if t.get("resolved")]
        call["literal_arguments"] = [_literal_argument(frontend, call, a, sources) for a in call["arguments"]]
        call["direct_observation"] = _direct_observations(sources[call["span"]["path"]], call, tests[call["test_id"]], observations[call["test_id"]])
        calls.append(call)
    edges = []
    for call in frontend["production_calls"]:
        for target in call["targets"]:
            if target.get("resolved"):
                edges.append({"from": call["function_id"], "to": target["function_id"],
                              "kind": "call", "span": call["span"]})
    # Carry field uses through directly bound formals. Recursion converges for
    # these unchanged access paths; arbitrary heap paths are outside this model.
    for _ in range(max_depth):
        updated = False
        for call in frontend["production_calls"]:
            caller = summaries.get(call["function_id"])
            if caller is None:
                continue
            formal_names = {p["name"] for p in functions[call["function_id"]]["parameters"]}
            for binding in call["argument_bindings"]:
                target = binding["function_id"]
                if not any(t["function_id"] == target and t.get("resolved") for t in call["targets"]):
                    continue
                argument = call["arguments"][binding["slot"]]
                if argument["kind"] != "identifier" or argument["text"] not in formal_names:
                    continue
                fields = summaries.get(target, {}).get("parameter_fields", {}).get(binding["parameter"], [])
                existing = set(caller["parameter_fields"].get(argument["text"], []))
                merged = existing | set(fields)
                if merged != existing:
                    caller["parameter_fields"][argument["text"]] = sorted(merged)
                    updated = True
        if not updated:
            break
    edges.extend(_value_flow_edges(frontend, functions, sources))
    program = {"sources": sources, "frontend": frontend, "functions": functions,
            "summaries": summaries, "tests": tests, "calls": calls, "edges": edges,
            "changed": changed, "changed_paths": sorted(changed_lines),
            "changed_test_ids": {tid for tid, test in tests.items() if any(test["span"]["line"] <= line <= test["span"]["end_line"]
                                  for line in changed_lines.get(test["span"]["path"], ()))},
            "max_depth": max_depth}
    from .relations import build_relations
    from .scopes import recover_callable_entries
    program["behavior_graph"] = build_relations(program, patch)
    recover_callable_entries(program)
    return program


def _resolve_go_package_calls(frontend, functions, sources):
    """Resolve bare, unshadowed Go functions in the same directory/package."""
    def package(source):
        clause = next((n for n in source.root.named_children if n.type == "package_clause"), None)
        return source.text(clause)
    symbols = defaultdict(list)
    for fid, function in functions.items():
        source = sources[function["span"]["path"]]
        if source.language == "go" and function.get("production") and not function.get("owner"):
            symbols[(str(Path(source.path).parent), package(source), function["name"])].append(fid)
    for call in frontend["calls"] + frontend["production_calls"]:
        source = sources[call["span"]["path"]]
        if source.language != "go" or not re.fullmatch(r"[A-Za-z_]\w*", call["callee"]):
            continue
        caller = functions[call.get("function_id") or call["test_id"]]
        name = call["callee"]
        body = _body_node(source, caller)
        shadowed = name in {p["name"] for p in caller["parameters"]}
        for node in owned_walk(body):
            if node.start_byte >= call["span"]["start_byte"]:
                continue
            lhs, _ = _assignment(node)
            if lhs is not None and name in {source.text(n) for n in walk(lhs) if n.type == "identifier"}:
                shadowed = True
            if node.type == "var_spec" and name in {source.text(n) for n in node.children_by_field_name("name")}:
                shadowed = True
        matches = symbols[(str(Path(source.path).parent), package(source), name)]
        if not shadowed and len(matches) == 1:
            fid = matches[0]
            call["targets"] = [{"function_id": fid, "reason": "same_go_package_unshadowed_function", "resolved": True}]
            call["argument_bindings"] = [{"slot": i, "parameter": p["name"], "parameter_index": i,
                                           "function_id": fid, "binding_status": "direct_actual_formal"}
                                          for i, p in enumerate(functions[fid]["parameters"]) if i < len(call["arguments"])]


def _value_flow_edges(frontend, functions, sources):
    """Direct result-to-argument handoffs, including one local assignment."""
    result = []
    by_function = defaultdict(list)
    for call in frontend["production_calls"]:
        by_function[call["function_id"]].append(call)
    for caller, calls in by_function.items():
        source = sources[functions[caller]["span"]["path"]]
        loc = functions[caller]["body_span"]
        body = source.root.named_descendant_for_byte_range(loc["start_byte"], loc["end_byte"] - 1)
        assignments = [(n, lhs, rhs) for n in owned_walk(body) for lhs, rhs in [_assignment(n)] if lhs is not None and rhs is not None]
        for consumer in calls:
            for argument in consumer["arguments"]:
                loc = argument["span"]
                if argument["kind"] == "identifier":
                    definitions = [(n, rhs) for n, lhs, rhs in assignments if source.text(lhs) == argument["text"] and n.end_byte <= loc["start_byte"]]
                    if not definitions:
                        continue
                    _, rhs = max(definitions, key=lambda pair: pair[0].end_byte)
                    loc = span(source, rhs)
                producers = [c for c in calls if c["span"]["start_byte"] == loc["start_byte"] and c["span"]["end_byte"] == loc["end_byte"]]
                for producer in producers:
                    for a in producer["targets"]:
                        for b in consumer["targets"]:
                            if a.get("resolved") and b.get("resolved") and a["function_id"] != b["function_id"]:
                                result.append({"from": a["function_id"], "to": b["function_id"], "kind": "value_flow",
                                               "caller": caller, "slot": argument["slot"], "span": consumer["span"],
                                               "producer_span": producer["span"]})
    return result


def reachable(program, start):
    edges = defaultdict(set)
    for edge in program["edges"]:
        if edge["kind"] == "call":
            edges[edge["from"]].add(edge["to"])
    seen, pending = set(), list(start)
    while pending:
        item = pending.pop()
        if item in seen:
            continue
        seen.add(item)
        pending.extend(edges[item] - seen)
    return seen


def evaluate_condition(expression, values):
    """Evaluate only literals, bound formals, and basic predicates; never eval()."""
    expression = expression.replace("===", "==").replace("!==", "!=").replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"!(?!=)", " not ", expression).strip()
    expression = re.sub(r"\btrue\b", "True", expression)
    expression = re.sub(r"\bfalse\b", "False", expression)
    def visit(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Attribute):
            value = visit(node.value)
            if isinstance(value, dict) and node.attr in value:
                return value[node.attr]
            if node.attr == "length" and isinstance(value, (str, list)):
                return len(value)
        if isinstance(node, ast.Subscript):
            return visit(node.value)[visit(node.slice)]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len" and len(node.args) == 1 and not node.keywords:
            return len(visit(node.args[0]))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub)):
            value = visit(node.operand)
            return not value if isinstance(node.op, ast.Not) else -value
        if isinstance(node, ast.BoolOp):
            items = [bool(visit(v)) for v in node.values]
            return all(items) if isinstance(node.op, ast.And) else any(items)
        if isinstance(node, ast.Compare):
            left = visit(node.left)
            for op, right_node in zip(node.ops, node.comparators):
                right = visit(right_node)
                if isinstance(op, ast.Eq): answer = left == right
                elif isinstance(op, ast.NotEq): answer = left != right
                elif isinstance(op, ast.Lt): answer = left < right
                elif isinstance(op, ast.LtE): answer = left <= right
                elif isinstance(op, ast.Gt): answer = left > right
                elif isinstance(op, ast.GtE): answer = left >= right
                elif isinstance(op, ast.In): answer = left in right
                elif isinstance(op, ast.NotIn): answer = left not in right
                else: raise ValueError("unsupported_comparison")
                if not answer:
                    return False
                left = right
            return True
        raise ValueError("unsupported_expression")
    try:
        return {"known": True, "value": bool(visit(ast.parse(expression, mode="eval").body))}
    except (SyntaxError, ValueError, TypeError, KeyError, IndexError, OverflowError):
        return {"known": False}
