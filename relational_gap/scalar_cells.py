"""Bounded scalar witnesses anchored in source comparisons and bit tests.

An unavailable counteroperand does not erase a source-relevant input: its two
neighbors remain explicit unknown-boundary hypotheses. No hypothesis is called
an executed relation cell or a justified oracle. Subject API names are opaque.
"""
from __future__ import annotations

import collections
from dataclasses import asdict, dataclass
import hashlib
import json
import posixpath

from anchor_retrieval.syntax import CALLS, FUNCTIONS, Source, call_parts, child, literal, walk
from generic_composition.corpus import ASSIGNMENTS


@dataclass(frozen=True)
class ScalarBudget:
    max_candidates: int = 128
    max_paths: int = 512
    max_depth: int = 4
    max_cells_per_argument: int = 8
    max_mask_bits: int = 8
    max_integer_bits: int = 64
    boundary_offsets: tuple[int, ...] = (-1, 0, 1)

    def __post_init__(self):
        if any(type(getattr(self, key)) is not int or getattr(self, key) < 1 for key in
               ("max_candidates", "max_paths", "max_depth", "max_cells_per_argument", "max_mask_bits", "max_integer_bits")):
            raise ValueError("scalar budgets must be positive integers")
        if not self.boundary_offsets or any(type(n) is not int or abs(n) > 1 for n in self.boundary_offsets):
            raise ValueError("boundary offsets are limited to -1, 0, 1")


def _id(*items):
    return hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def _span(source, node):
    return {"path": source.path, "start_byte": node.start_byte, "end_byte": node.end_byte,
            "line": node.start_point.row + 1, "end_line": node.end_point.row + 1}


def _unwrap(node):
    while node is not None and node.type in {"parenthesized_expression", "expression_list", "literal_element"} and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


def _inside(node, position):
    return node is not None and position["start_byte"] <= node.start_byte and node.end_byte <= position["end_byte"]


def _owned_walk(node):
    yield node
    for item in node.named_children:
        if item.type not in FUNCTIONS | {"arrow_function", "function_expression", "func_literal", "lambda"}:
            yield from _owned_walk(item)


