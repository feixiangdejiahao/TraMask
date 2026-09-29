"""Partial constant environments for the frozen guard-cell experiment.

An unsupported actual becomes TOP for that formal only. Reading TOP in a guard
still fails constant evaluation. Receiver resolution and pure-helper checks
remain as restrictive as v1. This is standard constant propagation, not an
additional claim of academic novelty or an oracle inference procedure.
"""
from __future__ import annotations

from collections import deque

from anchor_retrieval.syntax import CALLS, Source, call_parts, walk
from experimental import guard_transition_cells as original


POLICY = dict(original.POLICY, version="observed-guard-transition-partial-environment-v2",
              constant_environment="each formal independently has a known integer or TOP",
              unknown="TOP only blocks expressions that read it; all v1 call and purity limits remain")


def _call_syntax(text, language):
    prefix, suffix = ("package fragment\nfunc inspect(){\n", "\n}") if language == "go" else ("", "")
    source = Source("fragment", prefix+text+suffix, language)
    if source.root.has_error:
        raise original.Unknown("call_syntax_unresolved")
    begin, end = len(prefix.encode()), len(prefix.encode())+len(text.encode())
    node = next((node for node in walk(source.root) if node.type in CALLS
                 and node.start_byte == begin and node.end_byte == end), None)
    if node is None:
        raise original.Unknown("call_expression_unresolved")
    target, arguments = call_parts(node)
    keywords = [source.text(arg.child_by_field_name("name")) if arg.type == "keyword_argument" else None
                for arg in arguments]
    return source.text(target), len(arguments), keywords


class _PartialAnalysis(original._Analysis):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.partial_bindings = []

    def call_frame(self, call, owner, frame, modified, depth):
        if modified and call["callee"].split(".", 1)[0] in {row.get("name") for row in self.candidate.get("imports", [])}:
            raise original.Unknown("added_import_binding_not_reanalysed")
        targets = [row["function_id"] for row in call.get("targets", [])
                   if row.get("resolved") and row["function_id"] in self.functions]
        if len(targets) != 1:
            raise original.Unknown("call_target_not_unique")
        target = targets[0]
        if call.get("receiver") or self.functions[target].get("receiver"):
            raise original.Unknown("stateful_receiver_not_in_scalar_fragment")
        before = _call_syntax(self.source_text(call["span"], False), self.corpus["language"])
        after = _call_syntax(self.source_text(call["span"], modified), self.corpus["language"])
        if before[0] != after[0]:
            raise original.Unknown("modified_callee_binding")
        if before[1:] != after[1:]:
            raise original.Unknown("modified_argument_binding")
        arguments = {row["slot"]: row for row in call.get("arguments", [])}
        parameters = {row["name"]: row for row in self.functions[target].get("parameters", [])}
        result = {}

        def top(name, reason):
            self.partial_bindings.append(dict(call_id=call["id"], function_id=target, parameter=name,
                                              modified=modified, reason=reason))
            return dict(abstract="top", reason=reason)

        for binding in call.get("argument_bindings", []):
            if binding["function_id"] != target or binding["binding_status"] != "direct_actual_formal":
                raise original.Unknown("non_direct_actual_formal")
            name = binding["parameter"]
            if self.corpus["language"] == "go" and parameters[name].get("type") not in {"int", "int64"}:
                result[name] = top(name, "go_parameter_outside_integer_fragment")
                continue
            try:
                result[name] = self.expression(arguments[binding["slot"]]["span"], owner, frame, modified, depth+1)
            except original.Unknown as error:
                result[name] = top(name, str(error))
        # The experiment does not invent default values or expand unknown
        # spreads. An absent direct binding is not the same as an unknown value
        # at a known formal and continues to reject this call boundary.
        if set(result) != set(parameters):
            raise original.Unknown("implicit_default_or_parameter_binding")
        self.function(target)
        return target, result


def candidate_cells(corpus, frontend, candidate, *, max_depth=12, call_depth=2):
    analysis = _PartialAnalysis(corpus, frontend, candidate, max_depth)
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
                    raise original.Unknown("changed_call_target")
            except original.Unknown as error:
                unknowns.append(dict(call_id=current["id"], reason=str(error), observation_ids=linked))
                continue
            chain = [*chain, dict(call_id=current["id"], span=current["span"], function_id=target,
                                 before_arguments=before, after_arguments=after)]
            for comparison in analysis.comparisons[target]:
                try:
                    old = [analysis.expression(comparison[side]["span"], target, before, False) for side in ("left", "right")]
                    new = [analysis.expression(comparison[side]["span"], target, after, True) for side in ("left", "right")]
                except original.Unknown as error:
                    unknowns.append(dict(comparison_id=comparison["id"], reason=str(error), observation_ids=linked))
                    continue
                if old == new:
                    continue
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
    records = list({original._sha(row): row for row in records}.values())
    signature = sorted([row["call_id"], row["comparison_id"], row["before_order"], row["after_order"]]
                       for row in records)
    return dict(policy=POLICY, candidate_id=candidate["id"], records=records,
                cell_signature=signature, cell_id=original._sha(signature) if signature else None,
                unknowns=list({original._sha(row): row for row in unknowns}.values()),
                partial_bindings=list({original._sha(row): row for row in analysis.partial_bindings}.values()),
                observation_equivalence_proved=False, execution_or_oracle_inference=False,
                limits=dict(max_depth=max_depth, call_depth=call_depth))
