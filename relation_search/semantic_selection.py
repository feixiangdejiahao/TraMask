"""Deterministic, cache-independent allocation of local assertion judgments.

Selection uses source syntax only. Shape buckets schedule representatives first;
they do not establish behavioral equivalence and never delete value variants.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json

from anchor_retrieval.syntax import CALLS, Source, child, walk


POLICY = {
    "version": "local-oracle-shape-round-robin-v1",
    "family": "operator, otherwise candidate kind, otherwise unspecified",
    "family_order": "lexicographic",
    "seed": "base_test_id",
    "seed_order": "minimum source retrieval rank, then minimum material-content SHA256",
    "shape": "language + normalized before/after AST + enclosing call/statement slots + edit roles + existing relation.profile",
    "normalization": "erase literal values; alpha-number syntactically local bindings; retain AST kinds, operators, member/global names and import identities",
    "shape_representative": "fewer edits, lower source retrieval rank, material-content SHA256",
    "identical_content_tie": "candidate identifier",
    "rounds": "all family/seed/shape first representatives before any second representative; repeat for remaining variants",
    "within_round": "family round robin, with independent seed round robin inside each family",
    "forbidden_inputs": ["evaluation", "target IDs", "oracle cache", "runtime outcome", "provider"],
    "invalid_syntax": "retain as a distinct material-content bucket with an explicit normalization status",
}

_FUNCTIONS = {"function_definition", "function_declaration", "method_definition", "method_declaration",
              "function_expression", "arrow_function", "lambda", "func_literal"}
_PATTERNS = {"identifier", "tuple_pattern", "list_pattern", "pattern_list", "tuple", "list",
             "array_pattern", "object_pattern", "pair_pattern", "rest_pattern", "expression_list",
             "parameters", "formal_parameters", "parameter_list", "required_parameter",
             "optional_parameter", "parameter_declaration", "variadic_parameter_declaration",
             "default_parameter", "typed_parameter", "typed_default_parameter", "assignment_pattern"}
_LITERALS = {"integer", "float", "number", "int_literal", "float_literal", "imaginary_literal",
             "interpreted_string_literal", "raw_string_literal", "rune_literal", "string_literal",
             "string_content", "string_fragment", "escape_sequence", "null", "none", "nil", "undefined"}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _span_key(span):
    return span["path"], span["start_byte"], span["end_byte"]


def _pattern_identifiers(node):
    if node is None or node.type not in _PATTERNS:
        return []
    if node.type == "identifier":
        return [node]
    if node.type in {"default_parameter", "typed_default_parameter", "assignment_pattern"}:
        return _pattern_identifiers(child(node, "name", "left"))
    if node.type in {"required_parameter", "optional_parameter", "parameter_declaration",
                     "variadic_parameter_declaration", "typed_parameter"}:
        named = child(node, "name", "pattern")
        if named is not None:
            return _pattern_identifiers(named)
        return [part for part in node.named_children if part.type == "identifier"]
    if node.type == "pair_pattern":
        return _pattern_identifiers(child(node, "value"))
    return [identifier for part in node.named_children for identifier in _pattern_identifiers(part)]


def _local_names(source):
    declarations = []
    for node in walk(source.root):
        if node.type in _FUNCTIONS:
            declarations.extend(_pattern_identifiers(child(node, "parameters", "parameter")))
        target = None
        if node.type in _FUNCTIONS:
            target = child(node, "name")
        elif node.type in {"assignment", "short_var_declaration", "named_expression", "for_statement"}:
            target = child(node, "left", "name")
        elif node.type in {"variable_declarator", "var_spec"}:
            target = child(node, "name")
        if target is not None:
            owner = node.parent
            while owner is not None and owner.type not in _FUNCTIONS:
                owner = owner.parent
            if owner is not None:
                declarations.extend(_pattern_identifiers(target))
    names = {}
    for node in sorted(declarations, key=lambda n: n.start_byte):
        spelling = source.text(node)
        names.setdefault(spelling, len(names))
    return names


def _normal(source, node, names):
    if node is None:
        return None
    kind = node.type
    if kind == "comment":
        return None
    if kind in {"true", "false"}:
        return ["boolean_literal", "<value>"]
    if kind in _LITERALS or (kind in {"string", "template_string"} and
                            not any(part.type in {"interpolation", "template_substitution"} for part in walk(node))):
        return [kind, "<value>"]
    if kind == "identifier":
        text = source.text(node)
        if text in names:
            return [kind, "local", names[text]]
        if text in source.imports:
            return [kind, "import", *source.imports[text]]
    if not node.children:
        return [kind, source.text(node)]
    children = []
    for index, part in enumerate(node.children):
        normalized = _normal(source, part, names)
        if normalized is not None:
            children.append([node.field_name_for_child(index), normalized])
    return [kind, children]


def _cover(source, start, end):
    if end <= start:
        return None
    node = source.root.named_descendant_for_byte_range(start, end - 1)
    while node is not None and not (node.start_byte <= start and end <= node.end_byte):
        node = node.parent
    return node


def _location(source, node, names):
    """Relative AST slots stop at the nearest call or statement boundary."""
    slots = []
    current = node
    while current is not None and current.parent is not None:
        parent = current.parent
        index = next(i for i, part in enumerate(parent.children) if part.id == current.id)
        named_index = sum(part.is_named for part in parent.children[:index])
        slots.append([parent.type, parent.field_name_for_child(index), named_index])
        if parent.type in CALLS:
            return {"slots": slots, "call": _normal(source, child(parent, "function", "constructor"), names)}
        if parent.type.endswith("statement") or parent.type in {"assignment", "short_var_declaration", "variable_declarator"}:
            break
        current = parent
    return {"slots": slots}


def _material(candidate):
    return {"base_test_id": candidate.get("base_test_id"),
            "operator": candidate.get("operator", candidate.get("kind", "unspecified")),
            "edits": [{key: edit.get(key) for key in ("span", "before", "after", "role")}
                      for edit in candidate.get("edits", [])],
            "imports": candidate.get("imports", []),
            "relation": candidate.get("relation", {})}


def _shape(corpus, candidate, source_cache):
    language = corpus.get("language", "python")
    edits_by_path = defaultdict(list)
    for edit in candidate.get("edits", []):
        edits_by_path[edit["span"]["path"]].append(edit)
    shapes = []
    status = "parsed"
    try:
        for path, edits in sorted(edits_by_path.items()):
            if path not in source_cache:
                source = Source(path, corpus["sources"][path]["code"], language)
                source_cache[path] = source, _local_names(source)
            before_source, before_names = source_cache[path]
            data = before_source.data
            previous_end = -1
            ordered = sorted(edits, key=lambda edit: _span_key(edit["span"]))
            offsets, delta = {}, 0
            for index, edit in enumerate(ordered):
                _, start, end = _span_key(edit["span"])
                if not 0 <= start <= end <= len(data) or start < previous_end or data[start:end].decode() != edit["before"]:
                    raise ValueError("invalid_or_overlapping_span")
                previous_end = end
                offsets[index] = start + delta
                delta += len(edit["after"].encode()) - (end-start)
            for edit in reversed(ordered):
                _, start, end = _span_key(edit["span"])
                data = data[:start] + edit["after"].encode() + data[end:]
            after_source = Source(path, data.decode(), language)
            for imported in candidate.get("imports", []):
                after_source.imports[imported["name"]] = imported["module"], imported.get("imported_name")
            after_names = _local_names(after_source)
            if before_source.root.has_error or after_source.root.has_error:
                raise ValueError("parse_error")
            for index, edit in enumerate(ordered):
                _, start, end = _span_key(edit["span"])
                after_start = offsets[index]
                before_node = _cover(before_source, start, end)
                after_node = _cover(after_source, after_start, after_start+len(edit["after"].encode()))
                # If an edit cuts through an AST node, do not assert structural
                # sameness with edits of that entire node.
                before_exact = before_node is None or (before_node.start_byte, before_node.end_byte) == (start, end)
                after_exact = after_node is None or (after_node.start_byte, after_node.end_byte) == (after_start, after_start+len(edit["after"].encode()))
                shapes.append({"role": edit.get("role", "input"),
                               "before": _normal(before_source, before_node, before_names),
                               "after": _normal(after_source, after_node, after_names),
                               "before_slot": _location(before_source, before_node, before_names),
                               "after_slot": _location(after_source, after_node, after_names),
                               "whole_node": [before_exact, after_exact]})
        shape = {"language": language, "edits": shapes,
                 "profile": candidate.get("relation", {}).get("profile")}
    except (ValueError, KeyError, IndexError, TypeError) as error:
        status = str(error) if isinstance(error, ValueError) else type(error).__name__
        shape = {"language": language, "unparsed_material": _sha(_material(candidate))}
    return shape, status


def select(corpus, candidates, budget=16):
    """Return selected original candidates and a complete deterministic ranking."""
    if not isinstance(budget, int) or budget < 0:
        raise ValueError("budget must be a nonnegative integer")
    candidates = list(candidates)
    identifiers = [candidate["id"] for candidate in candidates]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("candidate IDs must be unique")
    groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    source_cache = {}
    by_id = dict(zip(identifiers, candidates))
    for candidate in candidates:
        shape, status = _shape(corpus, candidate, source_cache)
        family = candidate.get("operator", candidate.get("kind", "unspecified"))
        seed = candidate.get("base_test_id", "")
        record = {"id": candidate["id"], "family": family, "base_test_id": seed,
                  "shape_id": _sha(shape), "shape": shape, "normalization_status": status,
                  "edit_count": len(candidate.get("edits", [])),
                  "source_retrieval_rank": candidate.get("source_retrieval_rank",
                      corpus.get("tests", {}).get(seed, {}).get("retrieval_rank", 100000)),
                  "content_sha256": _sha(_material(candidate))}
        groups[family][seed][record["shape_id"]].append(record)
    def priority(row):
        return row["edit_count"], row["source_retrieval_rank"], row["content_sha256"], row["id"]
    for seeds in groups.values():
        for shapes in seeds.values():
            for rows in shapes.values():
                rows.sort(key=priority)
    maximum = max((len(rows) for seeds in groups.values() for shapes in seeds.values() for rows in shapes.values()), default=0)
    ranking = []
    for variant in range(maximum):
        queues, seed_orders = {}, {}
        for family, seeds in groups.items():
            queues[family] = {}
            for seed, shapes in seeds.items():
                rows = sorted((rows[variant] for rows in shapes.values() if len(rows) > variant), key=priority)
                if rows:
                    queues[family][seed] = deque(rows)
            seed_orders[family] = deque(sorted(queues[family], key=lambda seed: (
                min(row["source_retrieval_rank"] for row in queues[family][seed]),
                min(row["content_sha256"] for row in queues[family][seed]))))
        families = deque(sorted(family for family in groups if seed_orders[family]))
        while families:
            family = families.popleft()
            seed = seed_orders[family].popleft()
            row = queues[family][seed].popleft()
            ranking.append({**row, "variant_round": variant, "rank": len(ranking)+1,
                            "selected": len(ranking) < budget})
            if queues[family][seed]:
                seed_orders[family].append(seed)
            if seed_orders[family]:
                families.append(family)
    return {"selected": [by_id[row["id"]] for row in ranking[:budget]],
            "ranking": ranking, "unselected_ids": [row["id"] for row in ranking[budget:]],
            "budget": budget, "input_count": len(candidates), "selected_count": min(budget, len(candidates)),
            "shape_count": sum(len(shapes) for seeds in groups.values() for shapes in seeds.values()),
            "policy": POLICY, "policy_sha256": _sha(POLICY)}
