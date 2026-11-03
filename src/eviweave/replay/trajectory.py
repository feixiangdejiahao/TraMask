"""Parse ATIF shell actions once at the trajectory input boundary."""
import json
import shlex


MARKER = 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT'
TOKEN_LIMIT_NOTICE = (
    'Your previous response reached the output token limit (finish_reason=length) '
    'before you produced a tool call, so it was cut off. Respond more concisely '
    'and finish with exactly one bash tool call. If you need to think more, do so briefly.'
)
NO_TOOL_CALL_NOTICE = (
    'Tool call error:\n\n<error>\nNo tool calls found in the response. Every response MUST '
    'include at least one tool call.\n</error>\n\nHere is general guidance on how to submit '
    'correct toolcalls:\n\nEvery response needs to use the \'bash\' tool at least once to '
    'execute commands.\n\nCall the bash tool with your command as the argument:\n- Tool: '
    'bash\n- Arguments: {"command": "your_command_here"}\n\nIf you want to end the task, '
    'please issue the following command: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`\n'
    'without any other command.'
)
KNOWN_HARNESS_NOTICES = {TOKEN_LIMIT_NOTICE: 'model_output_token_limit',
                         NO_TOOL_CALL_NOTICE: 'model_response_missing_tool_call'}


def marker_shape(command):
    if MARKER not in command or '<<' in command:
        return None
    tokens = shlex.shlex(command, posix=True, punctuation_chars=';&|\n')
    tokens.whitespace = ' \t\r'
    tokens.whitespace_split = True
    tokens = list(tokens)
    separators = {'&&', '||', ';', '\n', '|', '&'}
    for i in range(len(tokens) - 1):
        if (tokens[i:i + 2] == ['echo', MARKER] and (i == 0 or tokens[i - 1] in separators)
                and (i + 2 == len(tokens) or tokens[i + 2] in separators)):
            return 'standalone_echo' if len(tokens) == 2 else 'compound_echo_preserve_entire_command'


def resolve_submission_actions(document):
    actions, excluded, markers, elided, notices = [], [], [], [], []
    for ordinal, step in enumerate(document['steps']):
        calls = step.get('tool_calls') or []
        results = []
        for index, result in enumerate((step.get('observation') or {}).get('results') or []):
            content = result['content']
            if isinstance(content, str) and content in KNOWN_HARNESS_NOTICES:
                if result.get('tool_call_id', result.get('call_id')):
                    raise ValueError('harness_notice_must_not_claim_a_tool_call_id')
                notices.append({'step_id': step.get('step_id', ordinal), 'result_index': index,
                                'kind': KNOWN_HARNESS_NOTICES[content], 'content': content})
            else:
                results.append((index, result))
        if len(calls) != len(results):
            raise ValueError('incomplete_call_observation_mapping')
        ids = [r.get('tool_call_id', r.get('call_id')) for _, r in results]
        if any(ids):
            call_ids = [call['tool_call_id'] for call in calls]
            if len(set(ids)) != len(ids) or set(ids) != set(call_ids):
                raise ValueError('ambiguous_observation_id_mapping')
            by_id = dict(zip(ids, results))
            results = [by_id[i] for i in call_ids]
        for call_index, (call, (result_index, result)) in enumerate(zip(calls, results)):
            if call['function_name'] != 'bash':
                raise ValueError('unsupported_trajectory_tool:' + call['function_name'])
            arguments = call['arguments']
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            expected = result['content']
            if isinstance(expected, str):
                expected = json.loads(expected)
            command = arguments['command']
            identity = f"s{step.get('step_id', ordinal)}_c{call_index}"
            row = {'id': identity, 'step_id': step.get('step_id', ordinal), 'ordinal': ordinal,
                   'call_index': call_index, 'function': 'bash', 'command': command, 'expected': expected,
                   'observation_mapping': {'result_index': result_index,
                                           'tool_call_id': call.get('tool_call_id'),
                                           'method': 'explicit_tool_call_id' if any(ids) else 'ordered_ATIF_results'}}
            exception = expected.get('exception_info', '').lower()
            executed = exception.strip() != 'action was not executed'
            if not executed and (expected['returncode'] != -1 or expected['output']):
                raise ValueError('contradictory_unexecuted_observation')
            if executed and expected['returncode'] == -1 and not any(
                    word in exception for word in ('timeout', 'timed out', 'signal', 'killed')):
                raise ValueError('unresolved_execution_state:' + identity)
            (actions if executed else excluded).append(row)
            if 'elided_chars' in expected:
                elided.append(identity)
            shape = marker_shape(command)
            if shape:
                markers.append({'id': identity, 'shape': shape, 'recorded_executed': executed})
            last_requested = identity
    last_marker = next((m for m in markers if m['id'] == last_requested), None)
    if len(markers) > 1:
        kind = 'multiple_markers_full_observed_trajectory'
    elif last_marker:
        kind = 'explicit_terminal_marker_executed' if last_marker['recorded_executed'] else 'explicit_unexecuted_submission_request'
    else:
        kind = 'marker_followed_by_actions_full_trajectory' if markers else 'EOF_after_last_observed_action'
    return actions, {'kind': kind, 'raw_tool_call_count': len(actions) + len(excluded),
                     'executed_action_count': len(actions),
                     'last_executed_action_id': actions[-1]['id'], 'last_requested_action_id': last_requested,
                     'marker_occurrences': markers, 'unambiguous_echo_marker_count': len(markers),
                     'explicitly_unexecuted_calls': excluded, 'output_elision_action_ids': elided,
                     'harness_notices': notices, 'mapping_complete': True,
                     'commands_rewritten': False, 'compound_commands_split': False,
                     'all_recorded_executed_actions_retained': True,
                     'boundary_strength': 'explicit_submission_marker' if last_marker else 'weaker_than_explicit_submission_marker',
                     'can_attempt_terminal_state_validation': True, 'submitted_state_verified': False,
                     'absent_marker_implies_unreproducible_state': False}
