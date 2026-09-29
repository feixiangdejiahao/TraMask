"""Bounded Go construction-prefix candidates, not semantics-preserving slices.

The criterion is the expression transported by an owner-prefix edit.  Follow
its reaching definitions, then retain operations touching the resulting local
resources or their owner from the resources' construction onward.  Earlier
owner calls have unknown effects: dropping them proposes a *new construction*,
and the receipt says so.  Syntactically visible owner writes are retained even
before construction.  No API names, trial names, expected values, or model are
used.  Branches, closures, and indirect lvalues are deliberately unsupported.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Iterable

from anchor_retrieval.syntax import CALLS, Source, attr_parts, call_parts, child, walk


VERSION = "bounded-owner-construction-v1"
_HEADER = "package prefixslice\nfunc candidate() {\n"
_CONTROL = {"if_statement", "for_statement", "expression_switch_statement",
            "type_switch_statement", "select_statement", "go_statement",
            "defer_statement", "labeled_statement", "goto_statement",
            "func_literal", "send_statement", "receive_statement", "block"}


def _root(source, node):
    if node is None:
        return None
    if node.type == "identifier":
        return source.text(node)
    if node.type == "selector_expression":
        return _root(source, attr_parts(node)[0])
    if node.type in {"index_expression", "slice_expression"}:
        return _root(source, child(node, "operand"))
    return None


def _refs(source, node):
    return {source.text(n) for n in walk(node) if n.type == "identifier"
            and source.text(n) != "_"}


def _definitions(source, statement):
    if statement.type not in {"short_var_declaration", "assignment_statement"}:
        return set(), None
    left, right = child(statement, "left"), child(statement, "right")
    if left is None or right is None:
        return set(), None
    names = list(left.named_children) if left.type == "expression_list" else [left]
    return {source.text(n) for n in names if n.type == "identifier" and source.text(n) != "_"}, right


def _write_roots(source, node):
    result = set()
    for part in walk(node):
        if part.type == "assignment_statement":
            left = child(part, "left")
            for item in left.named_children if left is not None else []:
                if item.type != "identifier" and _root(source, item):
                    result.add(_root(source, item))
        elif part.type in {"inc_statement", "dec_statement"}:
            operand = next(iter(part.named_children), None)
            if operand is not None and operand.type != "identifier" and _root(source, operand):
                result.add(_root(source, operand))
    return result


def receiver_write_evidence(sources: Iterable[Source]):
    """May-write evidence only; absence is never interpreted as purity.

    A same-named method is a possible target, not a proven type resolution.
    Keeping such a call is conservative.  The receipt includes exact method
    positions.  Calls, aliases, reflection, and synchronization can have further
    effects; this intentionally small prototype does not infer their absence.
    """
    evidence = {}
    for source in sources:
        if source.language != "go":
            continue
        for node in source.root.named_children:
            if node.type != "method_declaration":
                continue
            receiver, name, body = child(node, "receiver"), child(node, "name"), child(node, "body")
            if receiver is None or name is None or body is None:
                continue
            parameter = next(iter(receiver.named_children), None)
            identifier = child(parameter, "name") if parameter is not None else None
            if identifier is None or source.text(identifier) not in _write_roots(source, body):
                continue
            evidence.setdefault(source.text(name), []).append({
                "path": source.path, "start_byte": node.start_byte, "end_byte": node.end_byte,
                "source_sha256": hashlib.sha256(source.data).hexdigest(),
                "basis": "possible_same_named_method_directly_writes_receiver",
            })
    return evidence


def slice_prefix(prefix: str, binding: str, *, sources: Iterable[Source] = ()) -> dict:
    """Return one bounded construction proposal and an auditable receipt.

    Byte positions in the receipt address ``prefix`` itself, not a fabricated
    repository span.  Unknown incoming-owner history is explicitly recorded.
    Unsupported control flow returns ``status=unknown`` with no new prefix.
    """
    offset = len(_HEADER.encode())
    source = Source("__owner_prefix.go", _HEADER + prefix + "\n}\n", "go")
    binding_source = Source("__criterion.go", _HEADER + "_ = " + binding + "\n}\n", "go")
    result = {"version": VERSION, "status": "unknown", "prefix": None,
              "criterion": binding, "retained": [], "removed": [], "unknown": [],
              "claim": "bounded_new_construction_not_semantic_equivalence",
              "dependency_complete": False}
    if source.root.has_error or binding_source.root.has_error:
        result["unknown"].append({"reason": "parse_error"})
        return result
    function = next(n for n in source.root.named_children if n.type == "function_declaration")
    block = child(function, "body")
    listing = next((n for n in block.named_children if n.type == "statement_list"), None)
    statements = list(listing.named_children) if listing is not None else []
    statements = [n for n in statements if n.type != "comment"]
    unsupported = [n for statement in statements for n in walk(statement)
                   if n.type in _CONTROL or n.type in {"ERROR", "var_declaration"}]
    # A pointer write may establish state through an alias we cannot track.
    for statement in statements:
        if statement.type == "assignment_statement":
            left = child(statement, "left")
            if left is not None and any(n.type == "unary_expression" for n in walk(left)):
                unsupported.append(statement)
    if unsupported:
        result["unknown"] = [{"reason": "unsupported_control_or_alias",
                              "node_type": n.type, "start_byte": n.start_byte - offset,
                              "end_byte": n.end_byte - offset} for n in unsupported]
        return result

    facts = []
    for index, statement in enumerate(statements):
        defined, rhs = _definitions(source, statement)
        calls = []
        for call in walk(statement):
            if call.type not in CALLS:
                continue
            fn, arguments = call_parts(call)
            receiver, member = attr_parts(fn) if fn is not None and fn.type == "selector_expression" else (None, None)
            calls.append({"receiver": _root(source, receiver),
                          "method": source.text(member) if member is not None else None,
                          "args": set().union(*(_refs(source, a) for a in arguments)) if arguments else set(),
                          "start_byte": call.start_byte - offset,
                          "end_byte": call.end_byte - offset})
        facts.append({"node": statement, "defs": defined, "reads": _refs(source, rhs or statement),
                      "rhs": rhs, "calls": calls, "writes": _write_roots(source, statement)})

    criterion = next(n for n in walk(binding_source.root) if n.type == "assignment_statement")
    needed = _refs(binding_source, child(criterion, "right"))
    selected, reasons, resources = set(), {}, set()

    def keep(index, reason):
        selected.add(index)
        reasons.setdefault(index, set()).add(reason)

    # Reaching definitions in this straight-line prefix.  Visiting a statement
    # introduces only its preceding definitions; later reassignments do not
    # masquerade as the value consumed earlier.
    def dependencies(names, before):
        for name in sorted(names):
            definition = next((i for i in range(before - 1, -1, -1) if name in facts[i]["defs"]), None)
            if definition is None:
                continue
            fresh = definition not in selected
            keep(definition, "reaching_definition")
            if fresh:
                dependencies(facts[definition]["reads"], definition)

    dependencies(needed, len(facts))
    local_names = set().union(*(fact["defs"] for fact in facts)) if facts else set()

    def extend_resources():
        for index in selected:
            for call in facts[index]["calls"]:
                if call["receiver"]:
                    resources.add(call["receiver"])
                resources.update(call["args"] & local_names)

    extend_resources()
    # Direct aliases to tracked resources extend object identity conservatively.
    changed = True
    while changed:
        changed = False
        for index, fact in enumerate(facts):
            rhs = fact["rhs"]
            values = list(rhs.named_children) if rhs is not None and rhs.type == "expression_list" else [rhs]
            if len(values) == 1 and values[0] is not None and values[0].type == "identifier":
                target = source.text(values[0])
                linked = fact["defs"] | {target}
                if linked & resources and not linked <= resources:
                    resources.update(linked)
                    changed = True

    resource_definitions = {i for i, fact in enumerate(facts) if fact["defs"] & resources}
    anchor = min(resource_definitions) if resource_definitions else 0
    result["construction_anchor_statement"] = anchor
    result["resources"] = sorted(resources)
    write_evidence = receiver_write_evidence(sources)
    # State closure deliberately includes calls whose returned value is unused,
    # including calls nested inside checks and resource retirement after reading.
    changed = True
    while changed:
        old = set(selected)
        old_resources = set(resources)
        companion_values = set().union(*(facts[i]["defs"] for i in selected
                                       if len(facts[i]["defs"]) > 1)) if selected else set()
        for index, fact in enumerate(facts):
            touches = [c for c in fact["calls"]
                       if c["receiver"] in resources or c["args"] & resources]
            direct_write = bool(fact["writes"] & resources)
            known_write = [c for c in touches if c["receiver"] in resources and c["method"] in write_evidence]
            if direct_write:
                keep(index, "direct_resource_write")
            elif known_write:
                keep(index, "possible_callee_receiver_write")
            elif touches and index >= anchor:
                keep(index, "call_on_live_resource_or_resource_argument")
            elif fact["calls"] and fact["reads"] & companion_values:
                keep(index, "use_of_companion_return_value")
            if index in selected:
                dependencies(fact["reads"], index)
        extend_resources()
        changed = old != selected or old_resources != resources

    chunks = []
    for index, fact in enumerate(facts):
        node = fact["node"]
        receipt = {"statement": index, "start_byte": node.start_byte - offset,
                   "end_byte": node.end_byte - offset, "code": source.text(node)}
        if index in selected:
            receipt["reasons"] = sorted(reasons[index])
            matched = {c["method"] for c in fact["calls"] if c["receiver"] in resources and c["method"] in write_evidence}
            if matched:
                receipt["write_evidence"] = {m: write_evidence[m] for m in sorted(matched)}
            result["retained"].append(receipt)
            chunks.append(source.text(node))
        else:
            related = [c for c in fact["calls"] if c["receiver"] in resources or c["args"] & resources]
            receipt["reason"] = "preconstruction_owner_effect_unknown" if related else "outside_local_value_and_resource_closure"
            result["removed"].append(receipt)
            if related:
                result["unknown"].append({"statement": index, "reason": "removed_owner_call_may_change_state_block_or_fail",
                                          "calls": [{k: v for k, v in c.items() if k != "args"} for c in related]})
    if any(fact["calls"] for fact in facts):
        result["unknown"].append({"reason": "heap_aliases_global_effects_and_interprocedural_dependencies_not_proven_complete"})
    result["status"] = "proposed" if result["removed"] else "unchanged"
    result["prefix"] = "\n" + "\n".join(chunks) + "\n"
    return result


def propose_candidate(candidate: dict, *, sources: Iterable[Source] = ()) -> dict:
    """Return ``{candidate, analysis}``; the parent is never mutated or replaced."""
    prefixes = [e for e in candidate.get("edits", []) if e.get("role") == "state_prefix"]
    bindings = [e for e in candidate.get("edits", []) if e.get("role") == "binding"]
    if len(prefixes) != 1 or len(bindings) != 1:
        return {"candidate": None, "analysis": {"status": "unknown", "reason": "requires_one_prefix_and_one_binding"}}
    analysis = slice_prefix(prefixes[0]["after"], bindings[0]["after"], sources=sources)
    if analysis["status"] != "proposed":
        return {"candidate": None, "analysis": analysis}
    proposed = deepcopy(candidate)
    for edit in proposed["edits"]:
        if edit.get("role") == "state_prefix":
            edit["after"] = analysis["prefix"]
    old_id = candidate["id"]
    identifier = hashlib.sha256(json.dumps([VERSION, old_id, proposed["edits"]], sort_keys=True).encode()).hexdigest()[:20]
    proposed.update(id=identifier, static_parent_id=old_id, generator=VERSION,
                    operator="bounded_owner_prefix_rebind", generated_test_name="rs_" + identifier)
    proposed["prefix_slice"] = {"parent_id": old_id, "analysis": analysis,
                                "equivalence_claim": False,
                                "status": "requires_independent_construction_and_oracle_review"}
    proposed.pop("equivalence_key", None)
    proposed["search_shape"] = {"operator": "bounded_owner_prefix_rebind", "profile": []}
    return {"candidate": proposed, "analysis": analysis}
