"""Observation-relevant guard transitions, independent of oracle scheduling.

Instantiate resolved source guards with closed integer arguments before/after
an input edit.  This is a finite constant-propagation fragment, not execution of
subject code or proof of path feasibility.  Different cells justify retaining
different reasoning tasks; identical cells do not prove behavioral equivalence.
"""
from __future__ import annotations

import ast
from collections import defaultdict, deque
import hashlib
import json

from anchor_retrieval.syntax import Source, Unit, child, walk
from relational_gap.frontend import _bindings, _owned_walk
from relation_search.instrument import _program_edits


POLICY = {
    "version": "observed-guard-transition-cells-v1",
    "object": "resolved call on observation slice plus source guard before/after operand order",
    "constant_fragment": "closed integer literals, local bindings, + - *, source-resolved straight-line pure helpers",
    "guard_scope": "comparisons in reachable candidate functions; no issue or oracle input",
    "unknown": "unsupported computation remains unknown, never an equivalence class",
    "same_cell": "same sampled guard relations only; no output or oracle equivalence claim",
    "selection": "none; evidence-only experimental module",
}

_CONTROL = {"if_statement", "for_statement", "for_in_statement", "while_statement", "switch_statement",
            "expression_switch_statement", "try_statement", "with_statement", "select_statement"}
_ASSIGNMENT = {"assignment", "assignment_statement", "short_var_declaration", "variable_declarator",
               "var_spec", "const_spec", "lexical_declaration", "variable_declaration", "expression_statement"}
_SAFE = 2**53 - 1


class Unknown(ValueError):
    pass


def _key(span):
    return span["path"], span["start_byte"], span["end_byte"]