class _Kernel:
    def __init__(self, corpus, frontend, budget):
        self.corpus, self.frontend, self.budget = corpus, frontend, budget
        self.sources = {path: Source(path, metadata["code"], metadata.get("language", corpus["language"]))
                        for path, metadata in corpus["sources"].items()}
        self.nodes = {path: {(n.start_byte, n.end_byte): n for n in walk(source.root)} for path, source in self.sources.items()}
        self.functions = {f["id"]: f for f in frontend.get("functions", [])}
        self.aliases = []
        self.constants = collections.defaultdict(list)
        self.skipped = collections.Counter()
        self._declarations()

    def node(self, position):
        return self.nodes.get(position["path"], {}).get((position["start_byte"], position["end_byte"]))

    def _declarations(self):
        for path, source in self.sources.items():
            for node in walk(source.root):
                if node.type in {"type_spec", "type_alias", "type_alias_declaration"}:
                    name, value = child(node, "name"), child(node, "type", "value")
                    if name is not None and value is not None:
                        parent = node.parent
                        scope = None
                        while parent is not None and parent != source.root:
                            if parent.type in FUNCTIONS | {"arrow_function", "function_expression", "func_literal", "class_definition", "class_declaration", "internal_module"}:
                                scope = _span(source, parent)
                                break
                            parent = parent.parent
                        self.aliases.append({"name": source.text(name), "target": source.text(value),
                                             "span": _span(source, node), "language": source.language, "scope_span": scope})
                if node.type in ASSIGNMENTS | {"assignment_expression"}:
                    target, value = child(node, "name", "left"), _unwrap(child(node, "value", "right"))
                    if target is not None and target.type == "identifier" and value is not None:
                        self.constants[path, source.text(target)].append((node, value))
                if node.type in {"const_spec", "var_spec"}:
                    values = child(node, "value")
                    names = node.children_by_field_name("name")
                    values = list(values.named_children) if values is not None and values.type == "expression_list" else [values]
                    if len(names) == len(values):
                        for name, value in zip(names, values):
                            if value is not None:
                                self.constants[path, source.text(name)].append((node, value))

    def numeric_type(self, spelling, path, seen=()):
        name = spelling.lstrip(": ").strip()
        key = (path, name)
        if not name or key in seen or len(seen) > self.budget.max_depth:
            return {"kind": "unknown", "underlying": name, "aliases": []}
        choices = [a for a in self.aliases if a["name"] == name and a["span"]["path"] == path and a["scope_span"] is None]
        if not choices and self.sources[path].language == 'go' and '.' in name:
            qualifier, separator, member = name.partition('.')
            if separator and qualifier.isidentifier() and member.isidentifier():
                directories = self._imported_go_directories(path, qualifier)
                choices = [a for a in self.aliases if a['name'] == member and a['scope_span'] is None
                           and posixpath.dirname(a['span']['path']) in directories]
        if not choices and self.sources[path].language == "go":
            choices = [a for a in self.aliases if a["name"] == name and a["scope_span"] is None
                       and posixpath.dirname(a["span"]["path"]) == posixpath.dirname(path)]
        if len(choices) == 1:
            chosen = choices[0]
            info = self.numeric_type(chosen["target"], chosen["span"]["path"], (*seen, key))
            return dict(info, aliases=[chosen, *info["aliases"]])
        if len(choices) > 1:
            return {"kind": "unknown", "underlying": name, "aliases": []}
        integer = {"int", "integer", "number", "uint", "uintptr", "byte", "rune", "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"}
        if name in integer:
            bits = int("".join(c for c in name if c.isdigit()) or ("8" if name == "byte" else "32" if name == "rune" else "0"))
            return {"kind": "integer", "underlying": name, "unsigned": name.startswith("uint") or name == "byte", "bits": bits or None, "aliases": []}
        if name in {"str", "string", "bool", "boolean", "float", "float32", "float64", "[]byte"}:
            return {"kind": "non_integer", "underlying": name, "aliases": []}
        if name.startswith(('*', '[', 'map[', 'chan ', '<-chan ', 'func(', 'interface', 'struct')):
            return {"kind": "non_integer", "underlying": name, "aliases": []}
        return {"kind": "unknown", "underlying": name, "aliases": []}

    def _imported_go_directories(self, path, qualifier):
        """Resolve a package through source imports and supplied go.mod facts.

        Package basenames alone are insufficient: a module can use another
        package name, and two dependencies can expose the same type spelling.
        """
        modules = self.frontend.get('module_resolution', {}).get('go_modules', {})
        source = self.sources[path]
        directories = set()
        for node in walk(source.root):
            if node.type != 'import_spec':
                continue
            imported, alias = child(node, 'path'), child(node, 'name')
            if imported is None:
                continue
            try:
                module = literal(source.text(imported))
            except ValueError:
                continue
            if not isinstance(module, str):
                continue
            matching = [(root, prefix) for root, prefix in modules.items()
                        if module == prefix or module.startswith(prefix + '/')]
            if not matching:
                continue
            longest = max(len(prefix) for _, prefix in matching)
            targets = {posixpath.normpath(posixpath.join(root, module[len(prefix):].lstrip('/')))
                       for root, prefix in matching if len(prefix) == longest}
            if len(targets) != 1:
                continue
            directory = targets.pop()
            directory = '' if directory == '.' else directory
            if alias is not None:
                if source.text(alias) == qualifier:
                    directories.add(directory)
                continue
            package_names = set()
            for target_path, target in self.sources.items():
                if target.language != 'go' or posixpath.dirname(target_path) != directory:
                    continue
                for declaration in target.root.named_children:
                    if declaration.type == 'package_clause':
                        package_names.update(target.text(n) for n in declaration.named_children
                                             if n.type in {'package_identifier', 'identifier'})
            if package_names == {qualifier}:
                directories.add(directory)
        return directories

    def cast_type(self, source, function_node):
        """Only source-resolved Go conversions, never a name-shaped Python call."""
        name = source.text(function_node)
        if source.language != "go" or function_node is None or function_node.type not in {"identifier", "type_identifier"}:
            return {"kind": "unknown"}
        paths = {p for p in self.sources if posixpath.dirname(p) == posixpath.dirname(source.path)}
        if (name in source.imports or any(f["name"] == name and f["span"]["path"] in paths for f in self.functions.values())
                or any(p in paths and symbol == name for p, symbol in self.constants)
                or any(b.get("name") == name and b.get("span", {}).get("path") in paths for b in self.frontend.get("bindings", []))
                or any(a["name"] == name and a["scope_span"] is not None and a["span"]["path"] in paths for a in self.aliases)):
            return {"kind": "unknown"}
        return self.numeric_type(name, source.path)

    def ir(self, source, node, function, seen=(), depth=0):
        node = _unwrap(node)
        if node is None or depth > 16:
            return {"kind": "unknown", "reason": "expression_bound"}
        text = source.text(node)
        base = {"span": _span(source, node), "text": text}
        try:
            value = literal(text)
            if type(value) is int and value.bit_length() <= self.budget.max_integer_bits:
                return dict(base, kind="literal", value=value)
        except ValueError:
            pass
        if node.type == "identifier":
            parameters = function.get("parameters", []) if function else []
            matches = [p for p in parameters if p.get("name") == text]
            if len(matches) == 1:
                return dict(base, kind="formal", function_id=function["id"], index=matches[0]["index"], name=text)
            key = (source.path, text)
            if key not in seen:
                definitions = []
                for declaration, value in self.constants.get(key, []):
                    if declaration.end_byte > node.start_byte:
                        continue
                    parent = declaration.parent
                    blocked = False
                    while parent is not None and parent != source.root:
                        if parent.type in {"if_statement", "for_statement", "while_statement", "try_statement", "conditional_expression", "ternary_expression"}:
                            blocked = True
                        if parent.type in FUNCTIONS | {"arrow_function", "function_expression", "func_literal"}:
                            if not function or not _inside(parent, function["span"]):
                                blocked = True
                            break
                        parent = parent.parent
                    if not blocked:
                        definitions.append((declaration, value))
                if definitions:
                    declaration, value = max(definitions, key=lambda pair: pair[0].end_byte)
                    result = self.ir(source, value, function, (*seen, key), depth + 1)
                    return dict(result, definition_span=_span(source, declaration))
            return dict(base, kind="unknown", reason="unresolved_symbol")
        if node.type in {"binary_expression", "binary_operator"}:
            op = source.text(child(node, "operator"))
            if op in {"+", "-", "*", "//", "/", "%", "&", "|", "^", "&^", "<<", ">>"}:
                return dict(base, kind="binary", operator=op,
                            left=self.ir(source, child(node, "left"), function, seen, depth + 1),
                            right=self.ir(source, child(node, "right"), function, seen, depth + 1))
        if node.type in {"unary_expression", "unary_operator"}:
            op = source.text(child(node, "operator"))
            if op in {"+", "-", "~", "^"}:
                return dict(base, kind="unary", operator=op,
                            operand=self.ir(source, child(node, "operand", "argument"), function, seen, depth + 1))
        if node.type in CALLS:
            fn, args = call_parts(node)
            info = self.cast_type(source, fn)
            if info["kind"] == "integer" and len(args) == 1:
                return dict(base, kind="cast", operand=self.ir(source, args[0], function, seen, depth + 1), type_info=info)
        return dict(base, kind="unknown", reason="unsupported_or_effectful_expression")

    def safe_actual(self, source, node, function):
        node = _unwrap(node)
        if node is None:
            return False
        try:
            value = literal(source.text(node))
            return type(value) is int and value.bit_length() <= self.budget.max_integer_bits
        except ValueError:
            pass
        if node.type == "identifier":
            return True
        if node.type in {"binary_expression", "binary_operator"}:
            return (source.text(child(node, "operator")) in {"+", "-", "*", "//", "/", "%", "&", "|", "^", "&^", "<<", ">>"}
                    and self.safe_actual(source, child(node, "left"), function) and self.safe_actual(source, child(node, "right"), function))
        if node.type in {"unary_expression", "unary_operator"}:
            return source.text(child(node, "operator")) in {"+", "-", "~", "^"} and self.safe_actual(source, child(node, "operand", "argument"), function)
        if node.type in CALLS:
            fn, args = call_parts(node)
            return (self.cast_type(source, fn)["kind"] == "integer" and len(args) == 1
                    and self.safe_actual(source, args[0], function))
        return False


