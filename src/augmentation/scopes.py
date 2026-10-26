"""Candidate-local test evidence. Unknown values are never covered cells.

Rows belong to individual entry invocations, not a union of separate tests.
Source checks, actual execution, assertion strength and object identity remain
separate. This module does not certify a requirement or a test oracle.
"""
from __future__ import annotations

from collections import defaultdict, deque
import re

from anchor_retrieval.syntax import CALLS, ATTRS, child, call_parts, attr_parts, walk
from .program import _assignment, _body_node, _literal_node, _literal_argument, stable_id, span, evaluate_condition
from .relations import unwrap, access, _resolve

UNDEFINED = {"$language_value": "undefined"}


def literal_value(source, node, values=None):
    node = unwrap(node)
    if node is None:
        return {"known": False}
    text = source.text(node)
    if text == "undefined" and source.language == "typescript":
        return {"known": True, "value": UNDEFINED}
    if node.type == "identifier" and text in (values or {}):
        return values[text]
    if node.type in {"object", "dictionary"}:
        result, unknown = {}, []
        for part in node.named_children:
            key, value = child(part, "key"), child(part, "value")
            if part.type == "shorthand_property_identifier":
                name = source.text(part)
                decoded = (values or {}).get(name, {"known": False})
            elif key is not None and value is not None:
                ok, name = _literal_node(source, key)
                if not ok and key.type in {"identifier", "property_identifier"}:
                    name, ok = source.text(key), True
                if not ok or not isinstance(name, str):
                    return {"known": False}
                decoded = literal_value(source, value, values)
            else:
                return {"known": False}
            if decoded.get("known"):
                result[name] = decoded["value"]
            else:
                unknown.append(name)
        return {"known": not unknown, "value": result, "present_fields": sorted(set(result) | set(unknown)), "unknown_fields": unknown, "closed_object": True}
    if node.type in {"array", "list", "tuple"}:
        parts = [literal_value(source, n, values) for n in node.named_children]
        if all(p.get("known") for p in parts):
            return {"known": True, "value": [p["value"] for p in parts]}
        return {"known": False, "length": len(parts)}
    ok, value = _literal_node(source, node)
    return {"known": True, "value": value} if ok else {"known": False}


def _at(source, loc):
    return source.root.named_descendant_for_byte_range(loc["start_byte"], max(loc["start_byte"], loc["end_byte"] - 1))


def _environment(program, call):
    source = program["sources"][call["span"]["path"]]
    bindings = program.get("_binding_records")
    if bindings is None:
        bindings = {b["id"]: b for b in program["frontend"]["bindings"]}
        program["_binding_records"] = bindings
    values = {}
    for argument in call["arguments"]:
        binding = argument.get("binding") or {}
        record = bindings.get(binding.get("binding_id"))
        if record and not record.get("contexts"):
            decoded = literal_value(source, _at(source, record["value"]["span"]), values)
            values[argument["text"]] = decoded
    return values


def recover_callable_entries(program):
    """Bind callable arguments of known assertion helpers without running them."""
    additions = []
    for call in list(program["calls"]):
        name = call["callee"].split(".")[-1]
        index = 2 if name in {"assertRaisesRegex", "assertRaisesRegexp"} else 1 if name in {"assertRaises", "raises"} else None
        if index is None or len(call["arguments"]) <= index:
            continue
        arg = call["arguments"][index]
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", arg["text"]):
            continue
        targets, reason = _resolve(program, call["test_id"], arg["text"], None)
        if not targets:
            continue
        args = [{**a, "slot": i} for i, a in enumerate(call["arguments"][index + 1:])]
        observations = [o["id"] for o in program["frontend"]["observations"] if o["test_id"] == call["test_id"]
                        and o["span"]["start_byte"] <= call["span"]["start_byte"] and call["span"]["end_byte"] <= o["span"]["end_byte"]]
        row = {**call, "id": "helper_" + stable_id(call["id"], targets), "callee": arg["text"], "targets": targets,
               "arguments": args, "argument_bindings": [], "callable_helper": call["callee"], "binding_evidence": reason,
               "direct_observation": {"observation_ids": observations, "fields": [], "whole_fields": [], "result_binding": None}}
        for target in targets:
            row["argument_bindings"].extend({"slot": i, "parameter": p["name"], "function_id": target}
                                            for i, p in enumerate(program["functions"][target]["parameters"]) if i < len(args))
        row["literal_arguments"] = [_literal_argument(program["frontend"], row, a, program["sources"]) for a in args]
        additions.append(row)
    program["calls"].extend(additions)
    return additions


