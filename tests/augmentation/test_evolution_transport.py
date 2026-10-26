import pytest

from augmentation.evolution_transport import parse_completion, validate


def test_append_control_and_target_survive_in_one_file():
    a = 'def test_CCPilot_target():\n    assert False\n'
    b = 'def test_CCPilot_control():\n    assert True\n'
    raw = {"targets": [{"id": "h1", "decision": "gap", "tests": [
        {"path": "tests/test_x.py", "mode": "append", "code": a},
        {"path": "tests/test_x.py", "mode": "append", "code": b}]}]}
    value = validate(raw, 3)
    assert value["targets"][0]["tests"][0]["code"] == a+"\n\n"+b
    assert len(raw["targets"][0]["tests"]) == 2
    assert value["append_transport_normalization"]


def test_two_actual_files_still_exceed_frozen_file_cap():
    with pytest.raises(ValueError, match="one_test_file"):
        validate({"targets": [{"id": "h1", "decision": "gap", "tests": [
            {"path": "tests/test_a.py", "mode": "append", "code": "a"},
            {"path": "tests/test_b.py", "mode": "append", "code": "b"}]}]}, 3)


def test_distinct_json_objects_merge_without_choosing_between_answers():
    result = parse_completion('{"hypotheses":[]}\n {"queries":[],"notes":"done"}')
    assert result["hypotheses"] == result["queries"] == []
    with pytest.raises(ValueError, match="conflicting"):
        parse_completion('{"hypotheses":[]} {"hypotheses":[{"id":"h1"}]}')


def test_duplicate_new_files_are_not_rewritten_or_selected():
    with pytest.raises(ValueError, match="one_test_file"):
        validate({"targets": [{"id": "h1", "decision": "gap", "tests": [
            {"path": "test_x.py", "mode": "new", "code": "a"},
            {"path": "test_x.py", "mode": "new", "code": "b"}]}]}, 3)
