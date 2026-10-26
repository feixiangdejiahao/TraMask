"""Conservative replay-output qualification, separate from masking judgments.

No executions or file reads occur here. The caller supplies frozen execution
records and one unambiguously associated archived tool result. Source/version
restoration and assertion semantics still require independent review.
"""
from __future__ import annotations

import hashlib
import json
import re


VERSION = "tramask-fidelity-v1"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ELAPSED = r"[0-9]+(?:\.[0-9]+)?\s*(?:ms|s|seconds?)"
STATUS = r"passed|failed|skipped|errors?|warnings?|deselected|xfailed|xpassed"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _normalize(text: str) -> tuple[str, list[str]]:
    """Remove display formatting and narrowly identified runner timings only.

    Object addresses, arbitrary durations, paths, expected/actual values, test
    names, counts and statuses remain unchanged. Identity is a pilot target, so
    address differences are deliberately NOT dismissed as nondeterminism.
    """
    original = text
    text = text.replace("\r\n", "\n")
    rules = ["crlf"] if text != original else []
    cleaned = ANSI.sub("", text)
    if cleaned != text:
        rules.append("ansi_terminal_formatting")
    vitest_report = bool(re.search(r"^\s*Test Files\s+\d+\s+(?:passed|failed)", cleaned, re.M)
                         and re.search(r"^\s*Tests\s+\d+\s+(?:passed|failed)", cleaned, re.M))
    lines = []
    for line in cleaned.splitlines(keepends=True):
        before = line
        if re.match(r"^(?:=+\s*)?\d+\s+(?:" + STATUS + r")\b", line):
            line = re.sub(r"\bin\s+" + ELAPSED + r"(?=\s*(?:=+)?\s*$)", "in <ELAPSED>", line)
        if re.match(r"^\s*--- (?:PASS|FAIL|SKIP): \S+", line):
            line = re.sub(r"\(" + ELAPSED + r"\)(?=\s*$)", "(<ELAPSED>)", line)
        if re.match(r"^(?:ok\s+|FAIL\s+)\S+\s+", line):
            line = re.sub(ELAPSED + r"(?=\s*$)", "<ELAPSED>", line)
        if re.match(r"^Ran \d+ tests? in ", line):
            line = re.sub(r"(?<= in )" + ELAPSED, "<ELAPSED>", line)
        if re.match(r"^test result: (?:ok|FAILED)\.", line):
            line = re.sub(r"(?<=finished in )" + ELAPSED, "<ELAPSED>", line)
        # Vitest uses these dedicated runner metadata lines. Keep counts and
        # identities elsewhere, and do not normalize an arbitrary 'Time:' value.
        if vitest_report and re.match(r"^\s*Duration\s+" + ELAPSED, line):
            line = re.sub(ELAPSED, "<ELAPSED>", line)
        if vitest_report and re.match(r"^\s*Start at\s+\d{2}:\d{2}:\d{2}\s*$", line):
            line = re.sub(r"\d{2}:\d{2}:\d{2}", "<RUNNER_START_TIME>", line)
            rules.append("vitest_runner_start_wallclock")
        if line != before:
            rules.append("recognized_runner_elapsed_time")
        lines.append(line)
    return "".join(lines), sorted(set(rules))


def _escaped_variant(text: str) -> str | None:
    """Offer one explicit escape-layer hypothesis without altering raw evidence.

    Do not decode arbitrary backslashes or Unicode through ``unicode_escape``;
    that corrupts Unicode and can change literal test data. A mixed real/literal
    newline output remains ambiguous and is not decoded automatically.
    """
    if "\n" in text or "\\n" not in text:
        return None
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
               "\\": "\\", '"': '"', "'": "'"}
    def replace(match):
        token = match.group(1)
        if token.startswith(("x", "u")):
            return chr(int(token[1:], 16))
        return escapes[token]
    return re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[nrtbf\\\"'])", replace, text)