def _parameter_defaults(program, fid):
    cache = program.setdefault("_parameter_default_cache", {})
    if fid in cache:
        return dict(cache[fid])
    fn = program["functions"][fid]
    source = program["sources"][fn["span"]["path"]]
    node = _at(source, fn["span"])
    parameters = child(node, "parameters")
    result = {}
    if parameters is not None:
        for item in parameters.named_children:
            name, value = child(item, "name", "pattern", "left"), child(item, "value", "right")
            if name is not None and value is not None and name.type == "identifier":
                result[source.text(name)] = literal_value(source, value)
    cache[fid] = result
    return dict(result)


def _read_path(values, expression):
    parts = expression.split(".")
    root = values.get(parts[0], {"known": False})
    if len(parts) == 1:
        return root
    if not root.get("known") and not root.get("closed_object"):
        return {"known": False}
    current = root.get("value")
    for index, part in enumerate(parts[1:]):
        if not isinstance(current, dict):
            return {"known": False}
        if index == 0 and part in root.get("unknown_fields", []):
            return {"known": False, "present": True}
        if part not in current:
            return {"known": False, "present": False}
        current = current[part]
    return {"known": True, "value": current, "present": True}


def _predicate(expression, values):
    bound = {k: v["value"] for k, v in values.items() if v.get("known")}
    bound.update(undefined=UNDEFINED, null=None, nil=None, NoneValue=None)
    return evaluate_condition(expression, bound)


def _value_from_text(program, fid, text, loc, values):
    if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", text):
        value = _read_path(values, text)
        if value.get("known") or value.get("closed_object"):
            return value
    source = program["sources"][program["functions"][fid]["span"]["path"]]
    return literal_value(source, _at(source, loc), values)


def _locals_before(program, graph, fid, until, values):
    values = dict(values)
    cache = graph.setdefault("_local_assignments", {})
    if fid not in cache:
        cache[fid] = sorted((graph["nodes"][i] for i in graph["by_function"].get(fid, []) if graph["nodes"][i]["kind"] == "assignment"),
                           key=lambda n: (n["span"]["end_byte"], n["span"]["start_byte"]))
    default_cache = graph.get("_defaults_by_op")
    if default_cache is None:
        default_cache = defaultdict(list)
        for default in graph["defaults"]:
            default_cache[default["operation"]].append(default)
        graph["_defaults_by_op"] = default_cache
    for node in cache[fid]:
        if node["kind"] != "assignment" or node["span"]["end_byte"] > until:
            continue
        conditional = node["conditions"]
        status = [_predicate(c["expression"], values) for c in conditional if c["value"] is not None]
        if any(s.get("known") and s["value"] != c["value"] for s, c in zip(status, [c for c in conditional if c["value"] is not None])):
            continue
        target = node.get("target")
        if target and "." not in target and "[" not in target:
            source = program["sources"][node["span"]["path"]]
            _, rhs = _assignment(_at(source, node["span"]))
            values[target] = literal_value(source, unwrap(rhs), values) if not conditional else {"known": False}
        for default in default_cache.get(node["id"], []):
            actual = _read_path(values, default["root"] + "." + default["field"])
            if actual.get("present") is False or actual.get("known") and actual["value"] == UNDEFINED:
                # These literals are data; no eval or subject imports.
                from anchor_retrieval.syntax import literal
                try:
                    values[default["local"]] = {"known": True, "value": literal(default["default"])}
                except ValueError:
                    values[default["local"]] = {"known": False}
            else:
                values[default["local"]] = actual
    return values


