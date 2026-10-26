"""Public trajectory evidence. Historical commands are never executed."""
from __future__ import annotations

import json
import re

from anchor_retrieval.syntax import Source, units
from relational_gap.history import recover_history

from .program import stable_id

PRIVATE = {"reasoning_content", "analysis", "final_metrics", "metrics", "manual_labels", "labels"}


def _public(value):
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items() if k not in PRIVATE}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def public_trajectory(document):
    steps = []
    for ordinal, step in enumerate(document.get("steps", [])):
        public = {k: _public(step[k]) for k in ("step_id", "timestamp", "source", "message", "observation") if k in step}
        public.setdefault("step_id", ordinal)
        calls = []
        for call in step.get("tool_calls") or []:
            function = call.get("function", {})
            args = call.get("arguments", function.get("arguments", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    continue
            if not isinstance(args, dict):
                continue
            args = _public(args)
            if isinstance(args.get("cmd"), str) and "command" not in args:
                args["command"] = args.pop("cmd")
            calls.append({"function_name": call.get("function_name", function.get("name", "")), "arguments": args})
        public["tool_calls"] = calls
        steps.append(public)
    return {"steps": steps}


def recover_tests(document, language):
    public = public_trajectory(document)
    recovered, report = recover_history(public, language, max_bytes=10_000_000, max_versions=10000)
    result, seen = [], set()
    for source in recovered:
        if source.language != language:
            continue
        test_units = [u for u in units(source)[0] if u.test]
        if not test_units and not re.search(r"\bprint\s*\(", source.code):
            continue
        identity = (source.code, source.written_path, source.step)
        if identity in seen:
            continue
        seen.add(identity)
        # Unique virtual paths preserve distinct historical versions.
        suffix = {"python": ".py", "typescript": ".ts", "go": ".go"}[language]
        path = "trajectory/" + stable_id(*identity) + suffix
        result.append(Source(path, source.code, language, "trajectory", source.step, source.written_path))
    return result, report


def related_steps(document, paths, names):
    paths = set(paths)
    names = {n for n in names if len(n) >= 3}
    result = []
    for ordinal, step in enumerate(public_trajectory(document)["steps"]):
        commands = [c["arguments"].get("command", "") for c in step["tool_calls"]]
        selector = str(step.get("message", "")) + "\n" + "\n".join(c for c in commands if isinstance(c, str))
        identifiers = set(re.findall(r"[A-Za-z_$][\w$]*", selector))
        # Match complete path tokens, not arbitrary substrings such as x.py in other_x.py.
        tokens = set(re.findall(r"[A-Za-z0-9_./-]+\.(?:py|go|tsx?)(?![\w.])", selector))
        hit_paths = sorted(p for p in paths if any(t == p or t.endswith("/" + p) for t in tokens))
        hit_names = sorted(names & identifiers)
        if not hit_paths and not hit_names:
            continue
        kinds = []
        command_text = "\n".join(c for c in commands if isinstance(c, str))
        if re.search(r"\b(cat|sed|rg|grep|head|tail)\b|read_text\s*\(", command_text):
            kinds.append("read")
        if re.search(r"apply_patch|write_text\s*\(|\bcat\b[^\n]*>|\bsed\s+-i", command_text):
            kinds.append("edit")
        if re.search(r"\b(pytest|vitest|jest)\b|\bgo\s+test\b|\b(?:npm|pnpm)\s+(?:run\s+)?test\b|\bpython[\d.]*\s", command_text):
            kinds.append("validation_command")
        result.append({"id": "history_" + stable_id(ordinal, step), "ordinal": ordinal,
                       "matched_paths": hit_paths, "matched_names": hit_names, "kinds": kinds,
                       "step": step, "execution_status": "command_and_feedback_only_version_not_proved"})
    return result


def index_history(document):
    """Index public actions once. A command is not proof of final-version execution."""
    indexed = []
    for ordinal, step in enumerate(public_trajectory(document)["steps"]):
        commands = [c["arguments"].get("command", "") for c in step.get("tool_calls", [])]
        text = "\n".join(c for c in commands if isinstance(c, str))
        selector = text + "\n" + str(step.get("message", ""))
        kinds = []
        if re.search(r"\b(cat|sed|rg|grep|head|tail)\b|read_text\s*\(", text): kinds.append("read")
        if re.search(r"apply_patch|write_text\s*\(|\bcat\b[^\n]*>|\bsed\s+-i", text): kinds.append("edit")
        if re.search(r"\b(pytest|vitest|jest)\b|\bgo\s+test\b|\b(?:npm|pnpm)\s+(?:run\s+)?test\b|\bpython[\d.]*\s", text): kinds.append("validation_command")
        indexed.append({"id": "history_" + stable_id(ordinal, step), "ordinal": ordinal,
                        "paths": sorted(set(re.findall(r"[A-Za-z0-9_./-]+\.(?:py|go|tsx?|ya?ml)(?![\w.])", selector))),
                        "names": sorted(set(re.findall(r"[A-Za-z_$][\w$]*", selector))),
                        "kinds": kinds, "step": step})
    return indexed


def history_chain(index, paths, names, *, max_steps=12):
    """Keep edits, their neighboring reads/runs, and later validation feedback."""
    paths, names = set(paths), {n for n in names if len(n) >= 3}
    relevant, validations = [], []
    for row in index:
        matched_paths = sorted(p for p in paths if any(t == p or t.endswith("/" + p) for t in row["paths"]))
        matched_names = sorted(names & set(row["names"]))
        record = {k: row[k] for k in ("id", "ordinal", "kinds", "step")}
        record.update(matched_paths=matched_paths, matched_names=matched_names,
                      execution_status="command_and_feedback_only_version_not_proved")
        if matched_paths or matched_names:
            relevant.append(record)
        if "validation_command" in row["kinds"]:
            validations.append(record)
    edits = [r for r in relevant if "edit" in r["kinds"]]
    selected = {r["ordinal"]: r for r in relevant[-max_steps:]}
    for edit in edits[-3:]:
        selected[edit["ordinal"]] = edit
        before = [r for r in relevant if r["ordinal"] < edit["ordinal"] and "read" in r["kinds"]]
        after = [r for r in validations if r["ordinal"] >= edit["ordinal"]]
        for row in before[-1:] + after[:1]:
            selected[row["ordinal"]] = row
    for row in validations[-2:]:
        selected[row["ordinal"]] = row
    rows = [selected[n] for n in sorted(selected)]
    # Preserve action types rather than silently treating missing runs as never run.
    if len(rows) > max_steps:
        essential = {r["ordinal"] for r in edits[-2:] + validations[-2:]}
        chosen = [r for r in rows if r["ordinal"] in essential]
        chosen.extend(r for r in reversed(rows) if r["ordinal"] not in essential)
        rows = sorted(chosen[:max_steps], key=lambda r: r["ordinal"])
    last_edit = max((r["ordinal"] for r in edits), default=None)
    return {"steps": rows, "last_related_edit": last_edit,
            "validation_after_last_edit": [r["ordinal"] for r in validations if last_edit is None or r["ordinal"] > last_edit],
            "final_version_execution": "unknown_without_matching_source_receipt",
            "truncated": len(relevant) > max_steps,
            "meaning": "Read/edit/test ordering is public evidence, not the agent's intent or verified test selection."}
