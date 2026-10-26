"""Compact, source-linked evidence shared by prompts and inspection tools."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from .distinctions import behavioral_distinction
from .ranking import focus, words


def scope_view(row):
    """One invocation, with known values and assertion text kept together."""
    known = {k: v for k, v in row["conditions"].items() if v.get("known")}
    return {k: row[k] for k in ("id", "test_id", "entry_call", "entry", "function_id", "operation_path", "assertions", "source_conditions", "observation_relation") if k in row} | {
        "conditions": known, "unknown_conditions": [k for k in row["conditions"] if k not in known],
        "execution": row.get("execution", "unknown"),
        "meaning": "One entry invocation. Do not combine this row with another invocation to infer joint coverage."}


def read_source(prepared, path, start_line=1, end_line=None, *, max_lines=160):
    if path not in prepared.get("source_files", {}) and path not in prepared["source_receipts"]:
        raise ValueError("source_not_in_prepared_snapshot")
    if not isinstance(start_line, int) or start_line < 1 or end_line is not None and (not isinstance(end_line, int) or end_line < start_line):
        raise ValueError("invalid_line_range")
    if path in prepared.get("source_files", {}):
        code = prepared["source_files"][path]["code"]
    else:
        repository = Path(prepared["repository"]).resolve()
        source = repository / path
        if not source.resolve().is_relative_to(repository):
            raise ValueError("source_outside_repository")
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != prepared["source_receipts"][path]:
            raise ValueError("prepared_source_changed:" + path)
        code = data.decode()
    lines = code.splitlines()
    requested_end = end_line if end_line is not None else len(lines)
    end = min(requested_end, start_line + max_lines - 1, len(lines))
    return {"path": path, "start_line": start_line, "end_line": end,
            "code": "\n".join(lines[start_line - 1:end]), "total_lines": len(lines),
            "truncated": end < min(requested_end, len(lines))}


def _brief_step(row):
    step = row["step"]
    calls = step.get("tool_calls", [])
    commands = [c.get("arguments", {}).get("command", "") for c in calls]
    feedback = json.dumps(step.get("observation", {}), ensure_ascii=False)
    return {"ordinal": row["ordinal"], "kinds": row["kinds"], "matched_paths": row["matched_paths"],
            "commands": [c[:1800] for c in commands if isinstance(c, str)],
            "commands_truncated": any(len(c) > 1800 for c in commands if isinstance(c, str)),
            "public_feedback": feedback[:2400], "feedback_truncated": len(feedback) > 2400,
            "execution_status": row["execution_status"]}


def evidence_payload(prepared, candidate, *, max_chars=64000):
    behavior = candidate.get("behavior", {})
    operations = behavior.get("operations", [])
    seed_ids = set(candidate.get("evidence", {}).get("source_operations", []))
    ordered = sorted(operations, key=lambda n: (n["id"] not in seed_ids, not n["changed"], n["span"]["path"], n["span"]["line"]))
    excerpts, seen = [], set()
    for op in ordered[:12]:
        loc = op["span"]
        identity = (loc["path"], loc["line"])
        if identity in seen:
            continue
        seen.add(identity)
        excerpts.append(read_source(prepared, loc["path"], max(1, loc["line"] - 2), loc["end_line"] + 2, max_lines=48))
    for path in candidate.get("resource_paths", []):
        declaration = candidate.get("evidence", {}).get("declaration") or {}
        excerpts.append(read_source(prepared, path, max(1, declaration.get("line", 1) - 4), declaration.get("end_line", 1) + 4, max_lines=40))
    scope = candidate.get("test_scope", {"rows": [], "truncated": True})
    # Known rows first, but retain uncertain examples as distinct evidence.
    seed_functions = {n["function_id"] for n in focus(candidate)}
    scope_rows = sorted(scope["rows"], key=lambda row: (row["function_id"] not in seed_functions,
                        -sum(v.get("known", False) for v in row["conditions"].values()), not bool(row["assertions"]), row["id"]))
    query_words = words(" ".join(n.get("code", "") for n in focus(candidate)))
    row_order = {r["test_id"]: i for i, r in reversed(list(enumerate(scope_rows)))}
    ranked_tests = sorted(candidate["test_ids"], key=lambda tid: (
        -len(words(prepared["tests"][tid]["code"]) & query_words), row_order.get(tid, len(scope_rows)), tid))
    selected_tests = list(dict.fromkeys([r["test_id"] for r in scope_rows[:4]] + ranked_tests))[:8]
    tests = []
    for tid in selected_tests:
        test = prepared["tests"][tid]
        tests.append({**test, "code": test["code"][:4000], "code_truncated": len(test["code"]) > 4000})
    cells = behavior.get("combinations", {})
    analysis = {k: candidate[k] for k in ("id", "family", "scope", "reason", "contrast", "status")}
    analysis.update(condition_dimensions=behavior.get("condition_dimensions", 0), relation_count=behavior.get("relation_count", 0),
                    conditions=behavior.get("conditions", []), missing_joint_checks=cells.get("missing", [])[:12],
                    uncertain_joint_checks=cells.get("unknown", [])[:8], witnessed_joint_inputs=cells.get("checked", [])[:8],
                    combination_search_truncated=cells.get("truncated", False),
                    witness_meaning=cells.get("meaning", "Source evidence does not prove assertion adequacy or execution."),
                    declaration=candidate.get("evidence", {}).get("declaration"))
    payload = {"public_requirement": prepared["issue"], "analysis_candidate": analysis,
               "behavioral_distinction": behavioral_distinction(candidate),
               "program_relations": candidate["relations"][:30],
               "operations": [{k: n[k] for k in ("id", "function_id", "kind", "span", "changed", "conditions", "reads", "input_origin_reads", "target", "resolution") if k in n}
                              | {"code": n["code"][:650], "code_truncated": n.get("code_truncated", False) or len(n["code"]) > 650}
                              for n in ordered[:24]],
               "test_scope": [scope_view(r) for r in scope_rows[:16]], "related_tests": tests, "source_excerpts": excerpts,
               "trajectory": [_brief_step(r) for r in candidate.get("trajectory", [])],
               "history_chain": candidate.get("history_chain", {}), "analysis_limits": prepared["analysis"]["limits"],
               "available_tests": [{"id": tid, "name": prepared["tests"][tid]["name"], "path": prepared["tests"][tid]["span"]["path"]}
                                   for tid in candidate["test_ids"][:40]],
               "input_scope": {"all_related_tests": len(candidate["test_ids"]), "all_source_rows": len(scope["rows"]),
                               "analysis_truncated": scope.get("truncated", False),
                               "presentation_truncated": (len(ordered) > 24 or len(scope_rows) > 24 or len(candidate["test_ids"]) > 8
                                                          or len(candidate["relations"]) > 30),
                               "meaning": "Absence in a shortened prompt is not absence in the repository. Inspect more evidence when needed."}}
    payload["test_edit_context"] = {
        "append_location": "After the complete file, at module scope. Function-local fixtures and nested describe-block bindings are not in scope there.",
        "instruction": "Inspect the target file's imports, outer declarations and end before appending. Reuse only helpers visible at module scope, or define a new local fixture.",
        "files": list(dict.fromkeys(t["span"]["path"] for t in payload["related_tests"] if t.get("origin") == "repository"))}
    # Remove whole optional records, not arbitrary pieces of JSON or assertion expressions.
    # Relations and scope rows duplicate the compact behavioral distinction.
    # Remove those first; preserve concrete seed source and useful test code.
    optional = ("program_relations", "operations", "test_scope", "trajectory", "source_excerpts", "related_tests")
    while True:
        payload["input_scope"].update(included_tests=len(payload["related_tests"]), included_source_rows=len(payload["test_scope"]))
        if len(json.dumps(payload, ensure_ascii=False)) <= max_chars:
            break
        key = next((k for k in optional if len(payload[k]) > 1), None)
        if key is None:
            break
        payload[key].pop()
        payload["input_scope"]["presentation_truncated"] = True
    return payload


def inspect(prepared, candidate, query):
    kind = query.get("kind")
    if kind == "source":
        return read_source(prepared, query["path"], query.get("start_line", 1), query.get("end_line"))
    if kind == "tests":
        offset = query.get("offset", 0)
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid_test_offset")
        requested_ids = query.get("test_ids") or []
        if not isinstance(requested_ids, list) or len(requested_ids) > 8 or any(t not in prepared["tests"] for t in requested_ids):
            raise ValueError("invalid_test_query")
        path = query.get("path")
        start, end = query.get("start_line", 1), query.get("end_line")
        if not isinstance(start, int) or start < 1 or end is not None and (not isinstance(end, int) or end < start):
            raise ValueError("invalid_line_range")
        if path is not None:
            if not isinstance(path, str) or not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                raise ValueError("invalid_test_query_path")
            path = path.removeprefix("./").rstrip("/")
        elif "start_line" in query or "end_line" in query:
            if not requested_ids:
                raise ValueError("test_line_range_requires_path_or_ids")
        inventory = requested_ids or (list(prepared["tests"]) if path is not None else candidate["test_ids"])
        matches = []
        for tid in inventory:
            test = prepared["tests"][tid]
            loc = test["span"]
            paths = [loc["path"], test.get("written_path")]
            if path is not None and not any(p and (p == path or p.startswith(path + "/")) for p in paths):
                continue
            if loc["end_line"] < start or end is not None and loc["line"] > end:
                continue
            matches.append(tid)
        matches.sort(key=lambda tid: (prepared["tests"][tid].get("origin") != "repository",
                                     prepared["tests"][tid]["span"]["path"], prepared["tests"][tid]["span"]["line"], tid))
        ids = matches[offset:offset + (8 if requested_ids else 6)]
        known_paths = set(prepared.get("source_files", {})) | set(prepared.get("source_receipts", {}))
        path_known = path is None or any(p == path or p.startswith(path + "/") for p in known_paths)
        return {"tests": [{**prepared["tests"][t], "code": prepared["tests"][t]["code"][:12000],
                           "code_truncated": len(prepared["tests"][t]["code"]) > 12000} for t in ids],
                "query_scope": {"path": path, "start_line": start, "end_line": end,
                                "inventory": "snapshot" if path is not None else "explicit_ids" if requested_ids else "candidate"},
                "total_tests": len(matches), "offset": offset, "has_more": offset + len(ids) < len(matches),
                "status": "matched" if ids else "no_indexed_test_in_requested_range" if path_known else "path_not_in_snapshot",
                "meaning": "Matches are indexed test definitions. An empty result does not prove that the repository has no effective test."}
    if kind == "scope":
        offset = query.get("offset", 0)
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid_scope_offset")
        scope = candidate.get("test_scope", {"rows": [], "truncated": True})
        return {**scope, "rows": scope["rows"][offset:offset + 24], "offset": offset, "total_rows": len(scope["rows"])}
    if kind == "relations":
        index = prepared.get("relation_index", {})
        operation = query.get("operation_id")
        offset = query.get("offset", 0)
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid_relation_offset")
        links = candidate["relations"]
        operations = candidate.get("behavior", {}).get("operations", [])
        if operation is not None:
            if operation not in index.get("nodes", {}):
                raise ValueError("unknown_operation")
            links = [e for e in index["edges"] if operation in {e["from"], e["to"]}]
            ids = {operation} | {i for edge in links[offset:offset + 16] for i in (edge["from"], edge["to"])}
            operations = [index["nodes"][i] for i in sorted(ids)]
        return {"relations": links[offset:offset + 16], "operations": operations[:18],
                "total_relations": len(links), "offset": offset,
                "other_candidates": [{"id": c["id"], "reason": c["reason"]} for c in prepared["candidates"]
                                     if c["id"] != candidate["id"] and set(c["function_ids"]) & set(candidate["function_ids"])][:8]}
    if kind == "history":
        if "ordinal" in query:
            row = next((r for r in candidate.get("trajectory", []) if r["ordinal"] == query["ordinal"]), None)
            if row is None:
                raise ValueError("history_step_outside_candidate")
            # The public step retains complete feedback. The agent's response
            # size bound can ask for a narrower source query if it is too large.
            return {"trajectory_step": row, "chain": candidate.get("history_chain", {})}
        return {"trajectory": [_brief_step(r) for r in candidate.get("trajectory", [])], "chain": candidate.get("history_chain", {})}
    if kind == "requirement":
        return {"public_requirement": prepared["issue"]}
    raise ValueError("unknown_inspection_kind")
