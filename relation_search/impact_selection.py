"""Allocate local oracle judgments by unpaired edit-to-observation impact.

The program owns the dependence calculation; a model is only asked whether an
unchanged expectation remains appropriate.  A path is a *may* dependence, not
proof that the expectation must change or that the candidate exposes a bug.
No issue text, target labels, cached answers, execution outcomes or API-name
rules enter the policy.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Source, Unit, literal
from experimental.singleton_oracle_slots import assertion_inventory
from relational_gap.frontend import _flow_for_test, _test_walk
from relation_search import semantic_selection
from relation_search.instrument import _program_edits


POLICY = {
    "version": "unpaired-observation-impact-v1",
    "dependence": "original local value, control and conservative state-effect graph",
    "obligation": "edited node reaches observed expression but not expected value; assertion unchanged and editable",
    "identity": "observation source ID and original edited dependence-node port",
    "priority": "greedy uncovered observations, then uncovered observation-port pairs, then original shape round robin",
    "exploration": "every fourth eligible rank is the next original shape-round-robin candidate",
    "eligibility": "at least one unchanged assertion accepted by the existing expected-slot guard",
    "unsupported": "retain eligible candidates in exploration; no missing edge is an independence proof",
    "forbidden_inputs": ["issue text", "case name", "target labels", "oracle cache", "execution outcome", "provider"],
    "limits": ["original-source may dependence", "no path feasibility proof", "opaque calls and heap effects",
               "new call bindings are not resolved", "balanced impact is not an oracle proof"],
}

_SYNTHETIC = {"parameter", "receiver", "join", "unknown", "may_effect", "assertion"}


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _key(span):
    return span["path"], span["start_byte"], span["end_byte"]


def _overlap(edit, node):
    start, end = edit["start_byte"], edit["end_byte"]
    if start == end:
        # A statement-boundary insertion is unknown, not an edit of both
        # neighbouring expressions.  An insertion *inside* an expression is
        # still an edit of that expression.
        return node["start_byte"] < start < node["end_byte"]
    return start < node["end_byte"] and node["start_byte"] < end


def _slice(flow, roots, *, expected_value=False):
    """Unbounded finite graph closure, unlike the retrieval slice budget."""
    pending, reached = list(roots), set()
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(other for other in flow.edges.get(node, ())
                           if not expected_value or flow.edge_kinds.get((node, other)) != "control")
    return reached


def _roots(flow, expression):
    extent = (expression or {}).get("span")
    if not extent:
        return []
    return [node["id"] for node in flow.nodes if node["kind"] not in _SYNTHETIC
            and (node["start_byte"], node["end_byte"]) == (extent["start_byte"], extent["end_byte"])]


def _expected_roots(flow, observation, inventory, bindings):
    expression = observation.get("expected") or {}
    roots = _roots(flow, expression)
    if roots:
        return roots, "original_expression_graph"
    # Some assertion adapters intentionally evaluate only actual in the graph.
    # Literal syntax independently proves that expected has no input reads.
    if expression.get("literal_known"):
        return [], "closed_literal_no_input_reads"
    slot = inventory.get("slot") or {}
    if slot.get("retained_wrapper"):
        try:
            literal(slot["expected"])
            return [], "retained_scalar_wrapper_of_literal"
        except ValueError:
            pass
    if expression.get("kind") == "identifier" and expression.get("span"):
        preceding = [row for row in bindings if row.get("simple_name")
                     and row.get("name") == expression.get("text")
                     and row.get("definition_end", 10**30) <= expression["span"]["start_byte"]]
        if preceding:
            binding = max(preceding, key=lambda row: row["definition_end"])
            if not binding.get("contexts"):
                roots = _roots(flow, binding.get("target"))
                if roots:
                    return roots, "preceding_local_expected_binding"
    return None, "expected_expression_graph_unavailable"


def _path(flow, roots, targets):
    """One deterministic shortest witness, directed edit -> observed root."""
    pending = deque((node, [node]) for node in sorted(roots))
    seen = set()
    while pending:
        node, path = pending.popleft()
        if node in seen:
            continue
        seen.add(node)
        if node in targets:
            return list(reversed(path))
        pending.extend((other, path + [other]) for other in sorted(flow.edges.get(node, ())))
    return []


def _path_node(flow, identifier):
    node = flow.nodes[identifier]
    # Flow.text is an abbreviated graph label and synthetic nodes use labels
    # such as a local binding name.  Prompt evidence must never present that
    # label as if it were the complete source at the node's recorded span.
    source = flow.source.data[node["start_byte"]:node["end_byte"]].decode()
    return dict(node, path=flow.source.path, text=source,
                graph_label=node.get("text", ""), text_basis="complete_original_source_span")


def _flow_index(corpus, candidates):
    # Only local test-source flow is needed.  This does not resolve calls in the
    # edited program, execute a repository or trust a candidate implementation.
    paths = sorted({corpus["tests"][c["base_test_id"]]["span"]["path"] for c in candidates
                    if c.get("base_test_id") in corpus.get("tests", {})})
    sources = [Source(path, corpus["sources"][path]["code"], corpus["language"])
               for path in paths if path in corpus["sources"]]
    index = Index(sources, "")
    flows, reasons = {}, {}
    for test_id in sorted({c.get("base_test_id") for c in candidates if c.get("base_test_id")}):
        test = corpus.get("tests", {}).get(test_id)
        if not test:
            reasons[test_id] = "missing_test"
            continue
        unit = index.units.get(test_id)
        if unit is None and test.get("owner_kind") == "module_script":
            source = index.sources.get(test["span"]["path"])
            if source is not None:
                unit = Unit(source, source.root, source.root, "<script>", test=True)
                index.units[unit.id] = unit
        if unit is None:
            reasons[test_id] = "local_flow_owner_unresolved"
        elif unit.source.root.has_error:
            reasons[test_id] = "original_source_parse_error"
        else:
            try:
                flows[test_id] = _flow_for_test(index, unit, list(_test_walk(unit.body)))
            except (ValueError, KeyError, IndexError, RecursionError) as error:
                reasons[test_id] = "local_flow_unavailable:" + type(error).__name__
    return flows, reasons


def _edit_seeds(flow, edits):
    """Use innermost overlapping values; enclosing calls are not extra seeds.

    Selecting every enclosing node would let an edit of an unused argument
    pretend to affect all nested expressions, and would multiply obligations
    simply by nesting a call.  Whole-expression replacements keep all minimal
    covered values; callee-only changes fall back to the enclosing call.
    """
    result = []
    for edit_index, edit in edits:
        matches = [node for node in flow.nodes if node["kind"] not in _SYNTHETIC
                   and edit["span"]["path"] == flow.source.path and _overlap(edit["span"], node)]
        minimal = [node for node in matches if not any(
            node["start_byte"] <= other["start_byte"] and other["end_byte"] <= node["end_byte"]
            and (other["start_byte"], other["end_byte"]) != (node["start_byte"], node["end_byte"])
            for other in matches)]
        result.append((edit_index, edit, {node["id"] for node in minimal}))
    return result


def _candidate_evidence(corpus, frontend_rows, candidate, flow, unavailable):
    base = candidate.get("base_test_id")
    try:
        inventory = [] if candidate.get("is_source_profile") else assertion_inventory(corpus, frontend_rows, candidate)
    except (KeyError, ValueError, IndexError, UnicodeDecodeError):
        inventory = []
    editable = {_key(row["span"]): row for row in inventory if row["editable"]}
    record = {"eligible": bool(editable), "editable_assertions": len(editable),
              "obligations": [], "balanced_observation_ids": [], "unknowns": [],
              "dependence_status": "original_source_may_impact", "edit_seeds": []}
    if not editable:
        record["unknowns"].append("no_unchanged_editable_assertion")
        return record
    if flow is None:
        record["unknowns"].append(unavailable or "local_flow_unavailable")
        return record
    edits = []
    for i, edit in enumerate(candidate.get("edits", [])):
        if edit.get("role") == "semantic_expected" or edit.get("before") == edit.get("after"):
            continue
        extent = edit["span"]
        try:
            source = corpus["sources"][extent["path"]]["code"].encode()
            valid = (0 <= extent["start_byte"] <= extent["end_byte"] <= len(source)
                     and source[extent["start_byte"]:extent["end_byte"]].decode() == edit["before"])
        except (KeyError, UnicodeDecodeError):
            valid = False
        if not valid:
            record["unknowns"].append("edit_source_mismatch")
            record["eligible"] = False
            return record
        edits.append((i, edit))
    seeds = _edit_seeds(flow, edits)
    for edit_index, edit, nodes in seeds:
        record["edit_seeds"].append({"edit_index": edit_index, "span": edit["span"],
                                     "node_ids": sorted(nodes)})
        if not nodes:
            record["unknowns"].append("no_original_dependence_seed:" + str(edit_index))
    for observation in frontend_rows.get("observations", []):
        extent = observation.get("assertion_span") or observation.get("span")
        if observation.get("test_id") != base or not extent or _key(extent) not in editable:
            continue
        actual_roots = _roots(flow, observation.get("observed"))
        expected_roots, expected_basis = _expected_roots(
            flow, observation, editable[_key(extent)], frontend_rows.get("bindings", []))
        if not actual_roots or expected_roots is None:
            record["unknowns"].append("expression_root_unresolved:" + observation["id"])
            continue
        actual_slice = _slice(flow, actual_roots)
        # A condition can govern whether a literal expectation is evaluated;
        # that does not make the literal's value adapt with the changed input.
        expected_slice = _slice(flow, expected_roots, expected_value=True)
        for edit_index, edit, nodes in seeds:
            affected = nodes & actual_slice
            if not affected:
                continue
            if affected & expected_slice:
                record["balanced_observation_ids"].append(observation["id"])
            affected -= expected_slice
            if not affected:
                continue
            path = _path(flow, actual_roots, affected)
            port = sorted((flow.nodes[n]["kind"], flow.nodes[n]["start_byte"], flow.nodes[n]["end_byte"])
                          for n in affected)
            record["obligations"].append({
                "observation_id": observation["id"], "edit_index": edit_index,
                "port_id": _sha([base, port]), "assertion_span": extent,
                "actual_span": observation.get("observed", {}).get("span"),
                "expected_span": observation.get("expected", {}).get("span"),
                "actual_root_ids": actual_roots, "expected_root_ids": expected_roots,
                "expected_dependency_basis": expected_basis,
                "expected_value_slice_node_ids": sorted(expected_slice),
                "observed": observation.get("observed", {}).get("text"),
                "expected": observation.get("expected", {}).get("text"),
                "expected_status": "unchanged_expression_without_same_edit_dependency",
                "path": [_path_node(flow, n) for n in path],
                "edge_kinds": [flow.edge_kinds.get((right, left), "unknown")
                               for left, right in zip(path, path[1:])],
            })
    record["balanced_observation_ids"] = sorted(set(record["balanced_observation_ids"]))
    record["unknowns"] = sorted(set(record["unknowns"]))
    return record


def select(corpus, frontend, candidates, budget=16):
    """Return eligible selections and a complete, budget-independent ranking.

    Unsupported dependence remains eligible for exploration when the assertion
    interface can express an answer.  Unsupported assertion syntax is ranked
    and reported, but receives no unusable expected-slot model request.
    """
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
        raise ValueError("budget must be a nonnegative integer")
    candidates = list(candidates)
    by_id = {candidate["id"]: candidate for candidate in candidates}
    normalized = [dict(candidate, edits=_program_edits(candidate)) for candidate in candidates]
    baseline = semantic_selection.select(corpus, normalized, budget=len(candidates))
    program_by_id = {candidate["id"]: candidate for candidate in normalized}
    flows, missing = _flow_index(corpus, normalized)
    # Preindex observations to avoid scanning the entire corpus per candidate.
    observations, bindings = defaultdict(list), defaultdict(list)
    for row in frontend.get("observations", []):
        observations[row.get("test_id")].append(row)
    for row in frontend.get("bindings", []):
        bindings[row.get("test_id")].append(row)
    records = []
    for old in baseline["ranking"]:
        candidate = program_by_id[old["id"]]
        base = candidate.get("base_test_id")
        evidence = _candidate_evidence(corpus, {"observations": observations[base], "bindings": bindings[base]}, candidate,
                                       flows.get(base), missing.get(base))
        pairs = {(row["observation_id"], row["port_id"]) for row in evidence["obligations"]}
        records.append(dict(id=old["id"], base_test_id=base, baseline_rank=old["rank"],
                            shape_id=old["shape_id"], evidence=evidence, _pairs=pairs,
                            _observations={qid for qid, _ in pairs}))
    pending = [row for row in records if row["evidence"]["eligible"]]
    covered_pairs, covered_observations, ranking = set(), set(), []
    while pending:
        exploration = (len(ranking) + 1) % 4 == 0
        def priority(row):
            return (-len(row["_observations"] - covered_observations),
                    -len(row["_pairs"] - covered_pairs), row["baseline_rank"])
        chosen = min(pending, key=(lambda row: row["baseline_rank"]) if exploration else priority)
        pending.remove(chosen)
        chosen["new_observation_count"] = len(chosen["_observations"] - covered_observations)
        chosen["new_observation_port_count"] = len(chosen["_pairs"] - covered_pairs)
        chosen["selection_reason"] = "shape_exploration" if exploration else "uncovered_impact"
        covered_pairs.update(chosen["_pairs"])
        covered_observations.update(chosen["_observations"])
        ranking.append(chosen)
    eligible_count = len(ranking)
    ranking.extend(dict(row, selection_reason="ineligible_assertion_interface", new_observation_count=0,
                        new_observation_port_count=0) for row in records if not row["evidence"]["eligible"])
    for rank, row in enumerate(ranking, 1):
        row.pop("_pairs")
        row.pop("_observations")
        row.update(rank=rank, selected=rank <= min(budget, eligible_count))
    selected = [by_id[row["id"]] for row in ranking if row["selected"]]
    return {"selected": selected, "ranking": ranking,
            "unselected_ids": [row["id"] for row in ranking if not row["selected"]],
            "budget": budget, "input_count": len(candidates), "eligible_count": eligible_count,
            "selected_count": len(selected), "policy": POLICY, "policy_sha256": _sha(POLICY),
            "flow_count": len(flows), "flow_unavailable": missing}
