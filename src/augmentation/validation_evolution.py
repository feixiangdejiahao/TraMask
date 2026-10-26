"""Validation evolution and executable observations for an augmentation pilot.

Only original issue/source/trajectory are read. Historical edits are recovered
as text, never executed. AST facts retain locations and do not claim reachability.
"""
from __future__ import annotations

import ast
from collections import defaultdict
import difflib
import hashlib
import json
from pathlib import Path
import re

from anchor_retrieval.syntax import (
    Source, CALLS, child, call_parts, diff_lines, is_test_path, trajectory_sources, units, walk,
)
from augmentation import validation_context_pilot as previous
from augmentation.context_query_recovery import serve_queries as basic_queries
from augmentation.contrast_pilot import make_blocks
from augmentation.pipeline import write_json
from augmentation.program import ASSIGNMENTS, EXTENSIONS, _assignment
from augmentation.trajectory_contrast import excerpt, trajectory_index

COMMON = previous.COMMON + """
Use compact English JSON. Keep explanations short; do not repeat the input.
The original validation may hide a behavior difference by holding a condition
fixed, simplifying a sequence or observing the wrong object. Seek requirement-
relevant alternate contexts. If history is present, changes in test setup,
operations or assertions may guide this choice. They are clues, not an oracle.
You may reject this hypothesis and report selection, oracle or feedback problems.
Do not force three bugs to exist. Keep distinct targets, not three spellings of
one target. Rank them before seeing execution feedback. Preserve their IDs.
"""

INVESTIGATE = """Investigate up to THREE distinct combination targets. Return:
{"hypotheses":[{"id":"h1","original_validation":"test ID and checked behavior",
"restriction":"condition or observation that limits this validation",
"alternate_context":"legal concrete input/state/operation combination",
"expected":"requirement-supported result","predicted":"current behavior",
"basis":"issue/API source","history_added":"specific edit or none"}],
"queries":[{"kind":"source|search|test|connections|slice|history|history_search|evolution",
"path":"relative path","line":1,"symbol":"optional name","text":"literal text",
"test_id":"known test ID","step":1}],"notes":"uncertainty"}.
At most six queries. source/search/test/connections retrieve original material.
slice returns AST-local assignments, calls and enclosing conditions at path:line.
evolution returns recovered versions of the same named test, if available.
history/history_search require supplied development_history. Missing excerpts
never prove a missing test. Use queries that can disprove a proposed gap.
"""

PROBE = """Refine and rank at most THREE hypotheses using the retrieved evidence.
For each, propose a small executable observation that could support or refute
the alleged behavior distinction. This is an investigation, not yet a bug claim.
Return {"hypotheses":[{"id":"h1","original_validation":"...",
"restriction":"...","alternate_context":"...","expected":"...",
"predicted":"...","basis":"...","history_added":"...",
"question":"one uncertainty the observation can settle",
"probe":{"tests":[{"path":"relative test path","mode":"new|append",
"code":"complete executable test code"}]}}],"notes":"..."}.
At most ONE file and TWO named tests per hypothesis. Prefer printing observed
values, branch evidence, call order or object identity for original and alternate
contexts; do not assert that a behavior is a bug in this diagnostic probe.
Use normal APIs and the native test framework. Every test name contains CCPilot.
Go names start TestCCPilot; Python names start test_CCPilot. Log with t.Logf,
print or console.log. The runner enables Go verbose and pytest output capture off.
The probes may or may not be executed in the experimental setting. Do not assume
an observation occurred without an execution result. No production edits.
New files need their own imports. Append only adds to the end of an existing file.
Stay within one package per hypothesis. Code should be short (prefer <=100 lines).
"""