def _span(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class _Analysis:
    def __init__(self, corpus, frontend, candidate, max_depth):
        self.corpus, self.frontend, self.candidate, self.max_depth = corpus, frontend, candidate, max_depth
        self.sources = {}
        self.functions = {row["id"]: row for row in frontend.get("functions", [])}
        self.calls = {row["id"]: row for row in frontend.get("calls", []) + frontend.get("production_calls", [])}
        self.call_by_span = {_key(row["span"]): row for row in self.calls.values()}
        self.production_calls, self.comparisons = defaultdict(list), defaultdict(list)
        for row in frontend.get("production_calls", []):
            self.production_calls[row["function_id"]].append(row)
        for row in frontend.get("comparisons", []):
            if row.get("guard_span"):
                self.comparisons[row["function_id"]].append(row)
        self.bindings = defaultdict(list)
        for row in frontend.get("bindings", []):
            self.bindings[row["test_id"]].append(row)
        self.function_bodies = {}
        self.edits = _program_edits(candidate)
        for edit in self.edits:
            if self.source_text(edit["span"], False) != edit["before"]:
                raise ValueError("edit does not match original source")

    def source(self, path):
        if path not in self.sources:
            row = self.corpus["sources"][path]
            self.sources[path] = Source(path, row["code"], row.get("language", self.corpus["language"]))
        return self.sources[path]

    def source_text(self, span, modified):
        data = self.source(span["path"]).data[span["start_byte"]:span["end_byte"]]
        if modified:
            applicable = []
            for edit in self.edits:
                extent = edit["span"]
                if edit.get("role") == "semantic_expected" or extent["path"] != span["path"]:
                    continue
                if extent["start_byte"] < span["end_byte"] and span["start_byte"] < extent["end_byte"]:
                    if not span["start_byte"] <= extent["start_byte"] <= extent["end_byte"] <= span["end_byte"]:
                        raise Unknown("edit_crosses_expression_boundary")
                    applicable.append(edit)
            for edit in sorted(applicable, key=lambda row: row["span"]["start_byte"], reverse=True):
                begin, end = edit["span"]["start_byte"]-span["start_byte"], edit["span"]["end_byte"]-span["start_byte"]
                data = data[:begin] + edit["after"].encode() + data[end:]
        return data.decode()

    def function(self, identifier):
        if identifier not in self.function_bodies:
            record = self.functions[identifier]
            source = self.source(record["span"]["path"])
            span = record["span"]
            node = source.root.named_descendant_for_byte_range(span["start_byte"], span["end_byte"]-1)
            if (node.start_byte, node.end_byte) != (span["start_byte"], span["end_byte"]):
                raise Unknown("function_extent_unresolved")
            body = child(node, "body")
            if body is None:
                raise Unknown("function_body_unresolved")
            unit = Unit(source, node, body, record["name"], record.get("owner", ""))
            self.bindings[identifier] = _bindings(unit, list(_owned_walk(body)))
            self.function_bodies[identifier] = source, body
        return self.function_bodies[identifier]

    def check_binding(self, binding):
        extent = binding["span"]
        node = self.source(extent["path"]).root.named_descendant_for_byte_range(
            extent["start_byte"], extent["end_byte"]-1)
        if "augmented" in node.type or any(part.type in {"+=", "-=", "*=", "/=", "%=", "++", "--", "|=", "&="}
                                           for part in node.children):
            raise Unknown("augmented_assignment_not_in_scalar_fragment")
        if not binding["simple_name"] or binding.get("contexts"):
            raise Unknown("conditional_or_nonlocal_binding")

    def expression(self, extent, owner, frame, modified, depth=0, seen=()):
        if depth > self.max_depth:
            raise Unknown("expression_depth_limit")
        text = self.source_text(extent, modified)
        try:
            tree = ast.parse(text.strip(), mode="eval").body
        except (SyntaxError, RecursionError) as error:
            raise Unknown("unsupported_integer_expression") from error

        def integer(value):
            if type(value) is not int or abs(value) > _SAFE:
                raise Unknown("outside_exact_common_integer_fragment")
            return value

        def evaluate(node, expression_depth=0):
            if expression_depth > self.max_depth:
                raise Unknown("arithmetic_depth_limit")
            if isinstance(node, ast.Constant):
                return integer(node.value)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand, expression_depth+1)
                return integer(value if isinstance(node.op, ast.UAdd) else -value)
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
                left, right = evaluate(node.left, expression_depth+1), evaluate(node.right, expression_depth+1)
                return integer(left+right if isinstance(node.op, ast.Add) else left-right
                               if isinstance(node.op, ast.Sub) else left*right)
            if isinstance(node, ast.Name):
                choices = [row for row in self.bindings[owner] if row.get("simple_name")
                           and row["name"] == node.id and row["definition_end"] <= extent["start_byte"]]
                if choices:
                    binding = max(choices, key=lambda row: row["definition_end"])
                    self.check_binding(binding)
                    if binding["id"] in seen:
                        raise Unknown("cyclic_local_binding")
                    return self.expression(binding["value"]["span"], owner, frame, modified,
                                           depth+1, (*seen, binding["id"]))
                if node.id in frame:
                    return integer(frame[node.id])
                raise Unknown("unbound_or_noninteger_symbol")
            if isinstance(node, ast.Call) and node is tree:
                call = self.call_by_span.get(_key(extent))
                if call is None or ast.unparse(node.func) != call["callee"]:
                    raise Unknown("changed_or_unresolved_callable")
                target, child_frame = self.call_frame(call, owner, frame, modified, depth+1)
                return self.pure_return(target, child_frame, modified, depth+1)
            raise Unknown("unsupported_integer_expression")
        return integer(evaluate(tree))

    def call_frame(self, call, owner, frame, modified, depth):
        if modified and call["callee"].split(".", 1)[0] in {row.get("name") for row in self.candidate.get("imports", [])}:
            raise Unknown("added_import_binding_not_reanalysed")
        targets = [row["function_id"] for row in call.get("targets", [])
                   if row.get("resolved") and row["function_id"] in self.functions]
        if len(targets) != 1:
            raise Unknown("call_target_not_unique")
        target = targets[0]
        if call.get("receiver") or self.functions[target].get("receiver"):
            raise Unknown("stateful_receiver_not_in_scalar_fragment")
        if self.corpus["language"] == "go" and any(parameter.get("type") not in {"int", "int64"}
                                                    for parameter in self.functions[target].get("parameters", [])):
            raise Unknown("go_integer_type_not_in_common_fragment")
        # Editing a call target or surrounding statement cannot inherit the
        # original actual/formal binding merely because its span still exists.
        original = self.source_text(call["span"], False)
        changed = self.source_text(call["span"], modified)
        try:
            before, after = ast.parse(original, mode="eval").body, ast.parse(changed, mode="eval").body
            if not isinstance(before, ast.Call) or not isinstance(after, ast.Call) or ast.dump(before.func) != ast.dump(after.func):
                raise Unknown("modified_callee_binding")
            if len(before.args) != len(after.args) or [row.arg for row in before.keywords] != [row.arg for row in after.keywords]:
                raise Unknown("modified_argument_binding")
        except SyntaxError as error:
            raise Unknown("call_syntax_outside_common_fragment") from error
        args = {row["slot"]: row for row in call.get("arguments", [])}
        result = {}
        for binding in call.get("argument_bindings", []):
            if binding["function_id"] != target or binding["binding_status"] != "direct_actual_formal":
                raise Unknown("non_direct_actual_formal")
            arg = args[binding["slot"]]
            result[binding["parameter"]] = self.expression(arg["span"], owner, frame, modified, depth+1)
        required = {row["name"] for row in self.functions[target].get("parameters", [])}
        if set(result) != required:
            raise Unknown("implicit_default_or_parameter_binding")
        self.function(target)
        return target, result

    def pure_return(self, target, frame, modified, depth):
        if depth > self.max_depth:
            raise Unknown("helper_depth_limit")
        source, body = self.function(target)
        nodes = list(_owned_walk(body))
        if any(node.type in _CONTROL or node.type in {"function_definition", "function_declaration", "func_literal",
                                                     "lambda", "arrow_function"} for node in nodes[1:]):
            raise Unknown("non_straight_line_helper")
        returns = [node for node in nodes if node.type == "return_statement"]
        if len(returns) != 1 or len(returns[0].named_children) != 1:
            raise Unknown("non_single_scalar_return")
        # Unknown calls or field writes that precede a return cannot be silently
        # discarded. Permit only declarations/assignments with numeric RHS and
        # direct pure-return calls; evaluate every local write in source order.
        for binding in self.bindings[target]:
            self.check_binding(binding)
            self.expression(binding["value"]["span"], target, frame, modified, depth+1)
        statements = list(body.named_children)
        if len(statements) == 1 and statements[0].type == "statement_list":
            statements = list(statements[0].named_children)
        for node in statements:
            if node.type not in _ASSIGNMENT | {"return_statement", "comment"}:
                raise Unknown("unsupported_helper_statement")
            if node.type == "expression_statement" and not any(part.type == "assignment" for part in node.named_children):
                raise Unknown("discarded_effectful_call")
        expression = returns[0].named_children[0]
        return self.expression(_span(source, expression), target, frame, modified, depth+1)


