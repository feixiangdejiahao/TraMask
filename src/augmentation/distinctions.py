"""Source-backed behavioral contrasts and post-generation condition checks.

The analysis explains a possible effect, not a required oracle. Its condition
checks use individual call contexts. It never joins separate invocations into
a joint witness, or promotes unknown aliases and phases to confirmed evidence.
"""
from __future__ import annotations

from pathlib import Path
import re

from anchor_retrieval.syntax import Source, is_test_path
from .program import EXTENSIONS, build_program, stable_id, evaluate_condition
from .ranking import focus
from .scopes import test_scope


def operation_view(node):
    return {k: node[k] for k in ("id", "function_id", "kind", "span", "code", "changed", "conditions") if k in node}


def branch_effects(operations, dims, values):
    effects = []
    for n in operations:
        if not n.get("conditions") or n["kind"] == "condition":
            continue
        outcomes = []
        for guard in n["conditions"]:
            expression = guard["expression"]
            for d in sorted(dims, key=lambda d: -len(d["expression"])):
                if d["function_id"] != n["function_id"] or d["id"] not in values or d["kind"] != "predicate":
                    continue
                expression = re.sub(r"(?<![\w.])" + re.escape(d["expression"]) + r"(?![\w.])", str(values[d["id"]]), expression)
            answer = evaluate_condition(expression, {})
            outcomes.append(answer["value"] == guard["value"] if answer.get("known") and guard["value"] is not None else None)
        if all(v is not None for v in outcomes):
            effects.append({"operation_id": n["id"], "span": n["span"], "code": n["code"][:240],
                            "code_truncated": len(n["code"]) > 240,
                            "branch_condition": "enabled" if all(outcomes) else "excluded",
                            "meaning": "Predicate substitution only. Earlier exits, exceptions and scheduling still require review."})
    return effects[:4]


def behavioral_distinction(candidate):
    """Express input alternatives -> concrete operations -> observable effect."""
    behavior = candidate.get("behavior", {})
    dims = behavior.get("conditions", [])
    operations = behavior.get("operations", [])
    by_id = {n["id"]: n for n in operations}
    seeds = focus(candidate)
    effects = []
    for link in candidate.get("relations", []):
        if link["from"] not in by_id or link["to"] not in by_id:
            continue
        if link["kind"] not in {"may_prevent_continuation", "value_flow", "shared_state", "symbol_dispatch"}:
            continue
        a, b = by_id[link["from"]], by_id[link["to"]]
        effects.append({"relation": link["kind"], "before": operation_view(a), "after": operation_view(b),
                        "certainty": link.get("certainty", "source_relation_requires_runtime_review"),
                        "effect": "The exit can prevent this later operation." if link["kind"] == "may_prevent_continuation"
                                  else "These operations exchange a value or state; check their joint observable result."})
    # Branch bodies provide concrete alternatives even without a cross-function edge.
    for d in dims:
        if d["kind"] != "predicate":
            continue
        arms = {str(value).lower(): [operation_view(n) for n in operations if n["kind"] != "condition"
                                   and n["function_id"] == d["function_id"]
                                   and any(c["expression"] == d["expression"] and c["value"] is value
                                           for c in n.get("conditions", []))][:4] for value in (False, True)}
        if any(arms.values()):
            effects.append({"condition_id": d["id"], "expression": d["expression"], "span": d["span"],
                            "source_branches": arms, "effect": "These operations are controlled by this predicate. An empty arm is not proof of no effect."})
    cells = behavior.get("combinations", {})
    values = []
    # These are existing dimension semantics, not task-specific mutation rules.
    for d in dims:
        if d["kind"] == "presence":
            values.append({d["id"]: False})
    for exit_node in seeds:
        if exit_node.get("termination") or exit_node["kind"] in {"return", "raise"}:
            required = {d["id"]: cond["value"] for d in dims for cond in exit_node.get("conditions", [])
                        if d["expression"] == cond["expression"] and cond["value"] is not None}
            if required:
                values.append(required)
    # Prefer uncovered cells close to observed inputs, with true joint predicates
    # first on a tie. The expected result still comes from the public requirement.
    witnessed = [c["conditions"] for c in cells.get("checked", [])]
    choices = cells.get("missing", []) + cells.get("unknown", [])
    choices = sorted(choices, key=lambda c: (min((sum(w.get(k) != v for k, v in c["conditions"].items()) for w in witnessed), default=0),
                                              -sum(v is True for v in c["conditions"].values())))
    values.extend(c["conditions"] for c in choices)
    targets, seen = [], set()
    for value in values:
        key = stable_id(value)
        if not value or key in seen:
            continue
        seen.add(key)
        targets.append({"id": "target_" + key, "condition_values": value,
                        "conditions": [{"id": d["id"], "expression": d["expression"], "kind": d["kind"],
                                        "value": value[d["id"]], "span": d["span"]} for d in dims if d["id"] in value],
                        "predicted_branch_effects": branch_effects(operations, dims, value)})
        if len(targets) == 8:
            break
    return {"conditions": dims, "operations": [operation_view(n) for n in seeds[:12]],
            "effects": effects[:12], "targets": targets,
            "observation_points": [operation_view(n) for n in operations if n["kind"] == "observation"][:6],
            "declaration": candidate.get("evidence", {}).get("declaration"),
            "default_transfer": behavior.get("default_transfer"),
            "meaning": "Source-supported alternatives and possible effects. The model must decide the required result and whether existing tests already check it. A candidate is not a patch defect."}