BUILD = """Select at most THREE targets, preserving their prior IDs and ranking.
Return {"targets":[{"id":"h1","decision":"gap|selection_problem|oracle_problem|feedback_problem|unknown|no_gap_found",
"combination":"concrete interacting conditions",
"original_validation":"specific test IDs and their scope",
"new_context":"legal construction and operations","required_result":"...",
"predicted_current_result":"...","public_basis":"independent requirement",
"source_evidence":["path:line and fact"],"history_added":"what versions/events added, or none",
"observations_used":"actual observations and how they changed the target, or none",
"conditions":["essential condition and the test action that establishes it"],
"tests":[{"path":"relative test path","mode":"new|append","code":"complete code"}],
"notes":"uncertainty or reason for withdrawal"}],"notes":"..."}.
For each gap, supply at most ONE file and TWO named tests: a targeted combination
and optionally a passing control. Each target runs in a separate fresh container.
Do not put unrelated bug claims into one target. All names contain CCPilot;
Go starts TestCCPilot and Python starts test_CCPilot. Use native frameworks.
New files include imports/helpers; append cannot add imports at file start.
Prefer existing public setup. Do not change production or redefine public APIs.
Use actual original-patch observations when supplied, but derive the expectation
independently. Failure alone is not a bug. Do not invent states only to cause failure.
Put tests inside EACH target, including an empty tests list when no code is justified.
There is no top-level tests field. Keep every target self-contained.
"""

REVISE = """Review the draft targets with their original-patch executions once.
Return the complete BUILD object including all final test code. Keep target IDs
and ranking. Repair setup and implementation mistakes. Withdraw unsupported
claims. Do not add an unrelated target now. Preserve independently justified
failing expectations. Distinguish a compile/setup error from a behavior failure.
"""


def read(path):
    return json.loads(Path(path).read_text())


def hid(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def test_row(source, unit):
    return {"id": unit.id, "name": unit.name, "path": source.path, "line": unit.line,
            "end_line": unit.node.end_point.row+1, "code": source.text(unit.node),
            "origin": source.origin, "written_path": source.written_path, "step_id": source.step}


def rank_tests(tests, issue, changed, cap=60000):
    words = set(re.findall(r"[A-Za-z_]\w{3,}", issue.lower()))
    def score(t):
        path = t.get("written_path") or t["path"]
        overlap = len(words & set(re.findall(r"[A-Za-z_]\w{3,}", (t["name"]+t["code"][:1600]).lower())))
        return (-int(path in changed), -overlap, path, t["line"], t["id"])
    result, size, seen = [], 0, set()
    for t in sorted(tests, key=score):
        key = hid([t.get("written_path") or t["path"], t["name"], t["code"]])
        if key in seen or size+len(t["code"]) > cap or len(result) >= 60:
            continue
        result.append(t); size += len(t["code"]); seen.add(key)
    return result


def statement_facts(code, language, path):
    source = Source(path, code, language)
    result = {"assignments": [], "calls": [], "checks": []}
    for n in walk(source.root):
        text = source.text(n)
        row = {"line": n.start_point.row+1, "code": text[:700]}
        if n.type in ASSIGNMENTS:
            result["assignments"].append(row)
        elif n.type in CALLS:
            fn, args = call_parts(n)
            name = source.text(fn)
            row.update(callee=name, arguments=[source.text(a)[:250] for a in args])
            result["checks" if re.search(r"assert|expect|Equal|require\.", name) else "calls"].append(row)
        elif n.type == "assert_statement":
            result["checks"].append(row)
    return {k: v[:20] for k, v in result.items()}


def changed_facts(before, after, language, path):
    left, right = [statement_facts(code, language, path) for code in (before, after)]
    result = {}
    for key in left:
        a = {r["code"] for r in left[key]}
        b = {r["code"] for r in right[key]}
        result[key] = {"removed": [s[:350] for s in sorted(a-b)[:5]],
                       "added": [s[:350] for s in sorted(b-a)[:5]]}
    return result


def bounded_rows(rows, limit):
    result, size = [], 0
    for row in rows:
        cost = len(json.dumps(row))
        if size+cost <= limit:
            result.append(row); size += cost
    return result


def literal_test_edits(events):
    """Recover explicit test edit fragments; never pretend they are full files."""
    rows = []
    for event in events:
        command = event["command"]
        # apply_patch blocks retain literal old/new lines, including context.
        for m in re.finditer(r"\*\*\* (?:Update|Add) File: ([^\n]+)\n(.*?)(?=\n\*\*\* (?:Update|Add|Delete|End)|\Z)", command, re.S):
            path, body = m.group(1).strip().removeprefix("/repo/"), m.group(2)
            if not is_test_path(path):
                continue
            for part in re.split(r"^@@[^\n]*\n", body, flags=re.M):
                lines = part.splitlines()
                if not any(l.startswith(("+", "-")) for l in lines):
                    continue
                before = "\n".join(l[1:] for l in lines if l.startswith((" ", "-")))
                after = "\n".join(l[1:] for l in lines if l.startswith((" ", "+")))
                rows.append({"step": event["step"], "path": path, "before": before, "after": after,
                             "kind": "literal_patch_fragment", "complete_test": False})
        # Literal replacements inside Python edit scripts. Path must be explicit
        # and unique in the same command. No Python or shell is evaluated.
        paths = {p.removeprefix("/repo/") for p in re.findall(r"['\"]([\w./-]+\.(?:py|go|tsx?))['\"]", command) if is_test_path(p)}
        if len(paths) != 1:
            continue
        snippets = [s.code for s in trajectory_sources({"steps": [{"step_id": event["step"], "tool_calls": [{"arguments": {"command": command}}]}]}, "python") if s.language == "python"]
        for snippet in snippets:
            try:
                tree = ast.parse(snippet)
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute) or n.func.attr != "replace" or len(n.args) < 2:
                    continue
                try:
                    before, after = ast.literal_eval(n.args[0]), ast.literal_eval(n.args[1])
                except (ValueError, TypeError):
                    continue
                if isinstance(before, str) and isinstance(after, str) and before != after:
                    rows.append({"step": event["step"], "path": next(iter(paths)), "before": before, "after": after,
                                 "kind": "literal_replacement_requested", "complete_test": False,
                                 "limit": "Recorded edit request, not proof it applied or ran."})
    return rows