def dimension_value(dimension, values):
    kind = dimension["kind"]
    if kind == "predicate":
        return _predicate(dimension["expression"], values)
    actual = _read_path(values, dimension.get("access", ""))
    if kind == "presence":
        if "present" in actual:
            return {"known": True, "value": actual["present"]}
        return {"known": False}
    if kind == "value_category" and actual.get("known"):
        value = actual["value"]
        return {"known": True, "value": "undefined" if value == UNDEFINED else "null" if value is None else "ordinary"}
    return {"known": False}


def _exit_barriers(graph, fid, until, values):
    """Keep possible early exits separate from the input values of a call.

    This is not a CFG feasibility proof. Even a known exit guard does not prove
    that an exception escapes a surrounding handler. It does prevent claiming
    that a later source operation was checked just from the entry arguments.
    """
    cache = graph.setdefault("_exits_by_function", {})
    if fid not in cache:
        cache[fid] = [graph["nodes"][i] for i in graph["by_function"].get(fid, [])
                      if graph["nodes"][i].get("termination")]
    barriers = []
    for node in cache[fid]:
        if node["span"]["end_byte"] >= until:
            continue
        contexts = node["conditions"]
        if any(c["expression"] == "callback executes" for c in contexts):
            continue  # An asynchronous callback does not terminate its caller.
        answers = [(_predicate(c["expression"], values), c["value"]) for c in contexts if c["value"] is not None]
        if any(a.get("known") and a["value"] != required for a, required in answers):
            continue
        barriers.append({"expression": "possible earlier exit: " + node["code"][:180],
                         "value": None, "span": node["span"], "operation_id": node["id"]})
    return barriers


