"""Source-derived argument and testing-failure summaries for role analysis.

An optional variadic diagnostic tail does not make fixed explicit parameters
unresolvable.  Only that prefix is bound; an expanded or otherwise unknown tail
is never assigned fabricated values.  Failure wrappers are discovered by a
declared standard ``testing`` receiver and terminal failure dispatch, regardless
of helper/API names.  These summaries describe failure reachability on normal
completion, not absence of side effects or a required production behavior.
"""
from __future__ import annotations

from anchor_retrieval.graph import _locally_rebound
from anchor_retrieval.syntax import ATTRS, CALLS, FUNCTIONS, attr_parts, call_parts, child, walk
from generic_composition.corpus import span
from relational_gap.frontend import _parameters


VERSION = "source_testing_failure_summaries.v1"
NESTED = FUNCTIONS | {"arrow_function", "function_expression", "func_literal", "lambda"}
TRUSTED = {"local_symbol", "package_symbol", "import_symbol"}
FAILURE_METHODS = {"Error", "Errorf", "Fatal", "Fatalf", "Fail", "FailNow"}


def _owned(node):
    yield node
    for part in node.named_children:
        if part.type not in NESTED:
            yield from _owned(part)


def _statements(body):
    statements = [part for part in body.named_children if part.type != "comment"]
    if len(statements) == 1 and statements[0].type == "statement_list":
        statements = [part for part in statements[0].named_children if part.type != "comment"]
    return statements


def bind_fixed_prefix(unit, args, caller):
    """Return explicit fixed formal bindings and a deliberately opaque tail.

    This internal AST API returns ``value_node`` plus ``origin`` (caller/callee)
    so a client can preserve its lexical environment.  Public summary records
    contain source spans, not AST objects. Dynamic expansion that may fill a
    fixed formal makes the complete binding unknown; no partial guess remains.
    """
    parameters = _parameters(unit)
    unknown = lambda reason: {"status": "unknown", "reason": reason, "bindings": [], "variadic_tail": []}
    if any(row["name"] is None for row in parameters):
        return unknown("unsupported_formal_pattern")
    variadic = [row for row in parameters if row["variadic"]]
    if len(variadic) > 1:
        return unknown("multiple_variadic_formals")
    fixed = [row for row in parameters if not row["variadic"]]
    positional = [row for row in fixed if not row["keyword_only"]]
    bound, position, tail = {}, 0, []
    for slot, argument in enumerate(args):
        if argument.type in {"dictionary_splat", "list_splat", "spread_element", "variadic_argument"}:
            if argument.type == "dictionary_splat" or not variadic or position < len(positional):
                return unknown("expansion_may_bind_fixed_formals")
            tail.append({"slot": slot, "span": span(caller, argument), "status": "expanded_tail_unknown"})
            continue
        if argument.type == "keyword_argument":
            name, value = caller.text(child(argument, "name")), child(argument, "value")
            row = next((row for row in fixed if row["name"] == name), None)
            if row is None or row["positional_only"]:
                return unknown("unsupported_keyword_binding")
        elif position < len(positional):
            row = positional[position]
            name, value = row["name"], argument
            position += 1
        elif variadic:
            tail.append({"slot": slot, "span": span(caller, argument), "status": "explicit_tail_uninterpreted"})
            continue
        else:
            return unknown("too_many_explicit_arguments")
        if value is None or name in bound:
            return unknown("duplicate_or_missing_binding")
        bound[name] = {"parameter": name, "parameter_index": row["index"], "value_node": value, "origin": "caller", "span": span(caller, value), "slot": slot}
    for row in fixed:
        if row["name"] in bound:
            continue
        if row["default"] is None:
            return unknown("missing_fixed_argument")
        position = row["default"]["span"]
        node = next((node for node in walk(unit.node) if node.start_byte == position["start_byte"] and node.end_byte == position["end_byte"]), None)
        if node is None:
            return unknown("default_expression_unavailable")
        bound[row["name"]] = {"parameter": row["name"], "parameter_index": row["index"], "value_node": node, "origin": "callee", "span": position, "slot": None}
    return {"status": "fixed_prefix" if variadic else "resolved", "bindings": [bound[row["name"]] for row in fixed], "variadic_tail": tail, "variadic_formals": [row["name"] for row in variadic]}


def _testing_parameter(unit, name):
    row = next((row for row in _parameters(unit) if row["name"] == name), None)
    if row is None or _locally_rebound(unit, name):
        return None
    typ = row["type"].lstrip("*").split(".")
    if len(typ) != 2 or typ[1] not in {"T", "B", "F", "TB"} or unit.source.imports.get(typ[0], (None,))[0] != "testing":
        return None
    return {"parameter": name, "parameter_index": row["index"], "declared_type": row["type"], "span": row["span"], "import_identity": "testing"}


def direct_testing_failure(unit, call):
    if unit.source.language != "go" or call.type not in CALLS:
        return None
    fn, _ = call_parts(call)
    if fn is None or fn.type not in ATTRS:
        return None
    receiver, method = attr_parts(fn)
    if receiver is None or receiver.type != "identifier" or unit.source.text(method) not in FAILURE_METHODS:
        return None
    parameter = _testing_parameter(unit, unit.source.text(receiver))
    if parameter is None:
        return None
    return {"kind": "standard_testing_failure", "method": unit.source.text(method), "receiver": parameter, "span": span(unit.source, call)}