def test_evidence(text: str) -> dict:
    """Extract observed runner reports; never infer PASS from shell exit zero."""
    text, _ = _normalize(text)
    summaries, identities, assertion_lines, blockers = [], [], [], []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^(?:=+\s*)?\d+\s+(?:" + STATUS + r")\b", stripped):
            counts = re.findall(r"(\d+)\s+(" + STATUS + r")\b", stripped)
            summaries.append({"runner": "pytest_like", "counts": [[s, int(n)] for n, s in counts]})
        elif re.match(r"^(?:Tests|Test Files)\s+", stripped):
            summaries.append({"runner": "vitest", "text": stripped})
        elif re.match(r"^Ran \d+ tests? in ", stripped):
            summaries.append({"runner": "unittest", "tests": int(re.search(r"\d+", stripped)[0])})
        elif re.match(r"^test result: (?:ok|FAILED)\.", stripped):
            summaries.append({"runner": "rust", "text": stripped})
        go = re.match(r"^--- (PASS|FAIL|SKIP): (\S+)", stripped)
        py = re.match(r"^(\S+\.py::\S+)\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b", stripped)
        failure = re.match(r"^(FAILED|ERROR)\s+(\S+\.py(?:::\S+)?)", stripped)
        rust = re.match(r"^test (\S+) \.\.\. (ok|FAILED|ignored)\s*$", stripped)
        package = re.match(r"^(ok|FAIL|\?)\s+(\S+)\s+(.+)$", stripped)
        if go:
            identities.append({"runner": "go", "id": go[2], "status": go[1]})
        elif py:
            identities.append({"runner": "pytest", "id": py[1], "status": py[2]})
        elif failure:
            identities.append({"runner": "pytest", "id": failure[2], "status": failure[1]})
        elif rust:
            identities.append({"runner": "rust", "id": rust[1], "status": rust[2]})
        elif package:
            identities.append({"runner": "go_package", "id": package[2], "status": package[1],
                               "cached": "(cached)" in package[3],
                               "no_test_files": "[no test files]" in package[3]})
        if re.search(r"\bAssertionError\b|^E\s+assert\b|^Expected:|^Received:|^assert(?:ion)?\b", stripped):
            assertion_lines.append(stripped)
        if re.search(r"\bcommand not found\b|Cannot connect to the Docker daemon|No such container|"
                     r"Could not resolve host|Temporary failure in name resolution|"
                     r"No module named ['\"](?:pytest|unittest|vitest)['\"]|"
                     r"Interrupted: .*errors? during collection|collected 0 items", stripped):
            blockers.append(stripped)
    return {"summaries": summaries, "identities": identities, "assertion_lines": assertion_lines,
            "execution_blockers": blockers,
            "observed_test_evidence": bool(summaries or identities or assertion_lines),
            "limits": "Runner summaries and assertion messages are observed reports, not independently verified oracle correctness."}


def _archive(value):
    if isinstance(value, dict) and "content" in value and len(value) == 1:
        value = value["content"]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = {"output": value}
        value = parsed
    return value if isinstance(value, dict) else None


