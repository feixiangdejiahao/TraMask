import json

import pytest

from augmentation.validation_evolution import (
    build_inputs, literal_test_edits, local_slice, materialize, serve_queries, validate,
)


def test_final_only_inputs_do_not_include_deleted_historical_tests(tmp_path):
    repo = tmp_path/"repo"
    (repo/"tests").mkdir(parents=True)
    (repo/"calc.py").write_text("def add(a, b):\n    return a+b\n")
    (repo/"tests/test_calc.py").write_text("def test_final():\n    assert add(1, 2) == 3\n")
    issue = tmp_path/"issue.md"; issue.write_text("Add two numbers.")
    patch = tmp_path/"patch"; patch.write_text("diff --git a/calc.py b/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n+def add(a, b): return a+b\n")
    trajectory = tmp_path/"trajectory.json"
    trajectory.write_text(json.dumps({"steps": [{"step_id": 3, "tool_calls": [{"arguments": {"command": "cat > /repo/tests/test_calc.py <<'PY'\ndef test_old():\n    assert add(0, 0) == 0\nPY"}}]}]}))
    base, evolution, history, events = build_inputs({"repository": str(repo), "language": "python", "issue": str(issue), "candidate_patch": str(patch), "trajectory": str(trajectory)})
    assert [t["name"] for t in base["validation_tests"]] == ["test_final"]
    assert [t["name"] for t in evolution["historical_tests"]] == ["test_old"]
    assert "test_old" not in json.dumps(base)
    assert history["timeline"][0]["step"] == 3


def test_edit_fragments_keep_old_and_new_assertions_without_execution():
    events = [{"step": 8, "command": "apply_patch <<'PATCH'\n*** Begin Patch\n*** Update File: tests/test_calc.py\n@@\n-    assert result == 3\n+    assert result == 4\n*** End Patch\nPATCH"}]
    row = literal_test_edits(events)[0]
    assert row["before"].strip() == "assert result == 3"
    assert row["after"].strip() == "assert result == 4"
    assert row["complete_test"] is False


def test_versions_arm_cannot_obtain_execution_history(tmp_path):
    result = serve_queries({"repository": str(tmp_path), "language": "python"}, {"validation_tests": []},
                           {"historical_tests": [], "edit_fragments": []}, [],
                           [{"kind": "history", "step": 3}], "B_versions")
    assert result[0]["error"] == "history_unavailable_in_this_arm"


def test_slice_keeps_raw_argument_and_normalized_local_distinct(tmp_path):
    (tmp_path/"a.py").write_text("def caller(options):\n    mode = options.get('mode', 'put')\n    normalized = mode.lower()\n    return callee(options, normalized)\n")
    result = local_slice({"repository": str(tmp_path)}, {"path": "a.py", "line": 4})
    assert result["parameters"] == ["options"]
    assert {d["written"] for d in result["local_definitions"]} == {"mode", "normalized"}
    assert result["focus"]["code"] == "callee(options, normalized)"
    assert "No proven dynamic alias" in result["limit"]


def test_python_test_bytes_preserved_and_production_write_rejected(tmp_path):
    case = {"repository": str(tmp_path), "language": "python"}
    code = "def test_CCPilot():\n    assert 1 == 2"
    files, names = materialize(case, {"tests": [{"path": "tests/test_new.py", "mode": "new", "code": code}]})
    assert files == {"tests/test_new.py": code+"\n"}
    assert names == ["test_CCPilot"]
    with pytest.raises(ValueError):
        materialize(case, {"tests": [{"path": "source.py", "mode": "new", "code": code}]})


def test_multiple_targets_are_distinct_and_detection_can_survive_no_code():
    row = {"id": "h1", "decision": "gap", "target": {"combination": "x"}, "tests": []}
    assert validate({"targets": [row]}, 3)["targets"][0]["generation_missing"] is True
    with pytest.raises(ValueError, match="target_ids"):
        validate({"targets": [row, row]}, 3)


def test_unambiguous_transport_repair_preserves_code_bytes():
    tests = [{"path": "test_new.py", "mode": "new", "code": "def test_CCPilot():\n    assert False"}]
    v = validate({"targets": [{"id": "h1", "decision": "gap", "target": {}}], "tests": tests}, 3)
    assert v["targets"][0]["tests"] == tests
    assert v["transport_normalization"] == "single_target_top_level_tests"
    with pytest.raises(ValueError, match="test_list"):
        validate({"targets": [{"id": "h1", "decision": "gap"}, {"id": "h2", "decision": "gap"}], "tests": tests}, 3)