def build_inputs(case):
    repo = Path(case["repository"])
    index = previous.file_index(repo)
    issue = Path(case["issue"]).read_text()
    changed = diff_lines(Path(case["candidate_patch"]).read_text())
    final_tests, source_groups = [], []
    for path in index:
        language = EXTENSIONS.get(Path(path).suffix)
        if language != case["language"]:
            continue
        if is_test_path(path):
            src = Source(path, (repo/path).read_text(errors="replace"), language)
            final_tests.extend(test_row(src, u) for u in units(src)[0] if u.test)
        elif path in changed:
            source_groups.append(make_blocks(path, (repo/path).read_text(errors="replace"), changed[path], context=20))
    blocks, size = [], 0
    for i in range(max(map(len, source_groups), default=0)):
        for group in source_groups:
            if i < len(group) and size+len(group[i]["code"]) <= 150000:
                blocks.append(group[i]); size += len(group[i]["code"])
    chosen = rank_tests(final_tests, issue, changed)
    visible_index = bounded_rows([p for p in index if Path(p).suffix in EXTENSIONS], 24000)
    base = {"public_requirement": issue, "changed_paths": sorted(changed), "source": blocks,
            "validation_tests": chosen, "source_file_index": visible_index,
            "limits": {"final_tests_only": True, "all_final_test_count": len(final_tests), "selected_test_count": len(chosen),
                       "test_code_cap": 60000, "modified_source_cap": 150000,
                       "source_index_partial": len(visible_index) != len(index),
                       "meaning": "Final source presence is not proof of execution. Excerpts and visible path index are incomplete. Literal search queries cover the full public repository."},
            "test_environment": {"language": case["language"], "name_marker": "CCPilot",
                                 "execution": "Fresh original-patch container, native framework, network disabled; one file per target."}}
    base["test_environment"]["example_test_paths"] = list(dict.fromkeys(t["path"] for t in chosen))[:8]
    config_paths = sorted([p for p in index if re.search(r"(?:vitest|jest)\.config|(?:^|/)pytest\.ini$|(?:^|/)pyproject\.toml$", p)], key=lambda p: (len(Path(p).parts), p))[:4]
    base["test_environment"]["configuration_excerpts"] = [{"path": p, "code": excerpt((repo/p).read_text(errors="replace"), 4000)} for p in config_paths]
    trajectory = read(case["trajectory"])
    history, events = trajectory_index(case, base)
    history["episodes"] = bounded_rows(history["episodes"], 45000)
    history["timeline"] = [{k: e[k] for k in ("step", "kinds", "paths", "returncodes", "failure_text")} for e in history["timeline"]]
    history["test_event_links"] = [{**r, "associated_steps": r["associated_steps"][:20]} for r in history["test_event_links"]]
    history["counts"]["detailed"] = len(history["episodes"])
    history["limits"] += " Detailed episodes capped at 45000 characters; associations list first 20 matches. Full events remain available through history queries."
    steps = {str(s.get("step_id")): s for s in trajectory.get("steps", [])}
    for e in events:
        step = steps.get(str(e["step"]), {})
        e["agent_note"] = str(step.get("message", ""))+"\n"+str(step.get("reasoning_content", ""))
    old_tests = []
    for src in trajectory_sources(trajectory, case["language"]):
        if src.language == case["language"]:
            old_tests.extend(test_row(src, u) for u in units(src)[0] if u.test)
    versions = rank_tests(old_tests, issue, changed, cap=60000)
    groups = defaultdict(list)
    for t in versions:
        groups[(t.get("written_path") or t["path"], t["name"])].append(t)
    final_by_key = {(t["path"], t["name"]): t for t in final_tests}
    transitions = []
    for key, group in sorted(groups.items()):
        ordered = sorted(group, key=lambda t: (str(t.get("step_id") or "").zfill(10), t["id"]))
        if key in final_by_key:
            ordered.append(final_by_key[key])
        for before, after in zip(ordered, ordered[1:]):
            if before["code"] == after["code"]:
                continue
            transitions.append({"path": key[0], "name": key[1], "before_id": before["id"], "after_id": after["id"],
                                "before_step": before["step_id"], "after_step": after["step_id"],
                                "diff": excerpt("\n".join(difflib.unified_diff(before["code"].splitlines(), after["code"].splitlines(), lineterm="")), 2500),
                                "changed_facts": changed_facts(before["code"], after["code"], case["language"], key[0]),
                                "matching": "same explicit path and test name; intermediate versions may be absent"})
    edits = literal_test_edits(events)
    evolution = {"historical_tests": versions, "transitions": bounded_rows(transitions[:30], 45000), "edit_fragments": bounded_rows(edits[:45], 30000),
                 "limits": "Literal writes, named test alignment and explicit edit fragments only. Not complete trajectory replay. No inferred semantic cause or execution."}
    return base, evolution, history, events


