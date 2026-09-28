"""Program-selected single-observation witnesses with whole-source controls.

Only assertion mechanics are neutralized. Existing setup, action expressions,
context managers and cleanup stay in the original test. This does not establish
dynamic reachability: unrelated actions after q may still raise or time out.
"""
from __future__ import annotations

import collections
import copy
from dataclasses import asdict, dataclass
import hashlib
import json

from anchor_retrieval.syntax import ATTRS, CALLS, Source, attr_parts, call_parts, child, walk
from experimental.semantic_transport.oracle import Unknown, parse_source_literal
from .frontend import source_text


@dataclass(frozen=True)
class AtomicBudget:
    max_candidates: int = 128
    max_q_per_candidate: int = 2
    max_assertions: int = 128
    max_neutralized_bytes: int = 32_000

    def __post_init__(self):
        if not 1 <= self.max_q_per_candidate <= 3:
            raise ValueError("max_q_per_candidate must be between 1 and 3")
        if any(type(getattr(self, field)) is not int or getattr(self, field) < 1
               for field in ("max_candidates", "max_assertions", "max_neutralized_bytes")):
            raise ValueError("atomic budgets must be positive integers")


def _id(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def _inside(inner, outer):
    return (inner["path"] == outer["path"] and outer["start_byte"] <= inner["start_byte"]
            and inner["end_byte"] <= outer["end_byte"])


def _overlap(a, b):
    if a["path"] != b["path"]:
        return False
    if a["start_byte"] == a["end_byte"]:
        return b["start_byte"] < a["start_byte"] < b["end_byte"]
    if b["start_byte"] == b["end_byte"]:
        return a["start_byte"] < b["start_byte"] < a["end_byte"]
    return max(a["start_byte"], b["start_byte"]) < min(a["end_byte"], b["end_byte"])


def _span(source, node):
    return {"path": source.path, "start_byte": node.start_byte, "end_byte": node.end_byte,
            "line": node.start_point.row + 1, "end_line": node.end_point.row + 1}


def _pure_literal(source, node):
    return node is None or not isinstance(parse_source_literal(source.text(node), source.language), Unknown)


def _apply_within(source, node, edits):
    position = _span(source, node)
    text = source.text(node).encode()
    relevant = []
    for edit in edits:
        if _inside(edit["span"], position):
            relevant.append(edit)
        elif _overlap(edit["span"], position):
            raise ValueError("input_edit_crosses_assertion_expression_boundary")
    for edit in sorted(relevant, key=lambda e: e["span"]["start_byte"], reverse=True):
        start = edit["span"]["start_byte"] - node.start_byte
        end = edit["span"]["end_byte"] - node.start_byte
        if text[start:end].decode() != edit["before"]:
            raise ValueError("input_edit_source_mismatch")
        text = text[:start] + edit["after"].encode() + text[end:]
    return text.decode(), relevant


def _neutralization(source, observation, nodes, input_edits):
    position = observation.get("assertion_span") or observation["span"]
    node = nodes.get((position["start_byte"], position["end_byte"]))
    if node is None:
        raise ValueError("assertion_node_not_found")
    consumed = []
    if source.language == "python":
        if node.type != "assert_statement" or not node.named_children:
            raise ValueError("python_non_direct_assertion_not_neutralized")
        condition = node.named_children[0]
        if len(node.named_children) > 1 and not _pure_literal(source, node.named_children[1]):
            raise ValueError("effectful_python_assertion_message")
        text, consumed = _apply_within(source, condition, input_edits)
        after = "not (" + text + ")"
        # Unary not retains Python's condition truthiness evaluation, including
        # a custom __bool__, without introducing a shadowable builtin call.
        rule = "python_condition_truthiness_without_failure"
    elif source.language == "typescript":
        if node.type not in CALLS or node.parent is None or node.parent.type != "expression_statement":
            raise ValueError("typescript_assertion_not_eager_statement")
        eager = {"toBe", "toEqual", "toStrictEqual", "toMatchObject", "toHaveLength", "toContain", "toContainEqual",
                 "toBeTruthy", "toBeFalsy", "toBeNull", "toBeUndefined", "toBeDefined", "toBeGreaterThan",
                 "toBeGreaterThanOrEqual", "toBeLessThan", "toBeLessThanOrEqual", "toMatch",
                 "strictEqual", "deepStrictEqual", "equal", "deepEqual", "notStrictEqual", "notDeepStrictEqual", "truthy"}
        fn, _ = call_parts(node)
        if observation.get("predicate") not in eager or any(part in source.text(fn).split(".") for part in {"resolves", "rejects", "poll"}):
            raise ValueError("typescript_lazy_or_unknown_matcher")
        observed = observation.get("observed")
        expected = observation.get("expected")
        actual = nodes.get((observed["span"]["start_byte"], observed["span"]["end_byte"])) if observed else None
        expected_node = nodes.get((expected["span"]["start_byte"], expected["span"]["end_byte"])) if expected else None
        if actual is None or not _pure_literal(source, expected_node):
            raise ValueError("typescript_expected_evaluation_not_proved_pure")
        text, consumed = _apply_within(source, actual, input_edits)
        after = "(" + text + ")"
        rule = "typescript_eager_actual_evaluation"
    elif source.language == "go":
        if observation.get("adapter") == "go_testing_failure_guard" and node.type == "if_statement":
            body = child(node, "consequence")
            if body is None:
                raise ValueError("go_failure_body_not_found")
            node = body
            after = "{}"
            rule = "go_failure_handler_removed_condition_retained"
        elif node.type in CALLS:
            fn, _ = call_parts(node)
            root = source.text(attr_parts(fn)[0]) if fn is not None and fn.type in ATTRS else ""
            imported = source.imports.get(root)
            if not imported or imported[0] not in {"github.com/stretchr/testify/assert", "github.com/stretchr/testify/require"}:
                raise ValueError("go_assertion_framework_not_proved")
            if node.parent is None or node.parent.type != "expression_statement":
                raise ValueError("go_assertion_result_used")
            observed, expected = observation.get("observed"), observation.get("expected")
            actual = nodes.get((observed["span"]["start_byte"], observed["span"]["end_byte"])) if observed else None
            expected_node = nodes.get((expected["span"]["start_byte"], expected["span"]["end_byte"])) if expected else None
            if actual is None or not _pure_literal(source, expected_node):
                raise ValueError("go_expected_evaluation_not_proved_pure")
            text, consumed = _apply_within(source, actual, input_edits)
            after = "_ = " + text
            rule = "go_eager_actual_evaluation"
        else:
            raise ValueError("go_nonstandard_assertion_not_neutralized")
    else:
        raise ValueError("unsupported_language")
    position = _span(source, node)
    for edit in input_edits:
        if _overlap(edit["span"], position) and edit not in consumed:
            raise ValueError("input_edit_would_be_lost_by_neutralization")
    return {"span": position, "before": source.text(node), "after": after,
            "role": "atomic_neutralization", "observation_id": observation["id"], "rule": rule}, consumed


def _selection(corpus, frontend, candidate, observations, rotation, budget):
    pinned = (candidate.get("source_observation_id") or candidate.get("observation_id")
              or candidate.get("relation", {}).get("source_observation_id"))
    if pinned:
        matches = [o for o in observations if o["id"] == pinned]
        return matches, "explicit_program_observation" if matches else "pinned_observation_not_owned_by_seed"
    edits = candidate.get("edits", [])
    affected_calls = set()
    for call in frontend.get("calls", []):
        if call.get("test_id") == candidate["base_test_id"] and any(_inside(e["span"], call["span"]) for e in edits):
            affected_calls.add(call["id"])
    for value in frontend.get("values", []):
        if value.get("test_id") != candidate["base_test_id"] or not any(_overlap(value["span"], e["span"]) for e in edits):
            continue
        affected_calls.update(p["call_id"] for p in value.get("input_slots", []) + value.get("argument_slots", []))
    groups = collections.defaultdict(list)
    for observation in observations:
        overlap = bool(affected_calls & set(observation.get("source_call_ids", [])))
        groups[(not overlap, bool(observation.get("incidental")))].append(observation)
    selected = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda o: (o["span"]["start_byte"], o["id"]))
        offset = rotation % len(group)
        selected.extend(group[offset:] + group[:offset])
        if len(selected) >= budget.max_q_per_candidate:
            break
    return selected[:budget.max_q_per_candidate], "edited_input_may_dependence_then_observation_rotation"


