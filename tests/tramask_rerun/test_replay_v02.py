import json

import pytest

from tramask_rerun import replay_v02
from eviweave.replay import core


@pytest.mark.parametrize("terminal", [False, True])
def test_plan_retains_observed_actions_and_whole_unexecuted_boundary(tmp_path, monkeypatch, terminal):
    source = tmp_path / "input"
    source.mkdir()
    commands = [("printf original", {"returncode": 0, "output": "original"})]
    if terminal:
        commands.append(("cd /app && echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
                         {"returncode": -1, "output": "", "exception_info": "action was not executed"}))
    document = {"steps": [{"step_id": i, "tool_calls": [{"function_name": "bash", "arguments": {"command": command}}],
        "observation": {"results": [{"content": json.dumps(result)}]}} for i, (command, result) in enumerate(commands)]}
    (source / "trajectory.json").write_text(json.dumps(document))
    (source / "task.toml").write_text('[metadata]\nbase_commit_hash="' + "a" * 40 + '"\n[environment]\ndocker_image="synthetic:image"\n')
    for name in ("instruction.md", "model.patch"):
        (source / name).write_text("synthetic")

    def stop_before_docker(*args, **kwargs):
        raise RuntimeError("synthetic stop after plan")

    monkeypatch.setattr(core, "open_container", stop_before_docker)
    out = tmp_path / "attempt"
    with pytest.raises(RuntimeError, match='synthetic stop after plan'):
        replay_v02.replay_case({"id": "synthetic", "image": "synthetic:image", "base_commit": "a" * 40}, source, out)
    plan = json.loads((out / "plan.json").read_text())
    assert plan["action_ids"] == ["s0_c0"]
    boundary = plan["boundary"]
    assert boundary["all_recorded_executed_actions_retained"] is True
    assert boundary["compound_commands_split"] is False
    assert boundary["kind"] == ("explicit_unexecuted_submission_request" if terminal else "EOF_after_last_observed_action")
    if terminal:
        assert boundary["explicitly_unexecuted_calls"][0]["command"] == commands[1][0]
    assert not (out / 'tests').exists()
    with pytest.raises(FileExistsError):
        replay_v02.replay_case({'id': 'synthetic', 'image': 'synthetic:image', 'base_commit': 'a' * 40},
                              source, out, collect_validation_tests=True)