def local_slice(case, query):
    path = previous.public_file(case["repository"], query.get("path", ""))
    language = EXTENSIONS.get(path.suffix)
    if language is None:
        raise ValueError("unsupported_source_language")
    source = Source(str(path.relative_to(Path(case["repository"]).resolve())), path.read_text(), language)
    line = query.get("line", 1)
    if type(line) is not int or line < 1:
        raise ValueError("invalid_line")
    us = [u for u in units(source)[0] if u.line <= line <= u.node.end_point.row+1]
    if not us:
        return {"window": previous.read_window(case["repository"], query), "limit": "No enclosing function resolved."}
    unit = min(us, key=lambda u: u.node.end_byte-u.node.start_byte)
    focus = [n for n in walk(unit.node) if n.start_point.row+1 <= line <= n.end_point.row+1]
    target = min((n for n in focus if n.type in ASSIGNMENTS | CALLS | {"return_statement", "if_statement", "assert_statement"}),
                 key=lambda n: n.end_byte-n.start_byte, default=unit.node)
    wanted = set(re.findall(r"[A-Za-z_$][\w$]*", query.get("symbol") or source.text(target)))
    definitions = []
    candidates = [n for n in walk(unit.body) if n.type in ASSIGNMENTS and n.start_point.row+1 <= line]
    for _ in range(3):
        for n in reversed(candidates):
            lhs, rhs = _assignment(n)
            if lhs is None or rhs is None:
                continue
            if not wanted.intersection(re.findall(r"[A-Za-z_$][\w$]*", source.text(lhs))):
                continue
            row = {"line": n.start_point.row+1, "written": source.text(lhs), "expression": source.text(rhs)}
            if row not in definitions:
                definitions.append(row)
            wanted.update(re.findall(r"[A-Za-z_$][\w$]*", source.text(rhs)))
    guards = []
    n = target
    while n != unit.node and n.parent is not None:
        if n.type in {"if_statement", "for_statement", "while_statement", "conditional_expression"}:
            cond = child(n, "condition", "test")
            if cond is not None:
                guards.append({"line": cond.start_point.row+1, "condition": source.text(cond)})
        n = n.parent
    return {"path": source.path, "function": unit.name, "parameters": unit.params,
            "focus": {"line": target.start_point.row+1, "code": source.text(target)[:3500]},
            "local_definitions": definitions[:18], "enclosing_conditions": guards,
            "function_source": excerpt(source.text(unit.node), 12000), "sha256": previous.digest(path),
            "limit": "AST locations and local text dependencies. Definitions may be conditional or shadowed. No proven dynamic alias, path feasibility or required behavior."}