def _compare(execution: dict, archived_expected) -> dict:
    expected = _archive(archived_expected)
    stdout, stderr = str(execution.get("stdout", "")), str(execution.get("stderr", ""))
    combined = stdout + stderr
    actual_evidence = test_evidence(combined)
    result = {"classification": "insufficient_evidence", "needs_manual_review": True,
              "supports_output_fidelity": False, "reasons": [],
              "actual_returncode": execution.get("returncode"),
              "stdout_sha256": _digest(stdout), "stderr_sha256": _digest(stderr),
              "actual_test_evidence": actual_evidence,
              "shell_returncode_is_not_test_verdict": True,
              "possible_pipeline_status_masking": bool(re.search(r"\|\s*(?:head|tail|tee|sed|grep|cat)\b",
                                                                 execution.get("command", "")))}
    if execution.get("timed_out") or execution.get("transport_error") or execution.get("error"):
        result.update(classification="infrastructure", reasons=["replay_timeout_or_transport_error"])
        return result
    if expected is None:
        result["reasons"].append("missing_or_ambiguously_mapped_archived_observation")
        return result
    result["expected_returncode"] = expected.get("returncode")
    result["archive_sha256"] = _digest(json.dumps(expected, ensure_ascii=True, sort_keys=True))
    result["returncode_match"] = (execution.get("returncode") == expected.get("returncode")
                                 if expected.get("returncode") is not None else None)
    excerpt = any(k in expected for k in ("output_head", "output_tail", "elided_chars"))
    result["archive_completeness"] = "excerpt" if excerpt else "full" if "output" in expected else "unknown"
    if "output" not in expected and not excerpt:
        result["reasons"].append("archive_has_no_comparable_output")
        return result
    texts = [str(expected.get("output", ""))] if not excerpt else [
        str(expected.get("output_head", "")), str(expected.get("output_tail", ""))]
    alternatives = [(texts, False)]
    decoded = [_escaped_variant(text) for text in texts]
    if any(text is not None for text in decoded):
        alternatives.append(([decoded[i] if decoded[i] is not None else texts[i]
                              for i in range(len(texts))], True))
    actual_normalized, actual_rules = _normalize(combined)
    match = None
    for parts, escaped in alternatives:
        normalized_parts = [_normalize(part) for part in parts]
        if excerpt:
            exact = bool(any(parts)) and combined.startswith(parts[0]) and combined.endswith(parts[-1])
            normalized = bool(any(parts)) and actual_normalized.startswith(normalized_parts[0][0]) and actual_normalized.endswith(normalized_parts[-1][0])
        else:
            exact = combined == parts[0]
            normalized = actual_normalized == normalized_parts[0][0]
        if exact or normalized:
            match = {"output_relation": "raw_equal" if exact and not escaped else "normalized_equal",
                     "escape_layer_hypothesis": escaped,
                     "normalization_rules": sorted(set(actual_rules + [r for _, rs in normalized_parts for r in rs])),
                     "archive_test_evidence": test_evidence("\n".join(parts))}
            break
    if match is not None:
        result.update(match)
    else:
        result.update(output_relation="different", escape_layer_hypothesis=False,
                      archive_test_evidence=test_evidence("\n".join(alternatives[-1][0])))
    if expected.get("exception_info"):
        result["reasons"].append("archived_tool_reported_exception_info")
    if stdout and stderr:
        result["reasons"].append("archived_combined_stream_order_cannot_be_reconstructed")
    if match and match["escape_layer_hypothesis"]:
        result["reasons"].append("one_literal_escape_layer_inferred_from_matching_output")
    if not actual_evidence["observed_test_evidence"]:
        result["reasons"].append("no_machine_recognized_test_count_identity_or_assertion_report")
    if actual_evidence["execution_blockers"]:
        result.update(classification="infrastructure")
        result["reasons"].append("output_reports_blocked_execution_or_collection")
    elif result["returncode_match"] is False or match is None:
        result.update(classification="mismatch")
        result["reasons"].append("returncode_or_output_differs")
    elif excerpt:
        result["reasons"].append("matching_excerpts_cannot_establish_complete_output_fidelity")
    elif result["returncode_match"] is None:
        result["reasons"].append("archived_returncode_missing")
    else:
        result.update(classification="exact" if result["output_relation"] == "raw_equal" else "normalized_semantic_match",
                      supports_output_fidelity=True)
        result["needs_manual_review"] = bool(result["reasons"])
    return result


def evaluate_replay(summary: dict, archived_expected) -> dict:
    """Qualify output fidelity from a run record or full replay summary.

    The final-patch run is described separately: a difference against that run
    must never be mistaken for a failure to restore the historical program.
    ``needs_manual_review`` concerns output qualification only; source restoration
    and any masking judgment remain independent required checks.
    """
    original = summary.get("original_command_execution", summary)
    comparison = _compare(original, archived_expected)
    result = {"version": VERSION, **comparison, "comparison": comparison,
              "source_restoration_verified_by_this_helper": False,
              "masking_or_correctness_verdict": None}
    if "historical_test_only" in summary:
        rerun = summary["historical_test_only"]
        evidence = test_evidence(str(rerun.get("stdout", "")) + str(rerun.get("stderr", "")))
        result["historical_test_only"] = {"returncode": rerun.get("returncode"), "evidence": evidence,
            "timed_out": bool(rerun.get("timed_out")), "transport_error": bool(rerun.get("transport_error")),
            "runner_evidence_matches_original": evidence == comparison["actual_test_evidence"],
            "scope": "Commands can differ by setup prefix; equal runner reports do not prove equal public state."}
        if rerun.get("timed_out") or rerun.get("transport_error") or evidence["execution_blockers"]:
            result["needs_manual_review"] = True
            result["reasons"] = [*result["reasons"], "historical_test_only_execution_blocked"]
    if "final_test_only" in summary:
        final = summary["final_test_only"]
        result["final_test_only"] = {"returncode": final.get("returncode"),
            "evidence": test_evidence(str(final.get("stdout", "")) + str(final.get("stderr", ""))),
            "scope": "Different implementation; excluded from historical fidelity comparison."}
    return result
