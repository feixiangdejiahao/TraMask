"""Resolve observed shell actions and submission boundaries without execution.

A submission marker is useful provenance, not a prerequisite for comparing a
complete replay against the collected model.patch. Unexecuted calls are omitted
only when their mapped observation explicitly says so. No command is split,
rewritten, or truncated at the first marker. Agent messages and reasoning are
never copied into actions or boundary records.
"""
from __future__ import annotations

import hashlib
import json
import shlex


MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
NOT_EXECUTED = "action was not executed"


def _digest(value):
    raw = value.encode() if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _marker(command):
    if MARKER not in command:
        return None
    # A heredoc can contain source text resembling a shell marker. Keep it as
    # text-only provenance rather than claiming a shell-command boundary.
    if "<<" in command:
        return "marker_text_in_heredoc_or_ambiguous_shell"
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return "marker_text_in_unparsed_shell"
    separators = {"&&", "||", ";", "\n", "|", "&"}
    if tokens == ["echo", MARKER]:
        return "standalone_echo"
    for index, token in enumerate(tokens[:-1]):
        if (token == "echo" and tokens[index + 1] == MARKER
                and (index == 0 or tokens[index - 1] in separators)
                and (index + 2 == len(tokens) or tokens[index + 2] in separators)):
            return "compound_echo_preserve_entire_command"
    return "marker_text_without_unambiguous_echo"


def _parsed_observation(result):
    if not isinstance(result, dict) or "content" not in result:
        raise ValueError("mapped_observation_requires_content")
    content = result["content"]
    try:
        value = json.loads(content) if isinstance(content, str) else content
    except ValueError as error:
        raise ValueError("observation_is_not_structured_shell_result") from error
    if not isinstance(value, dict) or type(value.get("returncode")) is not int:
        raise ValueError("observation_requires_integer_returncode")
    exception = value.get("exception_info", "")
    if not isinstance(exception, str):
        raise ValueError("invalid_observation_exception_info")
    unexecuted = exception.strip().lower() == NOT_EXECUTED
    if unexecuted:
        if value["returncode"] != -1 or value.get("output") != "":
            raise ValueError("contradictory_unexecuted_observation")
        return value, "explicit_not_executed", False
    if isinstance(value.get("output"), str):
        output_form = "full_recorded_output"
    elif (isinstance(value.get("output_head"), str) and isinstance(value.get("output_tail"), str)
          and type(value.get("elided_chars")) is int and value["elided_chars"] >= 0):
        output_form = "explicitly_elided_output; do_not_synthesize_missing_bytes"
    else:
        raise ValueError("observation_output_or_explicit_elision_required")
    if value["returncode"] == -1 and not any(word in exception.lower() for word in ("timed out", "timeout", "signal", "killed")):
        raise ValueError("negative_one_result_has_unresolved_execution_state")
    return value, output_form, True


def _mapped_results(tool_calls, results):
    if not isinstance(results, list) or len(results) != len(tool_calls):
        raise ValueError("incomplete_call_observation_mapping")
    ids = [call.get("tool_call_id") for call in tool_calls]
    if any(value is not None for value in ids):
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("invalid_or_duplicate_tool_call_ids")
    result_ids = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("invalid_observation_result")
        first, second = result.get("tool_call_id"), result.get("call_id")
        if first is not None and second is not None and first != second:
            raise ValueError("conflicting_observation_call_ids")
        result_ids.append(first if first is not None else second)
    if any(value is not None for value in result_ids):
        if (any(not isinstance(value, str) or not value for value in result_ids)
                or len(set(result_ids)) != len(result_ids) or set(result_ids) != set(ids)):
            raise ValueError("ambiguous_observation_id_mapping")
        lookup = {value: (index, results[index]) for index, value in enumerate(result_ids)}
        return [(lookup[value][1], "explicit_tool_call_id", lookup[value][0]) for value in ids]
    return [(result, "ordered_ATIF_result_list_equal_cardinality", index) for index, result in enumerate(results)]