def atomize_candidates(corpus: dict, frontend: dict, candidates: list[dict], budget: AtomicBudget | None = None) -> dict:
    """Return source-controlled q variants; leave corpus/frontend/controls intact."""
    budget = budget or AtomicBudget()
    assertions = collections.defaultdict(list)
    for observation in frontend.get("observations", corpus.get("capsules", [])):
        if observation.get("kind", "assertion") == "assertion":
            assertions[observation["test_id"]].append(observation)
    cache, rotations, queues, unknowns = {}, collections.Counter(), collections.OrderedDict(), []
    generated = 0
    for candidate in candidates:
        base = candidate.get("base_test_id")
        if base not in corpus["tests"]:
            unknowns.append({"candidate_id": candidate.get("id"), "reason": "missing_base_test"})
            continue
        test = corpus["tests"][base]
        owned = assertions[base]
        if not owned or len(owned) > budget.max_assertions:
            unknowns.append({"candidate_id": candidate["id"], "reason": "missing_or_over_budget_observations"})
            continue
        path = test["span"]["path"]
        if path not in cache:
            language = corpus["sources"][path].get("language", corpus.get("language"))
            source = Source(path, corpus["sources"][path]["code"], language)
            cache[path] = source, {(n.start_byte, n.end_byte): n for n in walk(source.root)}
        source, nodes = cache[path]
        selected, selection = _selection(corpus, frontend, candidate, owned, rotations[base], budget)
        rotations[base] += 1
        if not selected:
            unknowns.append({"candidate_id": candidate["id"], "reason": selection})
        for q in selected:
            try:
                if any(c["kind"] not in {"with_statement"} for c in q.get("contexts", [])):
                    raise ValueError("selected_observation_control_or_callback_scope_unknown")
                if any(not _inside(e["span"], test["span"]) or source_text(corpus, e["span"]) != e["before"]
                       for e in candidate.get("edits", [])):
                    raise ValueError("candidate_input_not_source_owned")
                neutralized, consumed, other_ids, replacement_guards = [], [], [], []
                for observation in owned:
                    if observation["id"] == q["id"]:
                        continue
                    old_position = observation.get("assertion_span") or observation["span"]
                    replacements = candidate.get("provenance", {}).get("replaced_normal_observation_ids", [])
                    if observation["id"] in replacements and any(
                            e.get("role") == "source_exception_context" and e["span"] == old_position
                            for e in candidate.get("edits", [])):
                        # The source normal invocation has already been replaced
                        # with a borrowed, checked exceptional invocation. Its
                        # guard establishes reachability of the following q;
                        # neutralizing the old check a second time would destroy
                        # that program-owned context.
                        replacement_guards.append(observation["id"])
                        continue
                    edit, merged = _neutralization(source, observation, nodes, candidate.get("edits", []))
                    if _overlap(edit["span"], q.get("assertion_span") or q["span"]):
                        raise ValueError("nonselected_check_overlaps_selected_observation")
                    neutralized.append(edit)
                    consumed.extend(merged)
                    other_ids.append(observation["id"])
                if sum(len(e["before"].encode()) + len(e["after"].encode()) for e in neutralized) > budget.max_neutralized_bytes:
                    raise ValueError("neutralization_byte_budget")
                edits = [e for e in candidate.get("edits", []) if e not in consumed] + neutralized
                if any(_overlap(a["span"], b["span"]) for i, a in enumerate(edits) for b in edits[i + 1:]):
                    raise ValueError("atomic_edits_overlap")
                atomic = copy.deepcopy(candidate)
                atomic["id"] = "q_" + _id(candidate["id"], q["id"], edits)
                atomic["parent_candidate_id"] = candidate["id"]
                atomic["observation_id"] = q["id"]
                atomic["source_observation_id"] = q["id"]
                atomic["edits"] = edits
                atomic["atomic_observation"] = {"id": q["id"], "assertion_span": q.get("assertion_span") or q["span"],
                                                 "selection": selection, "neutralized_observation_ids": other_ids,
                                                 "source_exception_guard_ids": replacement_guards,
                                                 "input_edits": copy.deepcopy(candidate.get("edits", [])),
                                                 "status": "single_static_check_operational_reachability_unknown",
                                                 "remaining_risks": ["later_actions_may_raise_or_timeout", "framework_failure_control_intentionally_removed"]}
                atomic["oracle"] = dict(atomic.get("oracle", {}), assertion_ids=[q["id"]],
                                         applicability="selected_observation_requires_semantic_admission")
                queues.setdefault(base, collections.deque()).append(atomic)
                generated += 1
            except (ValueError, KeyError, TypeError) as exc:
                unknowns.append({"candidate_id": candidate["id"], "observation_id": q["id"], "reason": str(exc)})
    output = []
    active = list(queues)
    while active and len(output) < budget.max_candidates:
        remaining = []
        for test_id in active:
            output.append(queues[test_id].popleft())
            if queues[test_id]:
                remaining.append(test_id)
            if len(output) >= budget.max_candidates:
                break
        active = remaining
    return {"version": 1, "budget": asdict(budget), "candidates": output, "unknowns": unknowns,
            "counts": {"input_candidates": len(candidates), "atomic_pool": generated, "candidates": len(output),
                       "unknown": len(unknowns), "budget_exhausted": generated > len(output)}}