def serve_queries(case, base, evolution, events, queries, arm):
    history_allowed = arm in {"C_history", "D_probe"}
    history_tests = evolution["historical_tests"] if arm != "A_final" else []
    pool = {**base, "source_file_index": previous.file_index(case["repository"]),
            "validation_tests": base["validation_tests"]+history_tests}
    answers = []
    for query in queries[:6] if isinstance(queries, list) else []:
        try:
            if query.get("kind") == "slice":
                answers.append({"query": query, "answer": local_slice(case, query)})
            elif query.get("kind") == "evolution":
                if arm == "A_final":
                    raise ValueError("historical_versions_unavailable_in_this_arm")
                tid = query.get("test_id")
                selected = [t for t in pool["validation_tests"] if t["id"] == tid]
                if not selected:
                    raise ValueError("unknown_test_id")
                t = selected[0]; path = t.get("written_path") or t["path"]
                answers.append({"query": query, "answer": {"versions": [v for v in pool["validation_tests"] if (v.get("written_path") or v["path"]) == path and v["name"] == t["name"]],
                    "edits": [e for e in evolution["edit_fragments"] if e["path"] == path]}})
            else:
                answers.extend(basic_queries(case, pool, events, [query], history_allowed=history_allowed))
        except (ValueError, KeyError, OSError, TypeError) as exc:
            answers.append({"query": query, "error": str(exc)[:300]})
    return answers


def validate(value, stage):
    if not isinstance(value, dict):
        raise ValueError("not_object")
    key = "hypotheses" if stage in {1, 2} else "targets"
    rows = value.get(key)
    if not isinstance(rows, list) or len(rows) > 3:
        raise ValueError("invalid_"+key)
    ids = [r.get("id") for r in rows if isinstance(r, dict)]
    if len(ids) != len(rows) or len(set(ids)) != len(ids) or any(i not in {"h1", "h2", "h3"} for i in ids):
        raise ValueError("invalid_target_ids")
    if stage == 1 and (not isinstance(value.get("queries", []), list) or len(value.get("queries", [])) > 6):
        raise ValueError("invalid_queries")
    if stage >= 3:
        # A single target has an unambiguous owner for accidentally top-level
        # test code. Move bytes only; preserve this mechanical normalization.
        if len(rows) == 1 and "tests" not in rows[0] and isinstance(value.get("tests"), list):
            rows[0]["tests"] = value["tests"]
            value["transport_normalization"] = "single_target_top_level_tests"
        for row in rows:
            if row.get("decision") != "gap" and "tests" not in row:
                row["tests"] = []
                row["transport_normalization"] = "non_gap_missing_tests_is_empty"
            if row.get("decision") not in {"gap", "selection_problem", "oracle_problem", "feedback_problem", "unknown", "no_gap_found"}:
                raise ValueError("invalid_decision")
            if not isinstance(row.get("tests"), list):
                raise ValueError("invalid_test_list")
            if len(row["tests"]) > 1:
                raise ValueError("one_test_file_per_target")
            if row["decision"] == "gap" and not row["tests"]:
                row["generation_missing"] = True
    if stage == 2:
        for row in rows:
            ts = row.get("probe", {}).get("tests", [])
            if not isinstance(ts, list) or len(ts) > 1:
                raise ValueError("one_probe_file_per_target")
    return value


