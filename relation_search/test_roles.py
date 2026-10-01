"""Source-only actual/expected roles and narrow oracle contradiction checks.

The analysis starts at primitive assertion boundaries, follows unique local
definitions and source-resolved actual/formal bindings, and follows callback
returns.  Function and variable names do not decide their oracle role.  A role
is a value-use fact, not a specification: opaque calls, control-dependent
definitions, mutation, and callback scheduling remain explicit uncertainties.

``analyze(corpus, frontend, candidate)`` reparses the complete candidate.  It
returns ``invalid`` only for a closed, built-in equality contradiction.  An
input-labelled edit confined to expected construction is a review obligation:
it could be an incorrect mutation or a legitimate strengthening of the oracle.
In particular an
empty finding list is never a proof that the test is valid.  No target code,
provider, issue text, reference implementation, or semantic labels are used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json

from anchor_retrieval.graph import _locally_rebound
from anchor_retrieval.index import Index
from anchor_retrieval.syntax import (
    CALLS, FUNCTIONS, Source, Unit, call_parts, child, literal, walk,
)
from generic_composition.corpus import ASSIGNMENTS, _assertion_nodes, span
from relation_search.oracle_evidence import _modified_sources
from relation_search.test_role_summaries import (
    bind_fixed_prefix, failure_guard_constraints, summarize_failure_wrappers,
)
from relational_gap.frontend import _parameters


VERSION = "test_value_roles.v3"
NESTED = FUNCTIONS | {"arrow_function", "function_expression", "func_literal", "lambda"}
TRUSTED = {"local_symbol", "package_symbol", "import_symbol"}
WRAPPERS = {"parenthesized_expression", "expression_list", "type_assertion", "as_expression"}
CONTAINERS = {"list", "tuple", "set", "dictionary", "array", "object", "composite_literal", "literal_value"}
EQUALITY = {"==", "===", "Equal", "Same", "toBe", "toEqual", "toStrictEqual", "strictEqual", "deepEqual", "deepStrictEqual", "assertEqual"}
CONTROL = {"if_statement", "for_statement", "for_in_statement", "while_statement", "try_statement", "with_statement", "switch_statement", "expression_switch_statement", "case_statement", "conditional_expression", "ternary_expression"}
GUARD_CONTEXTS = CONTROL | {"type_switch_statement", "type_case", "select_statement", "communication_case", "expression_case", "default_case", "except_clause", "catch_clause", "finally_clause", "else_clause", "elif_clause", "for_clause"}


def _inside(inner, outer):
    return inner["path"] == outer["path"] and outer["start_byte"] <= inner["start_byte"] <= inner["end_byte"] <= outer["end_byte"]


def _overlap(left, right):
    return left["path"] == right["path"] and max(left["start_byte"], right["start_byte"]) < min(left["end_byte"], right["end_byte"])


def _owned(node):
    yield node
    for part in node.named_children:
        if part.type not in NESTED:
            yield from _owned(part)


def _unwrap(node):
    while node is not None and node.type in WRAPPERS and len(node.named_children) == 1:
        node = node.named_children[0]
    return node


def _guard_contexts(source, node, boundary):
    """Retain conditions and exceptional phases without assuming execution."""
    result = []
    current = node.parent
    while current is not None and current != boundary:
        if current.type in GUARD_CONTEXTS | NESTED:
            branch = next((current.field_name_for_child(index) or part.type for index, part in enumerate(current.children) if part.start_byte <= node.start_byte and node.end_byte <= part.end_byte), None)
            condition = child(current, "condition")
            body = child(current, "body", "consequence")
            header = source.data[current.start_byte:body.start_byte].decode() if body is not None else None
            result.append({"kind": current.type, "span": span(source, current), "branch": branch, "condition_span": span(source, condition) if condition is not None else None, "condition_text": source.text(condition) if condition is not None else None, "header": header, "execution_precision": "lexical_context_not_proved_executed"})
        current = current.parent
    return list(reversed(result))


@dataclass
class _Context:
    unit: Unit
    bindings: dict = field(default_factory=dict)
    path: tuple = ()
    parent: "_Context | None" = None


@dataclass
class _Ref:
    node: object
    context: _Context


class _Analysis:
    def __init__(self, sources, root, changes, *, max_depth, max_contexts):
        self.index = Index(sources, "")
        # The original Unit adapter loses grouped Go parameter names.  Use the
        # explicit parameter rows for binding; never guess from argument count.
        for unit in self.index.units.values():
            unit.params = [row["name"] for row in _parameters(unit) if row["name"]]
        self.root, self.changes = root, changes
        self.max_depth, self.max_contexts = max_depth, max_contexts
        self.roles, self.findings, self.unknowns, self.assertions = [], [], [], []
        self.contexts = 0
        self.node_maps = {}
        self.module_conflicts = {}
        self.failure_wrappers = summarize_failure_wrappers(self.index)
        self.assertion_records = []
        self.guard_constraints = []
        self.binding_records = []

    def nodes(self, source):
        if source.path not in self.node_maps:
            self.node_maps[source.path] = {(node.start_byte, node.end_byte): node for node in walk(source.root)}
        return self.node_maps[source.path]

    def module_binding_conflict(self, source, name):
        key = (source.path, name)
        if key not in self.module_conflicts:
            self.module_conflicts[key] = any(
                node.type in ASSIGNMENTS | {"assignment_expression"}
                and any(source.text(part) == name for part in walk(child(node, "left", "name")) if part.type == "identifier")
                for node in _owned(source.root) if child(node, "left", "name") is not None
            )
        return self.module_conflicts[key]

    def unknown(self, code, context, node=None):
        self.unknowns.append({"code": code, "span": span(context.unit.source, node or context.unit.node), "call_path": list(context.path)})

    def role(self, ref, role, basis, path):
        if any(step["kind"] == "opaque_argument_may_use" for step in path):
            basis = "opaque_argument_may_use"
        if any(step["kind"] == "symmetric_failure_operand_may" for step in path):
            basis = "symmetric_failure_operand_may"
        self.roles.append({"role": role, "span": span(ref.context.unit.source, ref.node), "basis": basis, "provenance": path})

    def definition(self, ref):
        """Unique prior direct local definition, with no reassignment/escape.

        Nested scopes are deliberately excluded. Conditional writes and
        multiple writes are unknown instead of nearest-text reaching guesses.
        """
        node, context = ref.node, ref.context
        name, source = context.unit.source.text(node), context.unit.source
        definitions, unsafe = [], False
        for item in _owned(context.unit.body):
            if item.type in ASSIGNMENTS | {"assignment_expression", "augmented_assignment_expression"}:
                targets = item.children_by_field_name("name") if item.type in {"var_spec", "const_spec"} else []
                target = child(item, "left", "name")
                if not targets and target is not None:
                    targets = target.named_children if target.type in {"expression_list", "pattern_list"} else [target]
                if not any(target.type == "identifier" and source.text(target) == name for target in targets):
                    continue
                value = child(item, "right", "value")
                values = list(value.named_children) if value is not None and value.type == "expression_list" else [value]
                if len(targets) == len(values):
                    value = next(value for target, value in zip(targets, values) if source.text(target) == name)
                else:
                    value = None
                parent = item.parent
                controlled = False
                while parent is not None and parent != context.unit.body:
                    controlled |= parent.type in CONTROL
                    parent = parent.parent
                definitions.append((item, value, controlled))
            elif item.type in {"update_expression", "inc_statement", "dec_statement", "global_statement", "nonlocal_statement"}:
                unsafe |= any(source.text(part) == name for part in walk(item) if part.type == "identifier")
            elif item.type == "unary_expression" and source.text(item).lstrip().startswith("&"):
                unsafe |= any(source.text(part) == name for part in walk(item) if part.type == "identifier")
        if unsafe or len(definitions) != 1:
            return None
        definition, value, controlled = definitions[0]
        if controlled or value is None or definition.end_byte > node.start_byte:
            return None
        return _Ref(_unwrap(value), context)

    def resolve_ref(self, ref, seen=None):
        seen = set() if seen is None else seen
        ref = _Ref(_unwrap(ref.node), ref.context)
        if ref.node.type != "identifier":
            return ref
        key = (ref.context.unit.id, ref.node.start_byte, json.dumps(ref.context.path, sort_keys=True))
        if key in seen:
            return ref
        seen.add(key)
        name = ref.context.unit.source.text(ref.node)
        definition = self.definition(ref)
        if definition is not None:
            return self.resolve_ref(definition, seen)
        if name in ref.context.bindings:
            # A formal may be rebound before it is read.  Only an untouched
            # formal inherits its caller's value role.
            if _locally_rebound(ref.context.unit, name):
                return ref
            return self.resolve_ref(ref.context.bindings[name], seen)
        if ref.context.parent is not None and name not in ref.context.unit.params:
            return self.resolve_ref(_Ref(ref.node, ref.context.parent), seen)
        return ref

    def bind(self, unit, args, context, call):
        bindings = bind_fixed_prefix(unit, args, context.unit.source)
        if bindings["status"] == "unknown":
            self.unknown(bindings["reason"], context, call)
            return None
        bound = {row["parameter"]: _Ref(row["value_node"], context if row["origin"] == "caller" else _Context(unit)) for row in bindings["bindings"]}
        site = {"call_span": span(context.unit.source, call), "caller_unit": context.unit.id, "guard_contexts": _guard_contexts(context.unit.source, call, context.unit.body)}
        if bindings["status"] == "fixed_prefix":
            self.binding_records.append({"call_span": span(context.unit.source, call), "callee_id": unit.id, "status": "fixed_prefix_variadic_tail_uninterpreted", "fixed_bindings": [{key: value for key, value in row.items() if key != "value_node"} for row in bindings["bindings"]], "variadic_tail": bindings["variadic_tail"]})
        return _Context(unit, bound, context.path + (site,))

    def callee(self, ref):
        node, context = ref.node, ref.context
        fn, args = call_parts(node)
        if fn is None:
            return None
        if fn.type == "identifier":
            target = self.resolve_ref(_Ref(fn, context))
            if target.node.type in NESTED:
                source = target.context.unit.source
                body = child(target.node, "body")
                if body is None:
                    return None
                unit = Unit(source, target.node, body, "<callback>")
                unit.params = [row["name"] for row in _parameters(unit) if row["name"]]
                nested = self.bind(unit, args, context, node)
                if nested is not None:
                    nested.parent = target.context
                return nested
            if fn.type == "identifier" and (_locally_rebound(context.unit, context.unit.source.text(fn)) or context.unit.source.text(fn) in context.unit.params):
                return None
        root_name = context.unit.source.text(fn).split(".")[0]
        if self.module_binding_conflict(context.unit.source, root_name):
            self.unknown("source_callee_binding_modified", context, node)
            return None
        targets = [(uid, reason) for uid, reason in self.index.resolve(context.unit, context.unit.source.text(fn)) if reason in TRUSTED]
        if len(targets) != 1:
            return None
        unit = self.index.units[targets[0][0]]
        return self.bind(unit, args, context, node)

    def returns(self, context):
        body = context.unit.body
        if body.type not in {"block", "statement_block", "statement_list"}:
            return [body]  # TS concise arrow / Python lambda.
        result = []
        for node in _owned(body):
            if node.type == "return_statement":
                values = [part for part in node.named_children if part.type != "comment"]
                result.extend(values)
        return result

    def trace(self, ref, role, provenance, depth=0, seen=None):
        if ref.node is None:
            return
        seen = set() if seen is None else seen
        node, context = _unwrap(ref.node), ref.context
        ref = _Ref(node, context)
        key = (context.unit.id, node.start_byte, node.end_byte, role, json.dumps(context.path, sort_keys=True))
        if key in seen:
            return
        seen.add(key)
        self.role(ref, role, "assertion_value_use", provenance)
        if depth >= self.max_depth:
            self.unknown("role_depth_budget", context, node)
            return
        if node.type == "identifier":
            resolved = self.resolve_ref(ref)
            if resolved.node != node or resolved.context != context:
                self.trace(resolved, role, provenance + [{"kind": "unique_definition_or_formal_binding", "span": span(context.unit.source, node)}], depth + 1, seen)
            elif context.unit.source.text(node) not in context.unit.params:
                self.unknown("unresolved_value_definition", context, node)
            return
        if node.type in CALLS:
            callee = self.callee(ref)
            if callee is not None:
                for value in self.returns(callee):
                    self.trace(_Ref(value, callee), role, provenance + [{"kind": "source_resolved_return", "span": span(context.unit.source, node)}], depth + 1, seen)
            # The complete call expression is an expected construction region,
            # but no input-to-return dependence or purity is assumed for opaque
            # callees.  Its contained edits therefore require semantic review.
            if callee is None:
                self.unknown("opaque_value_call", context, node)
                _, args = call_parts(node)
                for argument in args:
                    value = child(argument, "value") if argument.type == "keyword_argument" else argument
                    self.trace(_Ref(value, context), role, provenance + [{"kind": "opaque_argument_may_use", "span": span(context.unit.source, node)}], depth + 1, seen)
            return
        if node.type in NESTED:
            # A function value is not its returned value. It is followed only
            # at a source-proved invocation through its formal binding.
            return
        for part in node.named_children:
            if part.type in {"type_identifier", "property_identifier", "field_identifier", "comment"}:
                continue
            self.trace(_Ref(part, context), role, provenance, depth + 1, seen)

    def type_fact(self, ref, seen=None):
        seen = set() if seen is None else seen
        resolved = self.resolve_ref(ref)
        node, context = resolved.node, resolved.context
        key = (context.unit.id, node.start_byte, json.dumps(context.path, sort_keys=True))
        if key in seen:
            return None
        seen.add(key)
        source, text = context.unit.source, context.unit.source.text(node)
        proof = [{"kind": "expression_type", "span": span(source, node), "text": text}]
        try:
            value = literal(text)
            kind = {bool: "bool", int: "number", float: "number", str: "string", bytes: "bytes", type(None): "nil", list: "list", tuple: "tuple", dict: "dict", set: "set"}.get(type(value))
            if kind:
                if source.language == "typescript" and kind == "list":
                    kind = "array"
                return {"type": kind, "provenance": proof}
        except ValueError:
            pass
        if source.language == "typescript" and node.type in {"array", "object"}:
            return {"type": node.type, "provenance": proof}
        if node.type in CALLS:
            fn, args = call_parts(node)
            if fn is not None and fn.type == "identifier" and source.text(fn) == "len" and len(args) == 1 and source.language in {"python", "go"} and self.builtin_unshadowed(context, "len"):
                return {"type": "number", "provenance": proof + [{"kind": "unshadowed_language_builtin", "symbol": "len"}]}
            # A production function's current return body may itself be the
            # bug: f currently returning 3 does not invalidate assert f()==[].
            # Role propagation follows returns, but oracle invalidity never
            # derives an ACTUAL type from the candidate implementation.
        return None

    def builtin_unshadowed(self, context, name):
        parent = context.parent
        while parent is not None:
            if name in parent.unit.params or _locally_rebound(parent.unit, name):
                return False
            parent = parent.parent
        if name in context.unit.params or name in context.unit.source.imports or _locally_rebound(context.unit, name):
            return False
        for node in walk(context.unit.source.root):
            if node.type in FUNCTIONS and context.unit.source.text(child(node, "name")) == name:
                return False
            if node.type in ASSIGNMENTS | {"assignment_expression"}:
                targets = node.children_by_field_name("name") if node.type in {"var_spec", "const_spec"} else []
                target = child(node, "left", "name")
                if not targets and target is not None:
                    targets = [target]
                if any(context.unit.source.text(part) == name for target in targets for part in walk(target) if part.type == "identifier"):
                    return False
        return True

    def assertion_supported(self, context, statement, assertion):
        source = context.unit.source
        if assertion.predicate == "assertion_helper":
            return False
        if source.language == "python":
            return statement is not None and statement.type == "assert_statement"
        if assertion.assertion_adapter == "go_testing_failure_guard":
            return True
        if assertion.assertion_adapter == "node_assert_import":
            fn, _ = call_parts(statement)
            return not self.module_binding_conflict(source, source.text(fn).split(".")[0])
        if statement is None or statement.type not in CALLS:
            return False
        fn, _ = call_parts(statement)
        text = source.text(fn)
        if source.language == "go":
            root = text.split(".")[0]
            imported = source.imports.get(root)
            return imported is not None and imported[0] in {"github.com/stretchr/testify/require", "github.com/stretchr/testify/assert"} and not _locally_rebound(context.unit, root) and not self.module_binding_conflict(source, root)
        expects = [node for node in walk(fn) if node.type in CALLS and source.text(call_parts(node)[0]) == "expect"]
        if not expects or "expect" in context.unit.params or _locally_rebound(context.unit, "expect"):
            return False
        imported = source.imports.get("expect")
        return imported is not None and imported[0] in {"vitest", "@jest/globals"} and imported[1] == "expect" and not self.module_binding_conflict(source, "expect")

    def contradiction(self, context, statement, actual, expected, predicate):
        if actual is None or expected is None or predicate not in EQUALITY:
            return
        left, right = self.type_fact(_Ref(actual, context)), self.type_fact(_Ref(expected, context))
        if not left or not right or left["type"] == right["type"]:
            return
        # Python bools compare equal to numbers; Go named types and JS loose
        # equality require more semantics than this narrow check supports.
        if context.unit.source.language == "python" and {left["type"], right["type"]} <= {"bool", "number"}:
            return
        if context.unit.source.language == "typescript" and predicate in {"deepEqual"}:
            return
        guards = _guard_contexts(context.unit.source, statement, context.unit.body)
        guarded = bool(guards) or any(site.get("guard_contexts") for site in context.path)
        self.findings.append({"code": "equality_type_contradiction", "severity": "review" if guarded else "invalid", "span": span(context.unit.source, statement), "predicate": predicate, "actual_type": left["type"], "expected_type": right["type"], "provenance": left["provenance"] + right["provenance"], "edit_ids": [], "guard_contexts": guards, "call_path": list(context.path), "applicability": "only_if_assertion_executes_normally"})

    def imported_assertions(self, context):
        """Primitive assertion positions follow imported identity, not alias.

        Existing Flow recognizes a few conventional spellings. This adapter
        handles arbitrary import aliases without treating a subject's same-
        spelling method as a framework assertion.
        """
        source = context.unit.source
        for node in _owned(context.unit.body):
            if node.type not in CALLS:
                continue
            fn, args = call_parts(node)
            if fn is None:
                continue
            text = source.text(fn)
            if source.language == "go":
                parts = text.split(".")
                if len(parts) != 2 or len(args) < 3:
                    continue
                root, method = parts
                imported = source.imports.get(root)
                if imported is not None and imported[0] in {"github.com/stretchr/testify/require", "github.com/stretchr/testify/assert"} and root not in context.unit.params and not _locally_rebound(context.unit, root) and not self.module_binding_conflict(source, root) and method in {"Equal", "NotEqual", "Same", "NotSame"}:
                    yield node, args[2], args[1], method
            elif source.language == "typescript" and len(args) == 1:
                for inner in walk(fn):
                    if inner.type not in CALLS:
                        continue
                    receiver, values = call_parts(inner)
                    name = source.text(receiver)
                    imported = source.imports.get(name)
                    if receiver is None or receiver.type != "identifier" or len(values) != 1 or imported is None or imported[0] not in {"vitest", "@jest/globals"} or imported[1] != "expect" or name in context.unit.params or _locally_rebound(context.unit, name) or self.module_binding_conflict(source, name):
                        continue
                    method = source.text(child(fn, "property"))
                    if method not in {"toBe", "toEqual", "toStrictEqual"}:
                        continue
                    negated = any(part.type == "member_expression" and source.text(child(part, "property")) == "not" for part in walk(fn))
                    yield node, values[0], args[0], "not:" + method if negated else method

    def closed_operand(self, ref):
        """Orient a symmetric comparison only from a closed test value.

        Production return bodies do not orient an oracle. A literal anonymous
        callback with a single closed return is a test value construction,
        however, and can be followed without treating subject behavior as a
        specification. Effectful/conditional callbacks remain unoriented.
        """
        resolved = self.resolve_ref(ref)
        if self.closed(resolved.node):
            return True
        if resolved.node.type not in CALLS:
            return False
        callee = self.callee(resolved)
        if callee is None or callee.unit.node.type not in {"lambda", "arrow_function", "function_expression", "func_literal"}:
            return False
        body = callee.unit.body
        if body.type in {"block", "statement_block", "statement_list"}:
            statements = [part for part in body.named_children if part.type != "comment"]
            if len(statements) == 1 and statements[0].type == "statement_list":
                statements = [part for part in statements[0].named_children if part.type != "comment"]
            if len(statements) != 1 or statements[0].type != "return_statement":
                return False
        returns = self.returns(callee)
        return len(returns) == 1 and self.closed(self.resolve_ref(_Ref(returns[0], callee)).node)

    def trace_pair(self, context, operands, path, *, directed):
        if directed:
            actual, expected = operands
            if actual is not None:
                self.trace(_Ref(actual, context), "actual", path)
            if expected is not None:
                self.trace(_Ref(expected, context), "expected", path)
            return "framework_argument_direction"
        closed = [self.closed_operand(_Ref(node, context)) for node in operands]
        if len(operands) == 2 and closed.count(True) == 1:
            for node, is_closed in zip(operands, closed):
                self.trace(_Ref(node, context), "expected" if is_closed else "actual", path)
            return "one_closed_operand_direction"
        symmetric = path + [{"kind": "symmetric_failure_operand_may", "basis": "no_source_proved_oracle_direction"}]
        for node in operands:
            self.trace(_Ref(node, context), "actual", symmetric)
            self.trace(_Ref(node, context), "expected", symmetric)
        return "symmetric_operands_both_may_roles"

    def visit(self, context, depth=0, ancestry=()):
        key = context.unit.id
        if depth > self.max_depth or self.contexts >= self.max_contexts or key in ancestry:
            self.unknown("call_context_budget_or_recursion", context)
            return
        self.contexts += 1
        flow = self.index.flow(context.unit.id) if context.unit.id in self.index.units else None
        assertions = [(*row, True) for row in self.imported_assertions(context)]
        if flow is not None:
            for assertion in flow.assertions:
                statement, actual, expected, predicate = _assertion_nodes(context.unit.source, assertion, context.unit)
                if not self.assertion_supported(context, statement, assertion):
                    continue
                if not any(row[0].start_byte == statement.start_byte and row[0].end_byte == statement.end_byte for row in assertions):
                    directed = assertion.assertion_adapter == "node_assert_import" or context.unit.source.language == "typescript"
                    assertions.append((statement, actual, expected, predicate, directed))
        for statement, actual, expected, predicate, directed in assertions:
            self.assertions.append(span(context.unit.source, statement))
            guards = _guard_contexts(context.unit.source, statement, context.unit.body)
            path = [{"kind": "assertion_boundary", "span": span(context.unit.source, statement), "call_path": list(context.path), "guard_contexts": guards}]
            precision = self.trace_pair(context, [actual, expected], path, directed=True) if expected is None or directed else self.trace_pair(context, [actual, expected], path, directed=False)
            self.assertion_records.append({"span": span(context.unit.source, statement), "predicate": predicate, "actual_span": span(context.unit.source, actual) if actual is not None else None, "expected_span": span(context.unit.source, expected) if expected is not None else None, "role_precision": precision, "guard_contexts": guards, "call_path": list(context.path), "execution_precision": "lexical_assertion_not_proved_executed"})
            self.contradiction(context, statement, actual, expected, predicate)
        for constraint in failure_guard_constraints(self.index, context.unit, self.failure_wrappers):
            if any(row["start_byte"] == constraint["statement_span"]["start_byte"] and row["end_byte"] == constraint["statement_span"]["end_byte"] and row["path"] == constraint["statement_span"]["path"] for row in self.assertions):
                continue
            guards = _guard_contexts(context.unit.source, constraint["guard_node"], context.unit.body)
            path = [{"kind": "source_failure_guard", "span": constraint["statement_span"], "call_path": list(context.path), "guard_contexts": guards, "failure_proof": constraint["sink"]}]
            precision = self.trace_pair(context, constraint["operand_nodes"], path, directed=False)
            self.guard_constraints.append({key: value for key, value in constraint.items() if key not in {"guard_node", "operand_nodes"}} | {"role_precision": precision, "guard_contexts": guards, "call_path": list(context.path)})
        for node in _owned(context.unit.body):
            if node.type in CALLS:
                callee = self.callee(_Ref(node, context))
                if callee is not None:
                    self.visit(callee, depth + 1, ancestry + (key,))

    def expected_edits(self):
        program = [change for change in self.changes if change["role"] not in {"semantic_expected", "relation_runtime_probe"} and change["before"] != change["after"]]
        classifications = {}
        for change in program:
            matching = [role for role in self.roles if _inside(change["span"], role["span"])]
            classifications[change["id"]] = matching
        expected_only = bool(program) and all(any(role["role"] == "expected" for role in classifications[change["id"]]) and not any(role["role"] == "actual" for role in classifications[change["id"]]) for change in program)
        escapes = self.expected_values_escape() if expected_only else False
        for change in self.changes:
            if change["role"] in {"semantic_expected", "relation_runtime_probe"} or change["before"] == change["after"]:
                continue
            # Roles are recomputed after edits; deleted/ambiguous constructions
            # receive no invented former role and remain unknown.
            matching = [role for role in self.roles if _inside(change["span"], role["span"])]
            expected = [role for role in matching if role["role"] == "expected"]
            actual = [role for role in matching if role["role"] == "actual"]
            if expected and not actual:
                source = self.index.sources[change["span"]["path"]]
                nodes = self.nodes(source)
                # A literal inside an opaque expected constructor is not a
                # proof that changing it cannot alter side effects. Require a
                # closed complete expected-value region, and no other program
                # input edit. Joint input/oracle changes stay reviewable.
                closed = expected_only and not escapes and any(role["basis"] != "opaque_argument_may_use" and self.closed(nodes[(role["span"]["start_byte"], role["span"]["end_byte"])]) for role in expected if (role["span"]["start_byte"], role["span"]["end_byte"]) in nodes)
                self.findings.append({"code": "expected_only_program_edit" if closed else "expected_construction_edited", "severity": "review", "span": change["span"], "edit_ids": [change["id"]], "provenance": expected})
            elif expected and actual:
                code = "ambiguous_oracle_role" if any(role["basis"] == "symmetric_failure_operand_may" for role in matching) else "shared_actual_expected_dependency_edited"
                self.findings.append({"code": code, "severity": "review", "span": change["span"], "edit_ids": [change["id"]], "provenance": matching})

    def expected_values_escape(self):
        """A value used as expected may also be an input to an earlier action.

        Backward value tracing alone cannot prove absence of that effect. Any
        uncovered lexical use of an expected identifier therefore downgrades
        the oracle-only claim to review, including uses inside diagnostics.
        """
        for role in self.roles:
            if role["role"] != "expected":
                continue
            position = role["span"]
            source = self.index.sources[position["path"]]
            node = self.nodes(source).get((position["start_byte"], position["end_byte"]))
            if node is None or node.type != "identifier":
                continue
            owner = node.parent
            while owner is not None and owner.type not in NESTED:
                owner = owner.parent
            if owner is None:
                return True
            body = child(owner, "body")
            if body is None:
                return True
            name = source.text(node)
            for use in _owned(body):
                if use.type != "identifier" or source.text(use) != name:
                    continue
                parent = use.parent
                binder = False
                while parent is not None and parent != body:
                    if parent.type in ASSIGNMENTS:
                        targets = parent.children_by_field_name("name") if parent.type in {"var_spec", "const_spec"} else []
                        target = child(parent, "left", "name")
                        if not targets and target is not None:
                            targets = [target]
                        binder = any(target.start_byte <= use.start_byte and use.end_byte <= target.end_byte for target in targets)
                        break
                    parent = parent.parent
                if not binder and not any(_inside(span(source, use), role["span"]) for role in self.roles):
                    return True
        return False

    @staticmethod
    def closed(node):
        try:
            # Called only after exact byte-node matching. Closed syntax is
            # checked structurally below; no expression is executed.
            if node.type in {"integer", "int_literal", "float", "float_literal", "number", "string", "interpreted_string_literal", "raw_string_literal", "true", "false", "none", "nil", "null"}:
                return True
            if node.type in CONTAINERS | WRAPPERS | {"pair", "keyed_element", "literal_element"}:
                return all(_Analysis.closed(part) for part in node.named_children if part.type not in {"property_identifier", "field_identifier", "type_identifier", "comment"})
        except (TypeError, AttributeError):
            pass
        return False


def _dedup(rows):
    return [row for _, row in sorted({json.dumps(row, sort_keys=True, ensure_ascii=True): row for row in rows}.items())]


def analyze(corpus, frontend, candidate, *, max_depth=8, max_contexts=160):
    """Return source-backed invalidity or review facts for one candidate.

    ``frontend`` is accepted for the shared admission API, but its old bindings
    are intentionally not reused after source edits.  All locations in ``roles``
    and ``findings`` refer to the full modified source; ``changes`` records both
    source versions.  Unknown is retained rather than converted to validity.
    """
    result = {"version": VERSION, "candidate_id": candidate.get("id"), "status": "unknown", "findings": [], "roles": [], "unknowns": [], "limits": ["bounded source-resolved call contexts", "unique prior direct definitions only", "opaque calls and mutation are not proved pure", "lexical assertions do not prove callback execution", "no findings does not establish test validity"]}
    try:
        sources, owner, changes, _, unknowns = _modified_sources(corpus, candidate)
        if owner.root.has_error:
            result["unknowns"] = [{"code": "modified_source_parse_error", "path": owner.path}]
            return result
        test = corpus["tests"][candidate["base_test_id"]]
        definition = test.get("definition_span", test["span"])
        analysis = _Analysis(sources, None, changes, max_depth=max_depth, max_contexts=max_contexts)
        roots = [unit for unit in analysis.index.units.values() if unit.source.path == owner.path and unit.test and unit.node.start_byte == definition["start_byte"]]
        if len(roots) != 1:
            result["unknowns"] = [{"code": "modified_test_owner_not_recovered"}]
            return result
        analysis.root = roots[0]
        analysis.visit(_Context(roots[0]))
        analysis.expected_edits()
        result.update(roles=_dedup(analysis.roles), findings=_dedup(analysis.findings), unknowns=_dedup(analysis.unknowns + unknowns), changes=changes, assertion_count=len(analysis.assertions), contexts=analysis.contexts, assertions=_dedup(analysis.assertion_records), guard_constraints=_dedup(analysis.guard_constraints), argument_bindings=_dedup(analysis.binding_records))
        result["status"] = "invalid" if any(row["severity"] == "invalid" for row in result["findings"]) else "review" if result["findings"] else "unknown"
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError) as error:
        result["unknowns"] = [{"code": "source_role_analysis_unavailable", "detail": str(error)}]
    return result
