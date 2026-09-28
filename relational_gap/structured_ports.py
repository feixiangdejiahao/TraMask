"""Source-proven literal leaf carriers with explicit record/index paths.

These are syntax and value-binding facts. A carrier does not prove that a
callee consumes a field, nor that a mutable container is unchanged at runtime.
"""
from __future__ import annotations

import json

from anchor_retrieval.syntax import Source, child, literal
from generic_composition.engine import slot_key

from .transforms import _node_for, _position, _root_ports, _same_span


def structural_slot_key(port: dict) -> tuple:
    return (*slot_key(port), json.dumps(port.get("structural_path", []), sort_keys=True, ensure_ascii=True))


def _span(source, node):
    return {"path": source.path, "start_byte": node.start_byte, "end_byte": node.end_byte,
            "line": node.start_point.row + 1, "end_line": node.end_point.row + 1}


def _key(source, node, *, allow_field=False):
    while node is not None and node.type == "literal_element" and len(node.named_children) == 1:
        node = node.named_children[0]
    if node is None:
        return None
    if node.type == "property_identifier" and source.language == "typescript":
        return {"kind": "key", "value": source.text(node)}
    if node.type == "field_identifier" or allow_field and source.language == "go" and node.type == "identifier":
        return {"kind": "field", "value": source.text(node)}
    try:
        value = literal(source.text(node))
    except ValueError:
        return None
    if type(value) in {str, int, bool} or value is None:
        if source.language == "typescript" and type(value) is int:
            value = str(value)
        return {"kind": "key", "value": value}
    return None


def _container_step(source, node):
    """Return (container, path step), or stop at a nonliteral boundary."""
    parent = node.parent
    if parent is None:
        return None
    if parent.type in {"parenthesized_expression", "literal_element"} and len(parent.named_children) == 1:
        return parent, None
    if parent.type in {"pair", "keyed_element"}:
        if child(parent, "value") != node:
            return None
        container = parent.parent
        if container is None or container.type not in {"dictionary", "object", "literal_value"}:
            return None
        composite = container.parent
        typename = child(composite, "type") if composite is not None and composite.type == "composite_literal" else None
        allow_field = typename is not None and typename.type in {"type_identifier", "qualified_type", "struct_type"}
        key = _key(source, child(parent, "key"), allow_field=allow_field)
        if key is None:
            return None
        members = [n for n in container.named_children if n.type != "comment"]
        if any(n.type not in {"pair", "keyed_element"} for n in members):
            return None
        keys = [_key(source, child(n, "key"), allow_field=allow_field) for n in members]
        if any(k is None for k in keys) or len({json.dumps(k, sort_keys=True) for k in keys}) != len(keys):
            return None
        if source.language == "python" and len({k["value"] for k in keys}) != len(keys):
            return None
        return container, key
    if parent.type in {"list", "tuple", "array", "literal_value"}:
        members = [n for n in parent.named_children if n.type != "comment"]
        if any(n.type in {"list_splat", "list_splat_pattern", "spread_element", "keyed_element", "pair"} for n in members):
            return None
        if node not in members:
            return None
        # Array elisions alter positional offsets without a named AST child.
        if parent.type == "array":
            tokens = [n.type for n in parent.children if n.type not in {"[", "]", "comment"}]
            if tokens and tokens[0] == "," or any(a == b == "," for a, b in zip(tokens, tokens[1:])):
                return None
        return parent, {"kind": "index", "value": members.index(node)}
    if parent.type == "composite_literal" and child(parent, "body") == node:
        return parent, None
    return None


def carrier_ports(source: Source, donor: dict, frontend: dict | None = None, *, max_depth: int = 16) -> list[dict]:
    """Keep a leaf's exact literal-container path when locating actual slots.

    Dictionary keys, computed fields, spreads, arithmetic, indexing and function
    calls are never transparent carriers. Aliased containers require the
    frontend's unambiguous source binding origin, not a may-dependence edge.
    """
    if max_depth < 1 or donor.get("diagnostic") or donor.get("role") == "diagnostic":
        return []
    leaf = _node_for(source, donor)
    if leaf is None:
        return []
    root, steps = leaf, []
    for _ in range(max_depth):
        step = _container_step(source, root)
        if step is None:
            break
        root, part = step
        if part is not None:
            steps.insert(0, part)
    else:
        return []
    direct = [dict(p, structural_path=[], carrier_span=donor["span"], carrier_kind="whole_argument")
              for p in _root_ports(source, donor)]
    if not steps:
        return direct
    root_span = _span(source, root)
    ports = []
    if donor.get("call_context"):
        port = donor["call_context"]
        actual = _node_for(source, {"span": port["argument_span"]})
        if actual is not None and actual.type == "keyword_argument":
            actual = child(actual, "value")
        if actual == root:
            ports.append(dict(port, carrier_kind="literal_argument"))
    if frontend:
        bindings = {b["id"]: b for b in frontend.get("bindings", [])}
        for call in frontend.get("calls", []):
            if call.get("test_id") != donor.get("test_id") or call.get("role") != "operation":
                continue
            for arg in call.get("arguments", []):
                binding = arg.get("binding") or {}
                origin = bindings.get(binding.get("origin_binding_id"))
                same_actual = _same_span(arg["span"], root_span)
                same_binding = (origin is not None and not origin.get("contexts")
                                and binding.get("resolution") == "local_value_binding"
                                and _same_span((origin.get("value") or {}).get("span"), root_span))
                if not same_actual and not same_binding:
                    continue
                ports.append({"callee": call["callee"], "callee_identity": call["callee_identity"],
                              "argument_slot": arg["slot"], "keyword": arg.get("keyword"),
                              "call_span": call["span"], "argument_span": arg["argument_span"],
                              "carrier_kind": "literal_argument" if same_actual else "source_bound_literal",
                              "binding_id": origin["id"] if same_binding else None})
    unique = {}
    for port in ports:
        enriched = dict(port, structural_path=steps, carrier_span=root_span, leaf_span=donor["span"],
                        dependence="source_literal_container_path", runtime_container_state="unknown")
        unique.setdefault((structural_slot_key(enriched), _position(port["call_span"])), enriched)
    return list(unique.values())
