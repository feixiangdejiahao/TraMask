"""Pure synthetic trajectory fixtures; no filesystem reads or execution."""
from tramask_rerun.validation_inventory import build_validation_inventory


def calls(*commands):
    return [{"id": f"call-{i}", "command": command, "function": "bash", "expected": {"returncode": 0}}
            for i, command in enumerate(commands)]


def patch(*paths):
    return "\n".join(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new" for path in paths)


def test_all_patch_authored_pytest_and_go_tests_are_inventory_candidates():
    source = patch("tests/test_a.py", "tests/test_b.py", "pkg/value_test.go", "src/value.go")
    terminal = {"/app/tests/test_a.py": "assert True", "/app/tests/test_b.py": "assert 1", "/app/pkg/value_test.go": "package pkg"}
    result = build_validation_inventory(calls("pytest tests", "go test ./... -run TestValue"), source, terminal)
    assert result["all_authored_test_paths"] == sorted(terminal)
    assert len(result["invocations"]) == 2
    assert result["invocations"][0]["test_paths"] == ["/app/tests/test_a.py", "/app/tests/test_b.py"]
    assert all(row["needs_manual_command_review"] for row in result["invocations"])
    assert result["invocations"][1]["binding"] == "suite_membership_candidates_collection_unverified"
    assert result["invocations"][1]["test_paths"] == ["/app/pkg/value_test.go"]


def test_temporary_script_created_executed_then_deleted_keeps_historical_only():
    command = "cat >/tmp/check.py <<'PY'\nassert 2 + 2 == 4\nPY\npython /tmp/check.py"
    result = build_validation_inventory(calls(command, "rm /tmp/check.py"), "", {"files": [], "errors": []})
    assert result["all_authored_test_paths"] == ["/tmp/check.py"]
    assert result["terminal_authored_test_paths"] == []
    assert result["historical_only_test_paths"] == ["/tmp/check.py"]
    test = result["tests"][0]
    assert test["historical_text"] == "assert 2 + 2 == 4\n"
    assert test["terminal_text"] is None and test["execution_call_ids"] == ["call-0"]
    assert result["invocations"][0]["last_execution"]["exact_test_only_command_suffix"] == "python /tmp/check.py"
    assert not result["historical_test_overlay_allowed"]


def test_inline_python_node_and_go_bodies_not_misparsed_as_shell_commands():
    commands = ["python - <<'PY'\nassert 'pytest fake.py' != ''\nPY\n",
                "node <<'JS'\nconsole.assert(1 === 1);\nJS\n",
                "go run /dev/stdin <<'GO'\npackage main\nfunc main() { /* test */ }\nGO\n"]
    result = build_validation_inventory(calls(*commands), "", {})
    assert len(result["inline_invocation_ids"]) == 3
    assert len(result["invocations"]) == 3
    assert not result["all_authored_test_paths"]
    for command, row in zip(commands, result["invocations"]):
        execution = row["last_execution"]
        assert command[execution["suffix_offset"]:] == execution["exact_test_only_command_suffix"]
        assert execution["exact_test_only_command_suffix"] == command
    assert not any(row["kind"] == "pytest" for row in result["invocations"])


def test_node_tsx_and_python_module_invocations_keep_exact_suffixes_and_cwd():
    source = patch("test/check.test.ts", "tests/test_a.py")
    commands = ["cd /app && npx tsx test/check.test.ts", "python -m pytest tests/test_a.py::test_one -q",
                "node --test test/check.test.ts"]
    terminal = {"/app/test/check.test.ts": "test('x',()=>{})", "/app/tests/test_a.py": "def test_one(): pass"}
    result = build_validation_inventory(calls(*commands), source, terminal)
    assert [row["kind"] for row in result["invocations"]] == ["tsx_script", "pytest", "node_test"]
    assert result["invocations"][0]["last_execution"]["exact_test_only_command_suffix"] == "npx tsx test/check.test.ts"
    assert result["invocations"][0]["last_execution"]["working_directory"] == "/app"
    assert result["all_authored_test_paths"] == sorted(terminal)


def test_production_write_prefix_is_flagged_without_losing_exact_test_suffix():
    command = "sed -i 's/before/after/' src/core.py && pytest tests/test_a.py"
    result = build_validation_inventory(calls(command), patch("tests/test_a.py"), {"/app/tests/test_a.py": "assert True"})
    row = result["invocations"][0]["last_execution"]
    assert row["exact_test_only_command_suffix"] == "pytest tests/test_a.py"
    assert row["production_write_paths_in_action"] == ["/app/src/core.py"]
    assert "mixed_action_contains_production_writes" in row["review_reasons"]
    assert row["needs_manual_command_review"] and not row["automatic_execution_allowed"]


def test_production_write_after_test_has_no_fabricated_test_only_suffix():
    command = "pytest tests/test_a.py && sed -i 's/x/y/' src/core.py"
    result = build_validation_inventory(calls(command), patch("tests/test_a.py"), {"/app/tests/test_a.py": "assert True"})
    row = result["invocations"][0]["last_execution"]
    assert row["exact_test_only_command_suffix"] is None
    assert row["production_write_paths_in_action"] == ["/app/src/core.py"]
    assert row["command_segment"] == "pytest tests/test_a.py"


def test_duplicate_invocations_retain_all_calls_and_last_executed_version():
    a = "cat > /tmp/check.py <<'PY'\nassert 1\nPY\npython /tmp/check.py"
    b = "cat > /tmp/check.py <<'PY'\nassert 2\nPY\npython /tmp/check.py"
    final = "assert 3\n"
    result = build_validation_inventory(calls(a, b, "cat > /tmp/check.py <<'PY'\nassert 3\nPY\n"), "", {"/tmp/check.py": final})
    assert len(result["invocations"]) == 1
    row = result["invocations"][0]
    assert row["execution_call_ids"] == ["call-0", "call-1"]
    assert row["last_execution"]["call_id"] == "call-1"
    test = result["tests"][0]
    assert test["historical_text"] == "assert 2\n" and test["terminal_text"] == final
    assert test["terminal_matches_last_known_executed_bytes"] is False


def test_unknown_custom_command_and_unsupported_tool_are_retained_for_review():
    trajectory = {"steps": [{"step_id": 7, "tool_calls": [
        {"function_name": "bash", "arguments": {"command": "custom-validate --quick"}},
        {"function_name": "editor", "arguments": {"path": "test.py"}}]}]}
    result = build_validation_inventory(trajectory, "", {})
    assert len(result["unknown_commands"]) == 2
    assert [row["call_id"] for row in result["unknown_commands"]] == ["s7_c0", "s7_c1"]
    assert all(row["needs_manual_command_review"] for row in result["unknown_commands"])


def test_authoring_python_heredoc_is_not_automatically_a_validation():
    command = "python - <<'PY'\nfrom pathlib import Path\nPath('/tmp/check.py').write_text('assert True\\n')\nPY\npython /tmp/check.py"
    result = build_validation_inventory(calls(command), "", {"/tmp/check.py": "assert True\n"})
    assert result["all_authored_test_paths"] == ["/tmp/check.py"]
    assert len(result["invocations"]) == 1
    assert result["tests"][0]["historical_text"] == "assert True\n"
    assert result["unknown_commands"][0]["reason"] == "inline_authoring_script_not_established_as_validation"


def test_pipeline_is_preserved_and_status_requires_review():
    command = "pytest tests/test_a.py 2>&1 | tail -20"
    result = build_validation_inventory(calls(command), patch("tests/test_a.py"), {"/app/tests/test_a.py": "assert True"})
    row = result["invocations"][0]["last_execution"]
    assert row["exact_test_only_command_suffix"] == command
    assert not row["production_write_paths_in_action"]
    assert "pipeline_shell_status_is_not_test_verdict" in row["review_reasons"]


def test_unexecuted_patch_tests_and_incomplete_terminal_inventory_remain_separate():
    result = build_validation_inventory(calls("pytest tests/test_a.py"), patch("tests/test_a.py", "other/test_b.py"),
                                        {"files": [], "errors": [{"path": "/app", "error": "partial"}]})
    assert result["patch_test_paths_without_matched_invocation"] == ["/app/other/test_b.py"]
    assert result["tests"][0]["terminal_availability"] == "unresolved_inventory_incomplete"
    assert not result["historical_only_test_paths"]


def test_spaces_in_patch_paths_and_quoted_script_paths_preserve_string_offsets():
    path = "tests/test with spaces.py"
    command = 'cd /app && pytest "tests/test with spaces.py"'
    result = build_validation_inventory(calls(command), patch(path), {"/app/" + path: "assert True"})
    assert result["all_authored_test_paths"] == ["/app/" + path]
    execution = result["invocations"][0]["last_execution"]
    assert command[execution["suffix_offset"]:] == execution["exact_test_only_command_suffix"]


def test_current_directory_suite_selector_and_stderr_redirect_do_not_add_fake_files():
    result = build_validation_inventory(calls("cd . && python -m pytest . 2>&1"), patch("tests/test_a.py"),
                                        {"/app/tests/test_a.py": "assert True"})
    assert result["all_authored_test_paths"] == ["/app/tests/test_a.py"]
    assert not result["invocations"][0]["last_execution"]["production_write_paths_in_action"]


def test_literal_python_open_creation_and_execution_are_bound():
    command = "python - <<'PY'\nwith open('/tmp/check.py', 'w') as f:\n    f.write('assert True\\n')\nPY\npython /tmp/check.py"
    result = build_validation_inventory(calls(command), "", {"/tmp/check.py": "assert True\n"})
    assert result["all_authored_test_paths"] == ["/tmp/check.py"]
    assert result["tests"][0]["historical_text"] == "assert True\n"
    assert result["tests"][0]["terminal_matches_last_known_executed_bytes"] is True


def test_multiple_python_writes_and_expanding_heredocs_do_not_claim_exact_historical_bytes():
    command = "python - <<'PY'\nwith open('/tmp/check.py', 'w') as f:\n    f.write('assert ')\n    f.write('True\\n')\nPY\npython /tmp/check.py"
    result = build_validation_inventory(calls(command), "", {"/tmp/check.py": "assert True\n"})
    assert result["tests"][0]["historical_text"] is None
    assert result["tests"][0]["terminal_matches_last_known_executed_bytes"] is None
    expanding = "cat >/tmp/check.py <<PY\nassert '$VALUE'\nPY\npython /tmp/check.py"
    result = build_validation_inventory(calls(expanding), "", {"/tmp/check.py": "assert 'value'\n"})
    assert result["tests"][0]["historical_text"] is None