def materialize(case, response):
    # Extend the previous materializer to Python without changing the frozen v1.
    if case["language"] != "python":
        return previous.materialize_tests(case, response)
    repo = Path(case["repository"]).resolve()
    files, names = {}, []
    for edit in response.get("tests", []):
        p = Path(str(edit.get("path", "")))
        if p.is_absolute() or ".." in p.parts or p.suffix != ".py" or not is_test_path(str(p)) or any(x.startswith(".") for x in p.parts):
            raise ValueError("invalid_python_test_path")
        target = (repo/p).resolve()
        if not target.is_relative_to(repo):
            raise ValueError("test_outside_repository")
        code = edit.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("empty_test")
        if edit.get("mode") == "append":
            content = previous.public_file(repo, str(p)).read_text()+"\n\n"+code+"\n"
        elif edit.get("mode") == "new" and not target.exists():
            content = code+"\n"
        else:
            raise ValueError("invalid_new_or_append_mode")
        found = [u.name for u in units(Source(str(p), code, "python"))[0] if u.test]
        if any("CCPilot" not in name for name in found):
            raise ValueError("test_name_missing_marker")
        names.extend(found); files[str(p)] = content
    if not names:
        raise ValueError("no_named_tests")
    return files, sorted(set(names))


def execute(case, response, directory, *, probe=False):
    from combination_testing.runner import freeze_artifact, run_artifact
    directory = Path(directory)
    if (directory/"feedback.json").exists():
        return read(directory/"feedback.json")
    directory.mkdir(parents=True, exist_ok=True)
    result = {"status": "not_executed", "gold_used": False, "probe": probe}
    if response.get("tests"):
        try:
            files, names = materialize(case, response)
            if len(names) > 2:
                raise ValueError("at_most_two_named_tests_per_target")
            h = previous.harness(case, list(files))
            if probe and case["language"] == "go":
                h["command"] = h["command"].replace("go test ", "go test -v ", 1)
            if probe and case["language"] == "python":
                h["command"] = h["command"].replace(" -m pytest ", " -m pytest -s ", 1)
            files.update(h.get("files", {}))
            artifact = directory/"artifact"
            if not artifact.exists():
                freeze_artifact(artifact, case["id"], files, h["command"], h["report_format"], h["report_path"], timeout=300,
                                metadata={"source": "unmodified_model_code", "generated_test_names": names, "probe": probe})
            runpath = directory/"candidate/result.json"
            run = read(runpath) if runpath.exists() else run_artifact(artifact, "candidate", directory/"candidate", registry=[case])
            logs = {name: excerpt((directory/"candidate"/name).read_text(errors="replace"), 16000)
                    for name in ["stdout.txt", "stderr.txt", "go.jsonl"] if (directory/"candidate"/name).exists()}
            result.update(status=run["status"], tests=run["tests"], errors=run.get("errors", []), process=run.get("process", {}),
                          logs=logs, generated_test_names=names)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            result.update(status="execution_setup_error", error=str(exc)[:1000], error_type=type(exc).__name__)
    write_json(directory/"feedback.json", result)
    return result