def candidate_cells(corpus, frontend, candidate, *, max_depth=12, call_depth=2):
    """Return finite relation cells plus explicit unsupported edges; no ranking."""
    analysis = _Analysis(corpus, frontend, candidate, max_depth)
    base = candidate["base_test_id"]
    observations = {row["id"] for row in frontend.get("observations", [])
                    if row.get("test_id") == base and row.get("kind") == "assertion"}
    records, unknowns = [], []
    for call in frontend.get("calls", []):
        linked = sorted(set(call.get("observation_ids", [])) & observations)
        if call.get("test_id") != base or not linked or call.get("role") != "operation":
            continue
        pending = deque([(call, base, {}, {}, 0, [])])
        while pending:
            current, owner, before_frame, after_frame, level, chain = pending.popleft()
            try:
                target, before = analysis.call_frame(current, owner, before_frame, False, 0)
                other_target, after = analysis.call_frame(current, owner, after_frame, True, 0)
                if target != other_target:
                    raise Unknown("changed_call_target")
            except Unknown as error:
                unknowns.append(dict(call_id=current["id"], reason=str(error), observation_ids=linked))
                continue
            chain = [*chain, dict(call_id=current["id"], span=current["span"], function_id=target,
                                 before_arguments=before, after_arguments=after)]
            for comparison in analysis.comparisons[target]:
                try:
                    old = [analysis.expression(comparison[side]["span"], target, before, False) for side in ("left", "right")]
                    new = [analysis.expression(comparison[side]["span"], target, after, True) for side in ("left", "right")]
                except Unknown as error:
                    unknowns.append(dict(comparison_id=comparison["id"], reason=str(error), observation_ids=linked))
                    continue
                if old == new:
                    continue  # No changed scalar has reached this comparison.
                relation = lambda operands: (operands[0] > operands[1]) - (operands[0] < operands[1])
                records.append(dict(call_id=call["id"], comparison_id=comparison["id"], function_id=target,
                    observation_ids=linked, comparison_span=comparison["span"], operator=comparison["operator"],
                    before_operands=old, after_operands=new, before_order=relation(old), after_order=relation(new),
                    actual_formal_chain=chain, reachability="original_source_may_not_feasible_path"))
            if level < call_depth:
                pending.extend((nested, target, before, after, level+1, chain)
                               for nested in analysis.production_calls[target])
            elif analysis.production_calls[target]:
                unknowns.append(dict(call_id=current["id"], reason="production_call_depth_limit", observation_ids=linked))
    records = list({_sha(row): row for row in records}.values())
    signature = sorted((row["call_id"], row["comparison_id"], row["before_order"], row["after_order"])
                       for row in records)
    return dict(policy=POLICY, candidate_id=candidate["id"], records=records,
                cell_signature=signature, cell_id=_sha(signature) if signature else None,
                unknowns=list({_sha(row): row for row in unknowns}.values()),
                observation_equivalence_proved=False, execution_or_oracle_inference=False,
                limits=dict(max_depth=max_depth, call_depth=call_depth))