def _visit(ir):
    yield ir
    for key in ("left", "right", "operand"):
        if isinstance(ir.get(key), dict):
            yield from _visit(ir[key])


def _substitute(ir, function_id, bindings):
    if ir.get("kind") == "formal" and ir["function_id"] == function_id:
        return bindings.get(ir["index"], {"kind": "unknown", "reason": "unbound_formal", "text": ir["name"]})
    return {key: _substitute(value, function_id, bindings) if key in {"left", "right", "operand"} and isinstance(value, dict) else value
            for key, value in ir.items()}


def _constant(ir, actuals=None):
    kind = ir.get("kind")
    if kind == "literal":
        return ir["value"]
    if kind == "actual":
        return (actuals or {}).get(ir["slot"])
    if kind == "cast":
        value = _constant(ir["operand"], actuals)
        info = ir["type_info"]
        if value is not None and info.get("bits"):
            bits = info["bits"]
            if info["unsigned"] and not 0 <= value < 2 ** bits or not info["unsigned"] and not -2 ** (bits - 1) <= value < 2 ** (bits - 1):
                return None
        return value
    if kind == "unary":
        value = _constant(ir["operand"], actuals)
        if value is None:
            return None
        return value if ir["operator"] == "+" else -value if ir["operator"] == "-" else ~value
    if kind == "binary":
        a, b = _constant(ir["left"], actuals), _constant(ir["right"], actuals)
        if a is None or b is None:
            return None
        op = ir["operator"]
        if op == "+": return a + b
        if op == "-": return a - b
        if op == "*" and a.bit_length() + b.bit_length() <= 128: return a * b
        if op in {"/", "//"} and b and a % b == 0: return a // b
        if op == "%" and b: return a % b
        if op == "&": return a & b
        if op == "|": return a | b
        if op == "^": return a ^ b
        if op == "&^": return a & ~b
        if op == "<<" and 0 <= b <= 64: return a << b
        if op == ">>" and 0 <= b <= 64: return a >> b
    return None


