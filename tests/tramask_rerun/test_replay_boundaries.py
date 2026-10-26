"""Pure boundary resolution checks; no real trajectories or Docker calls."""
import copy
import json

import pytest

from tramask_rerun.replay_boundaries import MARKER, resolve_submission_actions


def step(number, commands, results=None, *, result_ids=False):
    calls = [{"function_name": "bash", "tool_call_id": f"tool-{number}-{index}", "arguments": {"command": command}}
             for index, command in enumerate(commands)]
    if results is None:
        results = [{"returncode": 0, "output": "observed"} for _ in commands]
    observations = [{"content": json.dumps(value), **({"tool_call_id": calls[index]["tool_call_id"]} if result_ids else {})}
                    for index, value in enumerate(results)]
    return {"step_id": number, "tool_calls": calls, "observation": {"results": observations},
            "message": "PRIVATE_MESSAGE", "reasoning_content": "PRIVATE_REASONING"}


def not_executed():
    return {"returncode": -1, "output": "", "exception_info": "action was not executed"}


def test_hf001_shape_excludes_whole_unexecuted_compound_marker_not_its_cd_prefix():
    document = {"steps": [step(136, ["cd /app && git status --short"]),
                           step(137, ["cd /app && echo " + MARKER], [not_executed()])]}
    actions, receipt = resolve_submission_actions(document)
    assert [row["id"] for row in actions] == ["s136_c0"]
    assert receipt["kind"] == "explicit_unexecuted_submission_request"
    assert receipt["marker_occurrences"][0]["shape"] == "compound_echo_preserve_entire_command"
    assert receipt["explicitly_unexecuted_calls"][0]["command"] == "cd /app && echo " + MARKER
    assert not receipt["compound_commands_split"] and not receipt["commands_rewritten"]
    assert "PRIVATE" not in json.dumps([actions, receipt])


def test_executed_compound_marker_keeps_all_commands_and_bytes():
    command = "touch /tmp/before && echo " + MARKER + "; touch /tmp/after"
    actions, receipt = resolve_submission_actions({"steps": [step(1, [command])]})
    assert actions[0]["command"] == command
    assert receipt["kind"] == "explicit_terminal_marker_executed"
    assert receipt["executed_action_count"] == 1


def test_eof_without_marker_is_weaker_but_can_be_patch_validated():
    actions, receipt = resolve_submission_actions({"steps": [step(1, ["git add . && git commit -m final"])]})
    assert len(actions) == 1 and receipt["kind"] == "EOF_after_last_observed_action"
    assert receipt["boundary_strength"] == "weaker_than_explicit_submission_marker"
    assert receipt["can_attempt_terminal_state_validation"] and not receipt["submitted_state_verified"]
    assert not receipt["absent_marker_implies_unreproducible_state"]


def test_multiple_markers_never_discard_later_actual_state_changes():
    commands = ["echo " + MARKER, "touch /app/changed", "echo " + MARKER]
    actions, receipt = resolve_submission_actions({"steps": [step(1, commands)]})
    assert [row["command"] for row in actions] == commands
    assert receipt["kind"] == "multiple_markers_full_observed_trajectory"
    assert receipt["last_executed_action_id"] == "s1_c2"


def test_earlier_marker_does_not_define_final_boundary():
    actions, receipt = resolve_submission_actions({"steps": [step(1, ["echo " + MARKER]), step(2, ["git commit -am actual-final"])]})
    assert len(actions) == 2 and receipt["kind"] == "marker_followed_by_actions_full_trajectory"


def test_missing_terminal_observation_is_not_assumed_executed_or_unexecuted():
    document = {"steps": [step(1, ["git status"]), step(2, ["echo " + MARKER], [])]}
    with pytest.raises(ValueError, match="incomplete_call_observation_mapping"):
        resolve_submission_actions(document)


def test_explicit_unexecuted_nonmarker_is_excluded_and_kept_in_receipt():
    actions, receipt = resolve_submission_actions({"steps": [step(1, ["touch /tmp/actual"]),
        step(2, ["rm /app/important"], [not_executed()])]})
    assert len(actions) == 1 and receipt["kind"] == "EOF_after_last_observed_action"
    assert receipt["explicitly_unexecuted_calls"][0]["id"] == "s2_c0"


def test_explicit_ids_resolve_reordered_results_and_partial_id_mapping_rejects():
    current = step(1, ["first", "second"], [{"returncode": 0, "output": "one"}, {"returncode": 1, "output": "two"}], result_ids=True)
    current["observation"]["results"].reverse()
    actions, _ = resolve_submission_actions({"steps": [current]})
    assert [row["expected"]["output"] for row in actions] == ["one", "two"]
    del current["observation"]["results"][0]["tool_call_id"]
    with pytest.raises(ValueError, match="ambiguous_observation_id_mapping"):
        resolve_submission_actions({"steps": [current]})


def test_truncated_output_does_not_mean_missing_execution_mapping():
    result = {"returncode": 0, "output_head": "begin", "output_tail": "end", "elided_chars": 100, "warning": "truncated"}
    actions, receipt = resolve_submission_actions({"steps": [step(1, ["cat huge-file"], [result])]})
    assert actions[0]["expected"] == result and "output" not in actions[0]["expected"]
    assert receipt["output_elision_action_ids"] == ["s1_c0"] and receipt["mapping_complete"]


def test_timeout_is_an_observed_attempt_but_unknown_negative_one_is_rejected():
    result = {"returncode": -1, "output": "partial", "exception_info": "Command timed out after 30 seconds"}
    actions, _ = resolve_submission_actions({"steps": [step(1, ["long test"], [result])]})
    assert len(actions) == 1
    result["exception_info"] = "unclear transport state"
    with pytest.raises(ValueError, match="unresolved_execution_state"):
        resolve_submission_actions({"steps": [step(1, ["long test"], [result])]})


def test_unknown_tools_and_contradictory_unexecuted_results_reject():
    current = step(1, ["write"])
    current["tool_calls"][0]["function_name"] = "editor"
    with pytest.raises(ValueError, match="unsupported_trajectory_tool"):
        resolve_submission_actions({"steps": [current]})
    bad = {**not_executed(), "output": "side effects occurred"}
    with pytest.raises(ValueError, match="contradictory_unexecuted"):
        resolve_submission_actions({"steps": [step(1, ["echo " + MARKER], [bad])]})


def test_marker_in_heredoc_source_text_does_not_create_submission_boundary():
    command = "cat > /tmp/source <<'EOF'\necho " + MARKER + "\nEOF"
    document = {"steps": [step(1, [command])]}
    before = copy.deepcopy(document)
    actions, receipt = resolve_submission_actions(document)
    assert document == before and actions[0]["command"] == command
    assert receipt["kind"] == "EOF_after_last_observed_action"
    assert receipt["unambiguous_echo_marker_count"] == 0