def resolve_submission_actions(document):
    """Return (observed_actions, boundary_receipt), without I/O or execution.

    EOF-only boundaries are admitted as weaker provenance, subject to later
    independent submitted HEAD/worktree/index validation against model.patch.
    Unknown tools, absent results, ambiguous mappings, or unresolved execution
    status fail closed. A final tool call lacking a result is never invented as
    executed or silently treated as an unexecuted submission marker.
    """
    if not isinstance(document, dict) or not isinstance(document.get("steps"), list):
        raise ValueError("trajectory_requires_steps")
    actions, excluded, markers, projection, mappings, elided = [], [], [], [], [], []
    seen_ids, seen_tool_ids = set(), set()
    for ordinal, step in enumerate(document["steps"]):
        if not isinstance(step, dict):
            raise ValueError("invalid_trajectory_step")
        tool_calls = step.get("tool_calls") or []
        observation = step.get("observation") or {}
        if not isinstance(tool_calls, list) or not isinstance(observation, dict):
            raise ValueError("invalid_tool_calls_or_observation")
        results = observation.get("results") or []
        mapped = _mapped_results(tool_calls, results)
        for index, (call, (result, mapping, result_index)) in enumerate(zip(tool_calls, mapped)):
            if not isinstance(call, dict) or call.get("function_name") != "bash":
                raise ValueError("unsupported_trajectory_tool")
            arguments = call.get("arguments")
            try:
                arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            except ValueError as error:
                raise ValueError("invalid_shell_arguments_json") from error
            if (not isinstance(arguments, dict) or not isinstance(arguments.get("command"), str)
                    or not arguments["command"] or "\0" in arguments["command"]):
                raise ValueError("shell_action_requires_exact_command")
            command = arguments["command"]
            identity = f"s{step.get('step_id', ordinal)}_c{index}"
            if identity in seen_ids:
                raise ValueError("duplicate_action_identity")
            seen_ids.add(identity)
            tool_id = call.get("tool_call_id")
            if tool_id is not None:
                if tool_id in seen_tool_ids:
                    raise ValueError("duplicate_tool_call_id_across_steps")
                seen_tool_ids.add(tool_id)
            expected, output_form, executed = _parsed_observation(result)
            shape = _marker(command)
            base = {"id": identity, "step_id": step.get("step_id", ordinal), "ordinal": ordinal,
                    "call_index": index, "function": "bash", "command": command, "expected": expected,
                    "observation_mapping_unambiguous": True,
                    "observation_mapping": {"method": mapping, "result_index": result_index, "tool_call_id": tool_id},
                    "command_sha256": _digest(command), "observation_sha256": _digest(expected), "output_form": output_form}
            projection.append({**base, "recorded_executed": executed})
            mappings.append({"id": identity, "method": mapping, "recorded_executed": executed})
            if executed:
                actions.append(base)
                if "elided" in output_form:
                    elided.append(identity)
            else:
                excluded.append({"id": identity, "command": command, "command_sha256": base["command_sha256"],
                                 "observation_sha256": base["observation_sha256"], "expected": expected,
                                 "reason": "explicit_mapped_observation_says_action_was_not_executed; no prefix or suffix executed"})
            if shape:
                markers.append({"id": identity, "shape": shape, "recorded_executed": executed,
                                "command_sha256": base["command_sha256"], "observation_sha256": base["observation_sha256"]})
    if not actions:
        raise ValueError("no_observed_executed_shell_actions")
    actual_markers = [row for row in markers if row["shape"] in {"standalone_echo", "compound_echo_preserve_entire_command"}]
    last_requested_id = projection[-1]["id"]
    terminal_marker = next((row for row in actual_markers if row["id"] == last_requested_id), None)
    if len(actual_markers) > 1:
        kind = "multiple_markers_full_observed_trajectory"
        strength = "all_observed_actions_retained; no_early_marker_cutoff"
    elif terminal_marker:
        kind = "explicit_terminal_marker_executed" if terminal_marker["recorded_executed"] else "explicit_unexecuted_submission_request"
        strength = "explicit_submission_request_with_complete_observation_mapping"
    elif actual_markers:
        kind, strength = "marker_followed_by_actions_full_trajectory", "EOF_after_last_observed_action; earlier_marker_is_not_cutoff"
    else:
        kind, strength = "EOF_after_last_observed_action", "weaker_than_explicit_submission_marker"
    receipt = {"version": "observed-submission-boundary.v1", "kind": kind, "boundary_strength": strength,
        "raw_tool_call_count": len(projection), "executed_action_count": len(actions),
        "last_executed_action_id": actions[-1]["id"], "last_requested_action_id": last_requested_id,
        "marker_occurrences": markers, "unambiguous_echo_marker_count": len(actual_markers),
        "explicitly_unexecuted_calls": excluded, "output_elision_action_ids": elided,
        "observation_mappings": mappings, "mapping_complete": True,
        "commands_rewritten": False, "compound_commands_split": False,
        "all_recorded_executed_actions_retained": True,
        "public_action_projection_sha256": _digest(projection), "executed_actions_sha256": _digest(actions),
        "can_attempt_terminal_state_validation": True, "submitted_state_verified": False,
        "required_acceptance": "Replay all returned actions, freeze filesystem, then independently compare submitted HEAD, literal worktree and index with base plus collected model.patch. Boundary resolution alone is not state validation.",
        "absent_marker_implies_unreproducible_state": False,
        "excluded_private_fields": ["agent message", "reasoning_content", "model reasoning", "scientific labels"]}
    return actions, receipt