def _affine(ir, slot, actuals):
    if ir.get("kind") == "actual" and ir["slot"] == slot:
        return 1, 0
    constant = _constant(ir, {k: v for k, v in actuals.items() if k != slot})
    if constant is not None:
        return 0, constant
    if ir.get("kind") == "unary" and ir["operator"] in {"+", "-"}:
        value = _affine(ir["operand"], slot, actuals)
        sign = -1 if ir["operator"] == "-" else 1
        return (sign * value[0], sign * value[1]) if value else None
    if ir.get("kind") == "binary" and ir["operator"] in {"+", "-", "*"}:
        a, b = _affine(ir["left"], slot, actuals), _affine(ir["right"], slot, actuals)
        if a is None or b is None:
            return None
        if ir["operator"] == "+": return a[0] + b[0], a[1] + b[1]
        if ir["operator"] == "-": return a[0] - b[0], a[1] - b[1]
        if a[0] == 0: return a[1] * b[0], a[1] * b[1]
        if b[0] == 0: return b[1] * a[0], b[1] * a[1]
    return None


def generate_scalar_cells(corpus: dict, frontend: dict, *, budget: ScalarBudget | None = None) -> dict:
    budget = budget or ScalarBudget()
    kernel = _Kernel(corpus, frontend, budget)
    incoming = collections.defaultdict(list)
    for call in frontend.get("calls", []) + frontend.get("production_calls", []):
        if call.get("test_id") is not None and call.get("role") != "operation":
            continue
        by_function = collections.defaultdict(list)
        for binding in call.get("argument_bindings", []):
            if binding.get("binding_status") == "direct_actual_formal":
                by_function[binding["function_id"]].append(binding)
        for function_id, bindings in by_function.items():
            incoming[function_id].append((call, bindings))
    constraints = []
    for comparison in frontend.get("comparisons", []):
        function = kernel.functions.get(comparison["function_id"])
        if not function or function.get("test") or comparison["operator"] not in {"<", "<=", ">", ">=", "==", "!=", "===", "!=="}:
            continue
        source = kernel.sources[comparison["span"]["path"]]
        left = kernel.ir(source, kernel.node(comparison["left"]["span"]), function)
        right = kernel.ir(source, kernel.node(comparison["right"]["span"]), function)
        constraints.append((comparison, function, left, right))
    for guard in frontend.get("guards", []):
        function = kernel.functions.get(guard["function_id"])
        if not function or function.get("test"):
            continue
        source = kernel.sources[guard["condition"]["span"]["path"]]
        ir = kernel.ir(source, kernel.node(guard["condition"]["span"]), function)
        if ir.get("kind") == "binary" and ir.get("operator") == "&":
            constraints.append((dict(guard, operator="truthy_bit_test"), function, ir, {"kind": "literal", "value": 0}))
    pool, paths, unknowns = {}, 0, []
    for constraint, origin, left, right in constraints:
        formals = [node for ir in (left, right) for node in _visit(ir) if node.get("kind") == "formal"]
        if not formals:
            continue
        types = [kernel.numeric_type(next(p.get("type", "") for p in origin["parameters"] if p["index"] == f["index"]), origin["span"]["path"])
                 for f in formals]
        if all(info["kind"] == "non_integer" for info in types):
            kernel.skipped["non_integer_formals"] += 1
            continue
        queue = collections.deque([(origin["id"], left, right, [], 0)])
        visited = set()
        while queue and paths < budget.max_paths:
            fid, lhs, rhs, trail, depth = queue.popleft()
            state = (fid, _id(lhs, rhs))
            if state in visited or depth >= budget.max_depth:
                continue
            visited.add(state)
            for call, bindings in incoming[fid]:
                paths += 1
                if paths > budget.max_paths:
                    break
                args = {a["slot"]: a for a in call["arguments"]}
                caller = kernel.functions.get(call.get("function_id"))
                source = kernel.sources[call["span"]["path"]]
                test_id = call.get("test_id")
                environment = {}
                for binding in bindings:
                    arg = args.get(binding["slot"])
                    if arg is not None:
                        environment[binding["parameter_index"]] = ({"kind": "actual", "slot": arg["slot"]} if test_id is not None
                                                                   else kernel.ir(source, kernel.node(arg["span"]), caller))
                mapped_left, mapped_right = _substitute(lhs, fid, environment), _substitute(rhs, fid, environment)
                edge = {"call_id": call["id"], "function_id": fid, "call_span": call["span"],
                        "bindings": [{"slot": b["slot"], "parameter_index": b["parameter_index"], "resolution": b["resolution"]} for b in bindings]}
                path = [edge, *trail]
                if test_id is None:
                    if caller and any(n.get("kind") == "formal" for ir in (mapped_left, mapped_right) for n in _visit(ir)):
                        queue.append((caller["id"], mapped_left, mapped_right, path, depth + 1))
                    continue
                if test_id not in corpus["tests"]:
                    continue
                test_function = kernel.functions.get(test_id)
                actuals = {slot: _constant(kernel.ir(source, kernel.node(arg["span"]), test_function)) for slot, arg in args.items()}
                relevant = sorted({n["slot"] for ir in (mapped_left, mapped_right) for n in _visit(ir) if n.get("kind") == "actual"})
                for slot in relevant:
                    arg = args[slot]
                    if not kernel.safe_actual(source, kernel.node(arg["span"]), test_function):
                        kernel.skipped["effectful_or_noninteger_actual"] += 1
                        continue
                    immediate = kernel.functions.get(fid, {})
                    immediate_types = [kernel.numeric_type(p.get('type', ''), immediate['span']['path'])
                                       for binding in bindings if binding['slot'] == slot
                                       for p in immediate.get('parameters', [])
                                       if p['index'] == binding['parameter_index']]
                    if immediate_types and all(info['kind'] == 'non_integer' for info in immediate_types):
                        kernel.skipped['non_integer_actual_domain'] += 1
                        continue
                    numeric_info = next((info for info in immediate_types if info['kind'] == 'integer'), None)
                    # A missing counter value is different from a missing
                    # numeric-domain premise. Equality also accepts pointers,
                    # hashes and arbitrary objects; it does not license x+1.
                    actual_ir = kernel.ir(source, kernel.node(arg['span']), test_function)
                    integer_syntax = any(n.get('kind') == 'binary' and n.get('operator') in {'&', '|', '^', '&^', '<<', '>>'}
                                         for n in _visit(actual_ir))
                    if (numeric_info is None and actuals[slot] is None and not integer_syntax
                            and not any(n.get('kind') == 'literal' for n in _visit(actual_ir))):
                        kernel.skipped['numeric_actual_domain_unknown'] += 1
                        continue
                    # A literal feeding an observed call can also occur in a
                    # broad oracle dependence slice. Reject actual expected
                    # expression locations, not such may-dependence labels.
                    if any(q.get('test_id') == test_id and q.get('expected')
                           and q['expected']['span']['path'] == arg['span']['path']
                           and q['expected']['span']['start_byte'] <= arg['span']['start_byte']
                           and arg['span']['end_byte'] <= q['expected']['span']['end_byte']
                           for q in corpus.get('capsules', ())):
                        kernel.skipped["expected_dependency"] += 1
                        continue
                    hypotheses = []
                    a, b = _affine(mapped_left, slot, actuals), _affine(mapped_right, slot, actuals)
                    if a is not None and b is not None:
                        coefficient, offset = a[0] - b[0], a[1] - b[1]
                        if coefficient and (-offset) % coefficient == 0:
                            boundary = -offset // coefficient
                            for delta in budget.boundary_offsets:
                                value = boundary + delta
                                hypotheses.append((str(value), "exact_affine_boundary", {"value": value, "offset": delta, "boundary": boundary}))
                        elif not coefficient:
                            kernel.skipped["comparison_independent_of_argument"] += 1
                            continue
                    masks = set()
                    for ir in (mapped_left, mapped_right):
                        for bit in _visit(ir):
                            if bit.get("kind") != "binary" or bit.get("operator") != "&":
                                continue
                            for target, other in ((bit["left"], bit["right"]), (bit["right"], bit["left"])):
                                mask = _constant(other, actuals)
                                if target.get("kind") == "actual" and target["slot"] == slot and type(mask) is int and 0 < mask < 2 ** budget.max_integer_bits:
                                    masks.add(mask)
                                    masks.update(1 << i for i in range(min(mask.bit_length(), budget.max_integer_bits)) if mask & (1 << i))
                    for mask in sorted(masks)[:budget.max_mask_bits]:
                        hypotheses.append(("(" + arg["text"] + ") | " + str(mask), "observed_mask_set", {"mask": mask, "action": "set"}))
                        clear = " &^ " if source.language == "go" else " & ~"
                        hypotheses.append(("(" + arg["text"] + ")" + clear + str(mask), "observed_mask_clear", {"mask": mask, "action": "clear"}))
                    if not hypotheses:
                        for delta in (-1, 1):
                            after = "(" + arg["text"] + ") " + ("+ " if delta > 0 else "- ") + "1"
                            value = actuals[slot] + delta if actuals[slot] is not None else None
                            if value is not None and not any(n.type in {'identifier', 'type_identifier'}
                                                             for n in walk(kernel.node(arg['span']))):
                                after = str(value)
                            hypotheses.append((after, "unknown_boundary_neighbor", {"offset": delta, "value": value}))
                    for after, kind, cell in hypotheses[:budget.max_cells_per_argument]:
                        value = cell.get("value")
                        if after == arg["text"] or (value is not None and value == actuals[slot]):
                            continue
                        type_info = numeric_info or {"kind": "source_integer_expression", "aliases": []}
                        if value is not None and (abs(value).bit_length() > budget.max_integer_bits or type_info.get("unsigned") and value < 0
                                                  or type_info.get("bits") and not (0 <= value < 2 ** type_info["bits"] if type_info.get("unsigned")
                                                                                   else -2 ** (type_info["bits"] - 1) <= value < 2 ** (type_info["bits"] - 1))):
                            kernel.skipped["integer_range"] += 1
                            continue
                        edit = {"span": arg["span"], "before": arg["text"], "after": after}
                        cid = "scalar_" + _id(test_id, edit)
                        relation = {"domain": "source_scalar_constraint", "cell": cell, "construction": kind,
                                    "operator": constraint["operator"], "constraint_span": constraint["span"],
                                    "comparison_span": constraint["span"], "function_id": origin["id"],
                                    "call_span": call["span"], "argument_slot": slot, "binding_path": path,
                                    "numeric_type": type_info, "counteroperand_status": "unrecoverable_or_nonlinear" if kind == "unknown_boundary_neighbor" else "source_expression_recovered",
                                    "status": "hypothesis_runtime_relation_unconfirmed", "evaluation": "original_actual_occurs_once_or_closed_integer"}
                        if cid in pool:
                            # One concrete edit can be supported by several
                            # source predicates. Deduplicate executions, not
                            # derivations needed for later witness composition.
                            evidence = pool[cid].setdefault('source_constraint_derivations', [pool[cid]['relation']])
                            if relation not in evidence:
                                evidence.append(relation)
                            continue
                        pool[cid] = {"id": cid, "base_test_id": test_id, "focus_test_id": test_id, "source_test_ids": [test_id],
                                     "kind": "scalar_source_constraint", "language": source.language, "edits": [edit], "imports": [],
                                     "relation": relation,
                                     "oracle": {"mode": "retain_all", "source_test_id": test_id, "applicability": "requires_independent_admission"},
                                     "provenance": {"source_spans": [constraint["span"], arg["span"], *[a["span"] for a in type_info["aliases"]]],
                                                    "target_span": arg["span"]},
                                     "selection": {"edit_size": max(len(arg["text"].encode()), len(after.encode())),
                                                   "focus_order": corpus["tests"][test_id].get("retrieval_rank") or 10**9}}
    queues = collections.OrderedDict()
    for candidate in sorted(pool.values(), key=lambda c: (c["selection"]["focus_order"], c["base_test_id"], c["relation"]["call_span"]["start_byte"], c["id"])):
        queues.setdefault(candidate["base_test_id"], collections.deque()).append(candidate)
    selected, active = [], list(queues)
    while active and len(selected) < budget.max_candidates:
        following = []
        for test_id in active:
            selected.append(queues[test_id].popleft())
            if queues[test_id]: following.append(test_id)
            if len(selected) >= budget.max_candidates: break
        active = following
    return {"version": 1, "budget": asdict(budget), "candidates": selected, "unknowns": unknowns,
            "type_aliases": kernel.aliases,
            "counts": {"constraints": len(constraints), "paths": min(paths, budget.max_paths), "candidate_pool": len(pool),
                       "candidates": len(selected), "skipped": dict(kernel.skipped), "path_budget_exhausted": paths >= budget.max_paths,
                       "candidate_budget_exhausted": len(pool) > len(selected)}}