def _scope_rows(program, graph, function_ids, *, max_rows=120):
    wanted = set(function_ids)
    call_nodes = graph.get("_calls_by_function")
    if call_nodes is None:
        call_nodes, parents = defaultdict(list), defaultdict(set)
        for node in graph["nodes"].values():
            if node["kind"] == "call" and node.get("targets"):
                call_nodes[node["function_id"]].append(node)
                for target in node["targets"]:
                    parents[target].add(node["function_id"])
        graph["_calls_by_function"], graph["_call_parents"] = call_nodes, parents
    reaching, todo = set(wanted), list(wanted)
    for _ in range(program["max_depth"]):
        following = {parent for target in todo for parent in graph["_call_parents"].get(target, [])} - reaching
        reaching.update(following)
        todo = list(following)
    observations = {o["id"]: o for o in program["frontend"]["observations"]}
    relevant_calls = [c for c in program["calls"] if set(c["targets"]) & reaching]
    relevant_calls.sort(key=lambda c: (c["test_id"] not in program.get("changed_test_ids", set()),
                                       program["sources"][c["span"]["path"]].origin == "repository", c["id"]))
    # Keep the complete may-related inventory even when path/value expansion
    # stops. One ambiguous entry must not hide the other test definitions.
    rows, test_ids, explored = [], {c["test_id"] for c in relevant_calls}, 0
    local_truncation = False
    for call in relevant_calls:
        entry_rows = 0
        source = program["sources"][call["span"]["path"]]
        environment = _environment(program, call)
        actuals = [literal_value(source, _at(source, a["span"]), environment) for a in call["arguments"]]
        pending = deque()
        for fid in call["targets"]:
            if fid not in reaching:
                continue
            values = _parameter_defaults(program, fid)
            for binding in call["argument_bindings"]:
                if binding["function_id"] == fid and binding["slot"] < len(actuals) and isinstance(binding.get("parameter"), str):
                    values[binding["parameter"]] = actuals[binding["slot"]]
            pending.append((fid, values, [], set(), {}, []))
        visited = set()
        while pending:
            fid, values, path, seen, inherited, path_conditions = pending.popleft()
            if fid in seen or len(path) > program["max_depth"]:
                continue
            state = (fid, stable_id(values, path))
            if state in visited:
                continue
            visited.add(state)
            explored += 1
            inherited = {**inherited, fid: values}
            if fid in wanted:
                test_ids.add(call["test_id"])
                checks = []
                for oid in call["direct_observation"]["observation_ids"]:
                    observation = observations.get(oid)
                    if observation:
                        loc = observation["span"]
                        checks.append({"span": loc, "code": source.data[loc["start_byte"]:loc["end_byte"]].decode()[:1200],
                                       "predicate": observation.get("predicate"), "observed": (observation.get("observed") or {}).get("text"),
                                       "contexts": observation.get("contexts", [])})
                rows.append({"id": "scope_" + stable_id(call["id"], fid, path), "test_id": call["test_id"], "entry_call": call["id"],
                             "entry": call["callee"], "function_id": fid, "inputs": values, "input_contexts": inherited,
                             "operation_path": path, "assertions": checks,
                             "objects": [{"argument": a["text"], "binding": (a.get("binding") or {}).get("origin_binding_id") or (a.get("binding") or {}).get("binding_id")}
                                         for a in call["arguments"]],
                             "source_conditions": call.get("contexts", []) + path_conditions, "ordering": "source_order_only",
                             "execution": "unknown", "observation_relation": "entry_result_checked" if checks else "not_established"})
                entry_rows += 1
                if len(rows) >= max_rows:
                    return {"rows": rows, "test_ids": sorted(test_ids), "truncated": True, "explored_calls": explored,
                            "meaning": "Candidate-local source evidence; truncation and unknown values cannot establish absence."}
                if entry_rows >= 4:
                    local_truncation = True
                    break
            for node in call_nodes.get(fid, []):
                if not set(node["targets"]) & reaching:
                    continue
                local = _locals_before(program, graph, fid, node["span"]["start_byte"], values)
                conditions = [(_predicate(c["expression"], local), c["value"]) for c in node["conditions"] if c["value"] is not None]
                if any(answer.get("known") and answer["value"] != required for answer, required in conditions):
                    continue
                args = [_value_from_text(program, fid, text, loc, local) for text, loc in zip(node["arguments"], node["argument_spans"])]
                for target in node["targets"]:
                    if target not in reaching:
                        continue
                    bound = _parameter_defaults(program, target)
                    bound.update({p["name"]: args[i] for i, p in enumerate(program["functions"][target]["parameters"]) if i < len(args) and isinstance(p.get("name"), str)})
                    unknown_conditions = [c for c in node["conditions"] if c["value"] is None or not _predicate(c["expression"], local).get("known")]
                    if "requires_type_review" in node.get("resolution", ""):
                        unknown_conditions.append({"expression": "receiver type for " + node["callee"] + " is unresolved",
                                                   "value": None, "span": node["span"]})
                    barriers = _exit_barriers(graph, fid, node["span"]["start_byte"], local)
                    pending.append((target, bound, path + [node["id"]], seen | {fid}, inherited,
                                    path_conditions + unknown_conditions + barriers))
            if explored >= 12000:
                return {"rows": rows, "test_ids": sorted(test_ids), "truncated": True, "explored_calls": explored,
                        "meaning": "Source exploration bound reached; unexamined paths remain unknown."}
    return {"rows": rows, "test_ids": sorted(test_ids), "truncated": local_truncation, "explored_calls": explored,
            "meaning": "Per-entry source evidence. Rows from separate invocations are never joined into a covered combination."}


def test_scope(program, graph, function_ids, dimensions, *, max_rows=120):
    cache = program.setdefault("_scope_cache", {})
    key = (tuple(sorted(function_ids)), max_rows)
    if key not in cache:
        cache[key] = _scope_rows(program, graph, function_ids, max_rows=max_rows)
    base = cache[key]
    rows = []
    for original in base["rows"]:
        assessed = {}
        for dimension in dimensions:
            fid = dimension.get("function_id")
            values = original["input_contexts"].get(fid)
            if values is None:
                assessed[dimension["id"]] = {"known": False}
            else:
                local = _locals_before(program, graph, fid, dimension.get("span", {}).get("start_byte", 0), values)
                answer = dimension_value(dimension, local)
                barriers = _exit_barriers(graph, fid, dimension.get("span", {}).get("start_byte", 0), local)
                assessed[dimension["id"]] = {**answer, "control_barriers": barriers} if barriers else answer
        rows.append({k: v for k, v in original.items() if k != "input_contexts"} | {"conditions": assessed})
    return {**base, "rows": rows}
