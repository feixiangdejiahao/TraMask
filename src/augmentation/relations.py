"""Source-grounded condition/operation/observation relations.

This is a bounded may-analysis, not a feasibility or adequacy proof. In
particular, an exit that prevents an observation is retained as a relation.
No issue text, reference patch, benchmark outcome or case identifier is used.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
import re

from anchor_retrieval.syntax import ATTRS, CALLS, child, call_parts, attr_parts, walk, diff_lines
from .program import _assignment, _body_node, _literal_node, owned_walk, span, stable_id

INDEXES = {"subscript", "subscript_expression", "index_expression"}
LOOPS = {"for_statement", "for_in_statement", "while_statement"}
SPECIALS = {"undefined", "UndefinedValue", "nil", "null", "None"}


def behavior_walk(node):
    """Keep anonymous callback bodies, with their unknown phase in contexts."""
    yield node
    for item in node.named_children:
        if item.type not in {"function_definition", "function_declaration", "method_declaration", "method_definition"}:
            yield from behavior_walk(item)


def _local_origins(source, body):
    origins = []
    for node in behavior_walk(body):
        left, right = _assignment(node)
        left, right = unwrap(left), unwrap(right)
        if left is not None and right is not None and left.type == "identifier":
            origin = access(source, right)
            origins.append({"local": source.text(left), "origin": origin, "start": node.end_byte, "end": body.end_byte})
        if node.type == "range_clause":
            lhs, rhs = child(node, "left"), child(node, "right")
            if lhs is not None and rhs is not None and lhs.named_children:
                variable = lhs.named_children[-1]
                if variable.type == "identifier" and source.text(variable) != "_":
                    origins.append({"local": source.text(variable), "origin": access(source, rhs),
                                    "start": node.end_byte, "end": node.parent.end_byte})
        if node.type == "for_in_statement":
            lhs, rhs = child(node, "left"), child(node, "right")
            if lhs is not None and rhs is not None and lhs.type == "identifier":
                origins.append({"local": source.text(lhs), "origin": access(source, rhs), "start": rhs.end_byte, "end": node.end_byte})
    return origins


def _expand_access(value, at, origins):
    seen = set()
    for _ in range(6):
        root, *suffix = value.split(".")
        matches = [o for o in origins if o["local"] == root and o["start"] <= at <= o["end"]]
        if not matches or root in seen:
            break
        chosen = max(matches, key=lambda o: o["start"])
        if not chosen["origin"]:
            break
        seen.add(root)
        value = chosen["origin"] + ("." + ".".join(suffix) if suffix else "")
    return value


def _type_name(text):
    text = text.strip().lstrip(": *![]")
    text = re.split(r"[<\[|,\s]", text, 1)[0]
    return text.split(".")[-1]


def _declared_types(program):
    """Explicit class/struct field and parameter types; no naming-based aliasing."""
    declarations = defaultdict(list)
    for source in program["sources"].values():
        if source.origin != "repository":
            continue
        for node in walk(source.root):
            if node.type not in {"class_declaration", "type_spec"}:
                continue
            name = child(node, "name")
            body = child(node, "body", "type")
            if name is None or body is None:
                continue
            fields = {}
            for item in walk(body):
                if item.type not in {"public_field_definition", "field_declaration"}:
                    continue
                field, annotation = child(item, "name"), child(item, "type")
                if field is not None and annotation is not None:
                    fields[source.text(field)] = _type_name(source.text(annotation))
            declarations[source.text(name)].append((source.path, fields))
    classes = {name: values[0] for name, values in declarations.items() if len(values) == 1}
    parameters = {}
    for fid, function in program["functions"].items():
        source = program["sources"][function["span"]["path"]]
        loc = function["span"]
        node = source.root.named_descendant_for_byte_range(loc["start_byte"], max(loc["start_byte"], loc["end_byte"] - 1))
        params = child(node, "parameters")
        types = {}
        if params is not None:
            for item in params.named_children:
                field, annotation = child(item, "name", "pattern"), child(item, "type")
                if field is not None and annotation is not None:
                    types[source.text(field)] = _type_name(source.text(annotation))
        if function.get("owner"):
            types.update({"this": function["owner"], "self": function["owner"]})
            receiver = function.get("receiver") or {}
            if isinstance(receiver, dict) and receiver.get("name"):
                types[receiver["name"]] = function["owner"]
        parameters[fid] = types
    return classes, parameters


def unwrap(node):
    while node is not None and node.type in {"expression_list", "parenthesized_expression"} and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


def access(source, node):
    node = unwrap(node)
    if node is None:
        return None
    if node.type in {"identifier", "this", "self", "shorthand_property_identifier_pattern"}:
        return source.text(node)
    if node.type in ATTRS:
        obj, field = attr_parts(node)
        root = access(source, obj)
        return root + "." + source.text(field) if root and field else None
    if node.type in INDEXES:
        obj, index = child(node, "value", "object", "operand"), child(node, "subscript", "index")
        root = access(source, obj)
        ok, value = _literal_node(source, index)
        return root + ("." + str(value) if ok else "[*]") if root else None
    return None


def reads(source, node):
    """Access paths, without method names or recursively copied expression ASTs."""
    result = set()
    for part in owned_walk(node):
        if part.type in ATTRS | INDEXES:
            if part.parent is not None and part.parent.type in ATTRS | INDEXES:
                continue
            if part.parent is not None and part.parent.type in CALLS and child(part.parent, "function", "constructor") == part:
                receiver, _ = attr_parts(part) if part.type in ATTRS else (None, None)
                value = access(source, receiver)
            else:
                value = access(source, part)
            if value:
                result.add(value)
        elif part.type == "identifier":
            parent = part.parent
            if parent is not None and (parent.type in ATTRS | INDEXES or
                    parent.type in CALLS and child(parent, "function", "constructor") == part):
                continue
            result.add(source.text(part))
    return sorted(result - {"undefined", "nil", "null", "None", "true", "false"})


def condition_atoms(source, node):
    node = unwrap(node)
    if node is None:
        return []
    operator = child(node, "operator")
    op = source.text(operator) if operator is not None else ""
    if not op:
        op = next((source.text(c) for c in node.children if not c.is_named and source.text(c) in {"and", "or", "&&", "||"}), "")
    if op in {"and", "or", "&&", "||"}:
        return condition_atoms(source, child(node, "left")) + condition_atoms(source, child(node, "right"))
    return [{"expression": source.text(node), "span": span(source, node), "reads": reads(source, node)}]


def _contexts(source, node, body):
    result = []
    current = node
    while current.parent is not None and current != body:
        parent = current.parent
        if parent.type in {"if_statement", "elif_clause", "conditional_expression", "ternary_expression"}:
            cond = child(parent, "condition")
            if cond is not None and not (cond.start_byte <= node.start_byte < cond.end_byte):
                alternative = child(parent, "alternative")
                result.append({"expression": source.text(cond), "value": not (alternative is not None and alternative.start_byte <= node.start_byte < alternative.end_byte),
                               "span": span(source, cond)})
        elif parent.type in LOOPS:
            result.append({"expression": source.text(child(parent, "condition")) or "loop executes", "value": None,
                           "span": span(source, parent)})
        elif parent.type in {"expression_case", "type_case", "case_statement", "switch_case"}:
            label = source.text(parent).split(":", 1)[0]
            result.append({"expression": "dispatch branch: " + label, "value": None, "span": span(source, parent)})
        elif parent.type in {"arrow_function", "func_literal", "function_expression", "lambda"}:
            result.append({"expression": "callback executes", "value": None, "span": span(source, parent)})
        current = parent
    return list(reversed(result))


def _default_fields(source, node):
    left, right = _assignment(node)
    left, right = unwrap(left), unwrap(right)
    if left is None or right is None:
        return []
    result = []
    if left.type == "object_pattern":
        root = access(source, right)
        for item in left.named_children:
            if item.type == "object_assignment_pattern":
                key, default = child(item, "left"), child(item, "right")
                name = source.text(key)
                result.append((root, name, name, default))
            elif item.type == "pair_pattern":
                value = child(item, "value")
                if value is not None and value.type == "assignment_pattern":
                    result.append((root, source.text(child(item, "key")), source.text(child(value, "left")), child(value, "right")))
    elif left.type == "identifier":
        target = source.text(left)
        if right.type in CALLS:
            fn, args = call_parts(right)
            obj, field = attr_parts(fn) if fn is not None and fn.type in ATTRS else (None, None)
            if source.text(field) == "get" and len(args) >= 2:
                ok, key = _literal_node(source, args[0])
                if ok and isinstance(key, str):
                    result.append((access(source, obj), key, target, args[1]))
        elif right.type in {"binary_expression", "boolean_operator"}:
            operator = child(right, "operator")
            if source.text(operator) in {"??", "||", "or"}:
                origin = access(source, child(right, "left"))
                if origin and "." in origin:
                    root, field = origin.rsplit(".", 1)
                    result.append((root, field, target, child(right, "right")))
    return [{"root": root, "field": field, "local": local, "default": source.text(default),
             "span": span(source, node)} for root, field, local, default in result if root and default is not None]


def _resolve(program, fid, callee, known):
    if known:
        resolved = [x["function_id"] for x in known.get("targets", []) if x.get("resolved")]
        if resolved:
            return resolved, "frontend_binding"
    function = program["functions"][fid]
    source = program["sources"][function["span"]["path"]]
    parts = callee.split(".")
    name = parts[-1]
    matches, method_matches = [], []
    imported = source.imports.get(parts[0])
    if len(parts) == 1 and imported and imported[1]:
        name = imported[1]
    if len(parts) == 1 and parts[0] in {p["name"] for p in function["parameters"]}:
        return [], "callable_parameter_unresolved"
    for other in program.get("_symbols_by_name", {}).get(name, []):
        target = program["functions"][other]
        if not target.get("production") or target["name"] != name:
            continue
        path = target["span"]["path"]
        local = path == source.path and (len(parts) == 1 or parts[0] in {"self", "this"} and target.get("owner") == function.get("owner"))
        package = source.language == "go" and len(parts) == 1 and PurePosixPath(path).parent == PurePosixPath(source.path).parent and not target.get("owner")
        if source.language == "go" and len(parts) == 2 and not imported and target.get("owner") and PurePosixPath(path).parent == PurePosixPath(source.path).parent:
            method_matches.append(other)
        imported_match = False
        if imported:
            module, symbol = imported
            module_stem = module.replace(".", "/") if source.language == "python" else module
            stems = {str(PurePosixPath(path).with_suffix("")), str(PurePosixPath(path).parent)}
            if source.language == "typescript" and module.startswith("."):
                import posixpath
                module_stem = posixpath.normpath(str(PurePosixPath(source.path).parent / module))
                module_stem = re.sub(r"\.(js|mjs|cjs)$", "", module_stem)
            if source.language == "python" and symbol and len(parts) > 1:
                # `from pkg import mod as alias; alias.fn()` imports a module.
                # An imported class can also qualify a method in pkg itself.
                submodule = module_stem + "/" + symbol
                imported_match = any(s == submodule or s.endswith("/" + submodule) for s in stems)
                imported_match |= target.get("owner") == symbol and any(s == module_stem or s.endswith("/" + module_stem) for s in stems)
            else:
                imported_match = any(s == module_stem or s.endswith("/" + module_stem) for s in stems) and (symbol is None or symbol == target["name"])
        if local or package or imported_match:
            matches.append(other)
    # This fallback is a source hypothesis; a name match never proves a receiver.
    if len(matches) == 1:
        return matches, "source_symbol_may_binding"
    if not matches and 0 < len(method_matches) <= 16:
        return method_matches, "same_package_method_may_dispatch_requires_type_review"
    return [], "unresolved"


def build_relations(program, patch):
    symbols = defaultdict(list)
    for fid, function in program["functions"].items():
        symbols[function["name"]].append(fid)
    program["_symbols_by_name"] = dict(symbols)
    changed = diff_lines(patch)
    nodes, edges, defaults, allocations = {}, [], [], []
    by_function = defaultdict(list)
    known_calls = {(c["span"]["path"], c["span"]["start_byte"], c["span"]["end_byte"]): c for c in program["frontend"]["production_calls"]}
    guard_conditions = {}
    dispatch_uses, dispatch_cases = defaultdict(list), defaultdict(list)

    def add(fid, source, node, kind, **extra):
        loc = span(source, node)
        key = "op_" + stable_id(fid, kind, loc)
        record = {"id": key, "function_id": fid, "kind": kind, "span": loc,
                  "code": source.text(node)[:1800], "code_truncated": len(source.text(node)) > 1800,
                  "changed": any(loc["line"] <= line <= loc["end_line"] for line in changed.get(source.path, [])),
                  "reads": reads(source, node), "conditions": _contexts(source, node, _body_node(source, program["functions"][fid])), **extra}
        nodes[key] = record
        by_function[fid].append(key)
        return record

    for fid, function in program["functions"].items():
        if not function.get("production"):
            continue
        source = program["sources"][function["span"]["path"]]
        body = _body_node(source, function)
        origins = _local_origins(source, body)
        for node in behavior_walk(body):
            if node.type in {"if_statement", "elif_clause", "conditional_expression", "ternary_expression"}:
                cond = child(node, "condition")
                if cond is not None:
                    row = add(fid, source, cond, "condition", atoms=condition_atoms(source, cond), statement_span=span(source, node))
                    guard_conditions[(source.path, cond.start_byte)] = row["id"]
            left, right = _assignment(node)
            left, right = unwrap(left), unwrap(right)
            if left is not None and right is not None:
                row = add(fid, source, node, "assignment", target=access(source, left), value=source.text(right), reads=reads(source, right))
                defaults.extend({**d, "operation": row["id"], "function_id": fid} for d in _default_fields(source, node))
            if node.type in CALLS:
                fn, args = call_parts(node)
                callee = source.text(fn)
                known = known_calls.get((source.path, node.start_byte, node.end_byte))
                targets, status = _resolve(program, fid, callee, known)
                row = add(fid, source, node, "call", callee=callee, arguments=[source.text(a) for a in args],
                          argument_spans=[span(source, a) for a in args], targets=targets, resolution=status)
                if callee.split(".")[-1] in {"exit", "Exit", "panic"}:
                    row["termination"] = True
                for argument in args:
                    value = source.text(argument)
                    if re.fullmatch(r"[A-Za-z_]\w*\.[A-Z]\w*", value):
                        dispatch_uses[value].append(row["id"])
            if node.type in {"return_statement", "throw_statement", "raise_statement", "yield_expression"}:
                add(fid, source, node, "observation", termination=node.type != "yield_expression", observation_kind=node.type)
            if node.type in INDEXES:
                parent = node.parent
                lhs, _ = _assignment(parent) if parent is not None else (None, None)
                if lhs == node:
                    continue
                obj, key = child(node, "value", "object", "operand"), child(node, "subscript", "index")
                add(fid, source, node, "lookup", container=access(source, obj), key=source.text(key),
                    distinctions=["position_or_key_present", "retrieved_value"])
            if node.type in {"expression_case", "case_statement", "switch_case"}:
                value = child(node, "value")
                text = source.text(value) if value is not None else source.text(node).split(":", 1)[0].removeprefix("case").strip()
                if re.fullmatch(r"[A-Za-z_]\w*\.[A-Z]\w*", text):
                    row = add(fid, source, node, "dispatch", symbol=text)
                    dispatch_cases[text].append(row["id"])
            # Repeated allocation is a question about sharing, not a claim of a copying bug.
            allocation = node.type == "new_expression" or node.type == "unary_expression" and source.text(node).lstrip().startswith("&") and any(n.type == "composite_literal" for n in node.named_children)
            if allocation:
                parent = node.parent
                loop = None
                while parent is not None and parent != body:
                    if parent.type in LOOPS:
                        loop = parent
                        break
                    parent = parent.parent
                if loop is not None:
                    clause = next((n for n in loop.named_children if n.type == "range_clause"), None)
                    origin = child(clause, "right") if clause is not None else child(loop, "right", "value")
                    row = add(fid, source, node, "allocation", loop_source=source.text(origin), loop_span=span(source, loop))
                    allocations.append(row["id"])
        for node_id in by_function[fid]:
            row = nodes[node_id]
            row["input_origin_reads"] = sorted({_expand_access(value, row["span"]["start_byte"], origins) for value in row["reads"]})

    for fid, ids in by_function.items():
        ordered = sorted((nodes[i] for i in ids), key=lambda n: (n["span"]["start_byte"], n["span"]["end_byte"]))
        definitions = defaultdict(list)
        for row in ordered:
            for value in row["reads"]:
                root = value.split(".")[0].split("[")[0]
                for origin in definitions.get(value, []) + definitions.get(root, []):
                    if nodes[origin]["span"]["end_byte"] <= row["span"]["start_byte"]:
                        edges.append({"from": origin, "to": row["id"], "kind": "value_flow", "access": value, "certainty": "may"})
            if row["kind"] == "assignment" and row.get("target"):
                target = row["target"]
                if not row["conditions"]:
                    definitions[target] = [row["id"]]
                else:
                    definitions[target].append(row["id"])
            for context in row["conditions"]:
                origin = guard_conditions.get((context["span"]["path"], context["span"]["start_byte"]))
                if origin and origin != row["id"]:
                    edges.append({"from": origin, "to": row["id"], "kind": "control", "when": context["value"], "certainty": "syntactic"})
            containers = [other for other in ordered if other["id"] != row["id"] and other["kind"] in {"assignment", "observation", "call", "condition", "dispatch"}
                          and other["span"]["start_byte"] <= row["span"]["start_byte"] and row["span"]["end_byte"] <= other["span"]["end_byte"]]
            if containers:
                parent = min(containers, key=lambda n: n["span"]["end_byte"] - n["span"]["start_byte"])
                if parent["kind"] == "dispatch":
                    edges.append({"from": parent["id"], "to": row["id"], "kind": "dispatch_control", "certainty": "syntactic"})
                else:
                    edges.append({"from": row["id"], "to": parent["id"], "kind": "expression_flow", "certainty": "syntactic"})
        for row in ordered:
            if row.get("termination"):
                enclosing = [c for c in row["conditions"] if c.get("value") is not None]
                if not enclosing:
                    continue
                callback_context = [c["span"] for c in row["conditions"] if c["expression"] == "callback executes"]
                for later in ordered:
                    same_callback = callback_context == [c["span"] for c in later["conditions"] if c["expression"] == "callback executes"]
                    if same_callback and later["span"]["start_byte"] > row["span"]["end_byte"] and later["kind"] in {"call", "observation", "assignment"} and later["conditions"] != row["conditions"]:
                        edges.append({"from": row["id"], "to": later["id"], "kind": "may_prevent_continuation", "conditions": enclosing, "certainty": "may"})
        for row in ordered:
            if row["kind"] != "call":
                continue
            for target in row["targets"]:
                for dest in by_function.get(target, []):
                    node = nodes[dest]
                    if node["kind"] == "observation":
                        edges.append({"from": dest, "to": row["id"], "kind": "call_result", "certainty": "may"})
                    if node["kind"] in {"condition", "assignment", "lookup"}:
                        params = {p["name"] for p in program["functions"][target]["parameters"]}
                        if any(x.split(".")[0].split("[")[0] in params for x in node["reads"]):
                            edges.append({"from": row["id"], "to": dest, "kind": "argument_flow", "certainty": "may"})
    for symbol in sorted(set(dispatch_uses) & set(dispatch_cases)):
        for caller in dispatch_uses[symbol]:
            for handler in dispatch_cases[symbol]:
                edges.append({"from": caller, "to": handler, "kind": "symbol_dispatch", "symbol": symbol, "certainty": "matching_dispatch_symbol"})
    # Share state through resolved owner/parameter regions from the existing analysis.
    state = defaultdict(list)
    for fid, summary in program["summaries"].items():
        for effect in summary["effects"]:
            if effect["resource"].startswith("parameter::"):
                continue  # Joining unrelated formal names would invent aliases.
            state[effect["resource"]].append((fid, effect))
    for resource, entries in state.items():
        writers = [(f, e) for f, e in entries if e["mode"] in {"write", "remove"}]
        readers = [(f, e) for f, e in entries if e["mode"] == "read"]
        for af, ae in writers:
            for bf, be in readers:
                if af == bf or not {af, bf} & program["changed"]:
                    continue
                def nearest(fid, loc):
                    options = [nodes[i] for i in by_function[fid] if nodes[i]["span"]["start_byte"] <= loc["start_byte"] and loc["end_byte"] <= nodes[i]["span"]["end_byte"]]
                    return min(options, key=lambda n: n["span"]["end_byte"] - n["span"]["start_byte"])["id"] if options else None
                a, b = nearest(af, ae["span"]), nearest(bf, be["span"])
                if a and b:
                    edges.append({"from": a, "to": b, "kind": "shared_state", "resource": resource, "certainty": "same_declared_region_not_runtime_identity"})
    classes, parameter_types = _declared_types(program)
    typed_reads, typed_writes = defaultdict(list), defaultdict(list)
    for row in nodes.values():
        values = row["input_origin_reads"]
        if row["kind"] == "assignment" and row.get("target"):
            values = values + [row["target"]]
        for value in values:
            parts = value.split(".")
            current_type = parameter_types.get(row["function_id"], {}).get(parts[0])
            if not current_type:
                continue
            for field in parts[1:]:
                declaration = classes.get(current_type)
                if declaration is None:
                    break
                resource = declaration[0] + "::" + current_type + "." + field
                is_write = row["kind"] == "assignment" and value == row.get("target")
                (typed_writes if is_write else typed_reads)[resource].append(row["id"])
                current_type = declaration[1].get(field)
                if not current_type:
                    break
    for resource in sorted(set(typed_reads) & set(typed_writes)):
        for writer in sorted(set(typed_writes[resource])):
            for reader in sorted(set(typed_reads[resource])):
                if nodes[writer]["function_id"] != nodes[reader]["function_id"] and {nodes[writer]["function_id"], nodes[reader]["function_id"]} & program["changed"]:
                    edges.append({"from": writer, "to": reader, "kind": "shared_state", "resource": resource,
                                  "certainty": "same_declared_type_and_field_requires_instance_review"})
    unique = {stable_id(e): e for e in edges if e["from"] != e["to"]}
    return {"nodes": nodes, "edges": list(unique.values()), "by_function": dict(by_function),
            "defaults": defaults, "allocations": allocations,
            "semantics": "Source may-dependence. Blocked continuations remain eligible; aliases and callback order need review."}


def schema_constraints(resources):
    """Read declaration paths and source lines; never execute YAML constructors."""
    import yaml
    result = []
    keys = {"pattern", "enum", "minimum", "maximum", "x-kubernetes-list-type", "x-kubernetes-list-map-keys"}
    for path, content in resources.items():
        try:
            documents = list(yaml.compose_all(content["code"], Loader=yaml.SafeLoader))
        except yaml.YAMLError:
            continue
        def visit(node, fields, ancestors):
            if node is None or id(node) in ancestors:
                return
            ancestors = ancestors | {id(node)}
            if isinstance(node, yaml.MappingNode):
                for key, value in node.value:
                    if not isinstance(key, yaml.ScalarNode):
                        continue
                    name = key.value
                    if name in keys:
                        raw = content["code"].splitlines()[key.start_mark.line:value.end_mark.line + 1]
                        result.append({"id": "schema_" + stable_id(path, key.start_mark.line, fields, name),
                                       "path": path, "line": key.start_mark.line + 1, "end_line": value.end_mark.line + 1,
                                       "field_path": ".".join(fields), "constraint": name, "code": "\n".join(raw)[:1600]})
                    elif name == "properties" and isinstance(value, yaml.MappingNode):
                        for field, specification in value.value:
                            if isinstance(field, yaml.ScalarNode):
                                visit(specification, fields + [field.value], ancestors)
                    else:
                        visit(value, fields, ancestors)
            elif isinstance(node, yaml.SequenceNode):
                for item in node.value:
                    visit(item, fields, ancestors)
        for document in documents:
            visit(document, [], set())
    return result