def _last_call(body):
    statements = _statements(body)
    if not statements or statements[-1].type != "expression_statement":
        return None
    children = [part for part in statements[-1].named_children if part.type != "comment"]
    return children[0] if len(children) == 1 and children[0].type in CALLS else None


def _source_target(index, unit, call):
    fn, _ = call_parts(call)
    if fn is None:
        return None
    root = unit.source.text(fn).split(".")[0]
    if root in {row["name"] for row in _parameters(unit)} or _locally_rebound(unit, root):
        return None
    targets = [(uid, reason) for uid, reason in index.resolve(unit, unit.source.text(fn)) if reason in TRUSTED]
    return index.units[targets[0][0]] if len(targets) == 1 else None


def summarize_failure_wrappers(index, *, max_rounds=6):
    """Monotone summaries of wrappers that end in a testing failure sink.

    A syntactic early return, deferred dispatch, or ambiguous receiver prevents
    this summary. Opaque earlier actions are retained as a limitation: this is
    failure reachability on normal completion, not purity or total termination.
    """
    summaries = {}
    for _ in range(max_rounds):
        added = {}
        for uid, unit in sorted(index.units.items()):
            if uid in summaries or unit.source.language != "go":
                continue
            if any(node.type in {"return_statement", "defer_statement", "go_statement"} for node in _owned(unit.body)):
                continue
            call = _last_call(unit.body)
            if call is None:
                continue
            direct = direct_testing_failure(unit, call)
            if direct is not None:
                sink = direct
            else:
                target = _source_target(index, unit, call)
                if target is None or target.id not in summaries:
                    continue
                _, args = call_parts(call)
                bound = bind_fixed_prefix(target, args, unit.source)
                if bound["status"] == "unknown":
                    continue
                receiver_name = summaries[target.id]["receiver"]["parameter"]
                binding = next((row for row in bound["bindings"] if row["parameter"] == receiver_name), None)
                if binding is None or binding["origin"] != "caller" or binding["value_node"].type != "identifier":
                    continue
                receiver = _testing_parameter(unit, unit.source.text(binding["value_node"]))
                if receiver is None:
                    continue
                sink = {"kind": "source_failure_wrapper_forward", "callee_id": target.id, "receiver": receiver, "span": span(unit.source, call), "callee_proof": summaries[target.id]}
            added[uid] = {"version": VERSION, "function_id": uid, "function_span": span(unit.source, unit.node), "receiver": sink["receiver"], "sink": sink, "basis": "terminal_failure_on_normal_completion_no_early_return", "effect_precision": "opaque_prior_effects_and_termination_unknown"}
        if not added:
            break
        summaries.update(added)
    return summaries


def failure_guard_constraints(index, unit, summaries):
    """Return lexical guards whose branch ends in a source-proved failure sink.

    Comparison operands are symmetric and carry no actual/expected role. This
    API deliberately does not label a formal named 'expected' as an oracle.
    ``guard_node`` / ``operand_nodes`` are internal AST objects for role tracing.
    """
    result = []
    for statement in _owned(unit.body):
        if statement.type != "if_statement" or child(statement, "alternative") is not None:
            continue
        guard, body = child(statement, "condition"), child(statement, "consequence")
        if guard is None or body is None or any(node.type in {"return_statement", "defer_statement", "go_statement"} for node in _owned(body)):
            continue
        call = _last_call(body)
        if call is None:
            continue
        sink = direct_testing_failure(unit, call)
        if sink is None:
            target = _source_target(index, unit, call)
            if target is None or target.id not in summaries:
                continue
            _, args = call_parts(call)
            bindings = bind_fixed_prefix(target, args, unit.source)
            if bindings["status"] == "unknown":
                continue
            receiver_name = summaries[target.id]["receiver"]["parameter"]
            binding = next((row for row in bindings["bindings"] if row["parameter"] == receiver_name), None)
            if binding is None or binding["value_node"].type != "identifier" or _testing_parameter(unit, unit.source.text(binding["value_node"])) is None:
                continue
            sink = {"kind": "source_failure_wrapper", "function_id": target.id, "call_span": span(unit.source, call), "proof": summaries[target.id]}
        operands = [child(guard, "left"), child(guard, "right")] if guard.type == "binary_expression" else [guard]
        operator = unit.source.text(child(guard, "operator")) if guard.type == "binary_expression" else None
        inverse = {"==": "!=", "!=": "==", "<": ">=", "<=": ">", ">": "<=", ">=": "<"}.get(operator)
        result.append({"guard_node": guard, "operand_nodes": [node for node in operands if node is not None], "statement_span": span(unit.source, statement), "guard_span": span(unit.source, guard), "guard_text": unit.source.text(guard), "guard_operator": operator, "passing_relation": inverse, "role_precision": "symmetric_operands_no_oracle_direction", "execution_precision": "lexical_branch_not_proved_executed", "required_passing_condition": "guard_falsy_on_normal_completion", "sink": sink})
    return result
