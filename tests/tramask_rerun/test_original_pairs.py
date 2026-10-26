import json

import pytest

from tramask_rerun import original_pairs


def make_plan(tmp_path, monkeypatch):
    directory = tmp_path / "runs/X"
    (directory / "reference_canonical_v01").mkdir(parents=True)
    fixed = {"original_command": "python test.py", "alternative": {"edits": [{"path": "app/program.py", "old": "x = 1", "new": "x = 2"}]}}
    (directory / "reference_canonical_v01/fixed_counterfactual.json").write_text(json.dumps(fixed))
    (directory / "selection.json").write_text(json.dumps({"command": "python test.py", "working_directory": "/app"}))
    packet = {"final_sources": {"app/program.py": "x = 1\n"}, "selected_test": {"files": {"app/test.py": "assert True\n"}}}
    monkeypatch.setattr(original_pairs, "public_packet", lambda *args: packet)
    case = {"id": "X", "checkpoint": {"image_id": "sha256:" + "a" * 64, "head": "b" * 40}, "test_timeout_seconds": 60, "resources": {}}
    plan = original_pairs.prepare(case, {"approved_for_control_execution": True, "effective_command": "python test.py"}, tmp_path)
    return plan, directory


def test_six_clean_controls_bind_Q_and_keep_original_tests(tmp_path, monkeypatch):
    plan, directory = make_plan(tmp_path, monkeypatch)
    assert plan["variants"]["p_original"] == {}
    assert set(plan["variants"]["q_original"]) == {"/app/program.py"}
    assert plan["variants"]["q_original"]["/app/program.py"]["content"] == "x = 2\n"
    calls = []

    def execute(checkpoint, destination, command, timeout, **kwargs):
        assert command == "python test.py"
        assert checkpoint == plan["checkpoint"]
        assert not destination.exists()
        destination.mkdir(parents=True)
        result = {"status": "executed", "execution": {"returncode": 1 if kwargs["files"] else 0}}
        (destination / "result.json").write_text(json.dumps(result))
        calls.append(destination)
        return result

    monkeypatch.setattr(original_pairs, "execute_variant", execute)
    result = original_pairs.execute("X", tmp_path)
    assert len(set(calls)) == 6
    assert result["scientific_label"] is None
    assert original_pairs.execute("X", tmp_path) == result
    assert len(calls) == 6


def test_partial_execution_not_silently_replayed(tmp_path, monkeypatch):
    _, directory = make_plan(tmp_path, monkeypatch)
    (directory / "original_pair_controls_v01/repeat_01/p_original").mkdir(parents=True)
    with pytest.raises(FileExistsError, match="Partial control"):
        original_pairs.execute("X", tmp_path)