def resolve_target(candidate, selection=None):
    """Let the model choose/refine input conditions, without a formal oracle."""
    options = behavioral_distinction(candidate)["targets"]
    if selection is None:
        return options[0] if options else {"id": None, "condition_values": {}, "conditions": []}
    if not isinstance(selection, dict):
        raise ValueError("invalid_target")
    if "id" in selection:
        match = next((t for t in options if t["id"] == selection["id"]), None)
        if match is None:
            raise ValueError("unknown_target_id")
        return match
    chosen = selection.get("condition_values")
    dims = {d["id"]: d for d in candidate.get("behavior", {}).get("conditions", [])}
    if not isinstance(chosen, dict) or not chosen or any(k not in dims or v not in dims[k]["domain"] for k, v in chosen.items()):
        raise ValueError("invalid_target_condition_values")
    return {"id": "target_" + stable_id(chosen), "condition_values": chosen,
            "conditions": [{"id": k, "expression": dims[k]["expression"], "kind": dims[k]["kind"],
                            "value": v, "span": dims[k]["span"]} for k, v in chosen.items()]}


def assess_rows(rows, target, *, truncated=False):
    desired = target["condition_values"]
    if not desired:
        return {"status": "unknown", "reason": "No machine-checkable target condition was selected.", "rows": []}
    checks = []
    for row in rows:
        known = {k: v["value"] for k, v in row["conditions"].items() if k in desired and v.get("known")}
        contradicted = {k: {"wanted": desired[k], "actual": v} for k, v in known.items() if v != desired[k]}
        missing = [k for k in desired if k not in known]
        status = "contradicted" if contradicted else "unknown" if missing or row.get("source_conditions") else "source_supported"
        checks.append({"test_id": row["test_id"], "entry_call": row["entry_call"], "entry": row["entry"],
                       "status": status, "known_values": known, "contradictions": contradicted, "unknown_conditions": missing,
                       "assertions": row.get("assertions", []),
                       "control_barriers": [b for v in row["conditions"].values() for b in v.get("control_barriers", [])]})
    status = ("source_supported" if any(r["status"] == "source_supported" for r in checks)
              else "not_preserved" if checks and not truncated and all(r["status"] == "contradicted" for r in checks) else "unknown")
    return {"status": status, "rows": checks[:16], "rows_truncated": truncated or len(checks) > 16,
            "meaning": "Checks input conditions within one invocation. Source support is not proof of execution, assertion adequacy or a patch bug. A production exit blocking the observation can be the defect."}


def check_generated_conditions(prepared, candidate, response, target):
    """Reparse only local production evidence and the proposed test files.

    Original tests in an appended file are excluded from the check. Unresolved
    dispatch, external setup, shared identity and asynchronous phases stay unknown.
    This function never imports or executes subject code.
    """
    if not target.get("condition_values"):
        return assess_rows([], target)
    sources, starts = {}, {}
    paths = {n["span"]["path"] for n in candidate.get("behavior", {}).get("operations", [])}
    paths.update(candidate.get("source_paths", []))
    for path in sorted(paths):
        record = prepared.get("source_files", {}).get(path)
        if record and record.get("origin", "repository") == "repository" and Path(path).suffix in EXTENSIONS and not is_test_path(path):
            sources[path] = Source(path, record["code"], EXTENSIONS[Path(path).suffix])
    for edit in response["tests"]:
        path = edit["path"]
        original = ""
        if edit["mode"] == "append":
            record = prepared.get("source_files", {}).get(path)
            if record:
                original = record["code"]
            else:
                # Exact snapshot membership, hash and safe path checks also
                # apply to appended test files outside the initial candidate.
                from .presentation import read_source
                original = read_source(prepared, path, max_lines=10**9)["code"]
            original += "\n\n"
        starts[path] = len(original.encode())
        sources[path] = Source(path, original + edit["code"] + "\n", EXTENSIONS[Path(path).suffix])
    if any(source.root.has_error for path, source in sources.items() if path in starts):
        return {"status": "unknown", "reason": "Generated test has a syntax error; repair it before interpreting conditions."}
    try:
        program = build_program(list(sources.values()), "")
        new_tests = {tid for tid, test in program["tests"].items()
                     if test["span"]["path"] in starts and test["span"]["start_byte"] >= starts[test["span"]["path"]]}
        program["calls"] = [c for c in program["calls"] if c["test_id"] in new_tests]
        dimensions = [d for d in candidate["behavior"]["conditions"] if d["id"] in target["condition_values"]]
        # Intermediate helpers remain on the traversal path. Do not spend the
        # per-entry row bound recording unrelated neighbors before reaching the
        # function that actually evaluates the selected condition.
        functions = {d["function_id"] for d in dimensions}
        scope = test_scope(program, program["behavior_graph"], functions, dimensions)
        result = assess_rows(scope["rows"], target, truncated=scope["truncated"])
        result.update(generated_test_definitions=len(new_tests), analyzed_production_files=len(sources) - len(starts))
        return result
    except (KeyError, ValueError, TypeError, RecursionError) as exc:
        return {"status": "unknown", "reason": "Local source analysis could not resolve this test.", "analysis_error": type(exc).__name__}
