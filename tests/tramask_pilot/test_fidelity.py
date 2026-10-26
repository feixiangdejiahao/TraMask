"""Synthetic output comparisons; no subjects or model providers are invoked."""
from tramask_pilot.fidelity import evaluate_replay, test_evidence as extract_evidence


def run(text, rc=0, **kwargs):
    return {"stdout": text, "stderr": "", "returncode": rc,
            "command": "pytest -q", "timed_out": False, "transport_error": False, **kwargs}


def test_exact_counts_and_ids_are_preserved_without_claiming_masking():
    text = "test_a.py::test_target PASSED\n1 passed in 0.1s\n"
    evidence = evaluate_replay(run(text), {"output": text, "returncode": 0})
    assert evidence["classification"] == "exact"
    assert evidence["supports_output_fidelity"] and not evidence["needs_manual_review"]
    assert evidence["actual_test_evidence"]["identities"][0]["id"] == "test_a.py::test_target"
    assert evidence["actual_test_evidence"]["summaries"][0]["counts"] == [["passed", 1]]
    assert not evidence["source_restoration_verified_by_this_helper"]
    assert evidence["masking_or_correctness_verdict"] is None


def test_double_escaped_newlines_and_ansi_are_explicit_inferred_decoding():
    archived = r"\u001b[32m1 passed in 0.24s\u001b[0m\n"
    evidence = evaluate_replay(run("1 passed in 0.98s\n"), {"output": archived, "returncode": 0})
    assert evidence["classification"] == "normalized_semantic_match"
    assert evidence["escape_layer_hypothesis"] and evidence["needs_manual_review"]
    assert "recognized_runner_elapsed_time" in evidence["normalization_rules"]


def test_elapsed_time_normalization_does_not_hide_values_addresses_or_paths():
    for expected, actual in [
        ("<object at 0xaaaa>\n1 passed in 0.1s\n", "<object at 0xbbbb>\n1 passed in 0.2s\n"),
        ("duration in 0.1s\n1 passed in 0.1s\n", "duration in 0.2s\n1 passed in 0.1s\n"),
        ("path=/tmp/one\n1 passed in 0.1s\n", "path=/tmp/two\n1 passed in 0.1s\n"),
    ]:
        assert evaluate_replay(run(actual), {"output": expected, "returncode": 0})["classification"] == "mismatch"


def test_same_exitcode_and_counts_do_not_hide_different_test_identity_or_assertion():
    old = "test_a.py::test_one PASSED\n1 passed in 0.1s\n"
    new = "test_a.py::test_two PASSED\n1 passed in 0.1s\n"
    assert evaluate_replay(run(new), {"output": old, "returncode": 0})["classification"] == "mismatch"
    assert evaluate_replay(run("assert actual == 8\n", 1),
                           {"output": "assert actual == 7\n", "returncode": 1})["classification"] == "mismatch"


def test_matching_excerpts_do_not_establish_full_fidelity():
    expected = {"output_head": "=== RUN   TestA\n", "output_tail": "PASS\n", "elided_chars": 200, "returncode": 0}
    result = evaluate_replay(run("=== RUN   TestA\nanything omitted\nPASS\n"), expected)
    assert result["classification"] == "insufficient_evidence"
    assert result["archive_completeness"] == "excerpt" and result["needs_manual_review"]
    assert not result["supports_output_fidelity"]


def test_piped_exit_zero_does_not_become_test_pass():
    text = "FAILED test_a.py::test_target - AssertionError\n1 failed in 0.2s\n"
    result = evaluate_replay(run(text, command="pytest -q 2>&1 | tail -20"), {"output": text, "returncode": 0})
    assert result["classification"] == "exact"
    assert result["possible_pipeline_status_masking"]
    assert result["actual_test_evidence"]["summaries"][0]["counts"] == [["failed", 1]]
    assert result["shell_returncode_is_not_test_verdict"]


def test_reproduced_collection_failure_is_not_an_analyzable_test_execution():
    text = "E ModuleNotFoundError: No module named 'google'\n!!! Interrupted: 2 errors during collection !!!\n2 errors in 0.1s\n"
    result = evaluate_replay(run(text), {"output": text, "returncode": 0})
    assert result["classification"] == "infrastructure"
    assert result["output_relation"] == "raw_equal"
    assert result["needs_manual_review"]


def test_transport_timeout_overrides_partial_output_match():
    result = evaluate_replay(run("1 passed in 0.1s\n", timed_out=True),
                             {"output": "1 passed in 0.1s\n", "returncode": 0})
    assert result["classification"] == "infrastructure" and not result["supports_output_fidelity"]


def test_silent_exit_zero_needs_manual_assertion_and_collection_review():
    result = evaluate_replay(run(""), {"output": "", "returncode": 0})
    assert result["classification"] == "exact" and result["needs_manual_review"]
    assert not result["actual_test_evidence"]["observed_test_evidence"]


def test_combined_stream_order_is_not_invented():
    result = evaluate_replay(run("first\n", stderr="last\n"), {"output": "first\nlast\n", "returncode": 0})
    assert result["classification"] == "exact" and result["needs_manual_review"]
    assert "archived_combined_stream_order_cannot_be_reconstructed" in result["reasons"]


def test_final_program_difference_does_not_fail_original_fidelity():
    original = run("1 passed in 0.1s\n")
    summary = {"original_command_execution": original, "historical_test_only": original,
               "final_test_only": run("1 failed in 0.1s\n", 1)}
    result = evaluate_replay(summary, {"output": original["stdout"], "returncode": 0})
    assert result["classification"] == "exact"
    assert result["final_test_only"]["returncode"] == 1
    assert result["historical_test_only"]["runner_evidence_matches_original"]


def test_go_test_identity_duration_and_cache_state_are_preserved():
    old = "=== RUN   TestX\n--- PASS: TestX (0.00s)\nPASS\nok  example/pkg\t0.012s\n"
    new = "=== RUN   TestX\n--- PASS: TestX (0.03s)\nPASS\nok  example/pkg\t0.248s\n"
    result = evaluate_replay(run(new), {"output": old, "returncode": 0})
    assert result["classification"] == "normalized_semantic_match"
    assert result["actual_test_evidence"]["identities"][0]["id"] == "TestX"
    assert evaluate_replay(run(new.replace("0.248s", "(cached)")),
                           {"output": old, "returncode": 0})["classification"] == "mismatch"


def test_unknown_archive_and_returncode_missing_require_review():
    assert evaluate_replay(run(""), None)["classification"] == "insufficient_evidence"
    assert evaluate_replay(run("1 passed in 0.1s\n"),
                           {"output": "1 passed in 0.1s\n"})["classification"] == "insufficient_evidence"


def test_mixed_literal_and_actual_newlines_are_not_silently_unescaped():
    old = "expected literal \\n\n1 passed in 0.1s\n"
    new = "expected literal \n\n1 passed in 0.1s\n"
    assert evaluate_replay(run(new), {"output": old, "returncode": 0})["classification"] == "mismatch"


def test_rust_and_unittest_reports_have_counts_or_identities():
    assert extract_evidence("test examples::target ... ok\n")["identities"][0]["id"] == "examples::target"
    assert extract_evidence("Ran 3 tests in 0.03s\nOK\n")["summaries"][0]["tests"] == 3


def test_vitest_runner_wallclock_changes_preserve_counts_and_other_output():
    old = " Test Files  10 passed (10)\n      Tests  158 passed (158)\n   Start at  20:59:34\n   Duration  2.84s (transform 504ms)\n M target.ts\n"
    new = old.replace("20:59:34", "18:02:43").replace("2.84s", "1.74s").replace("504ms", "507ms")
    result = evaluate_replay(run(new), {"output": old, "returncode": 0})
    assert result["classification"] == "normalized_semantic_match"
    assert "vitest_runner_start_wallclock" in result["normalization_rules"]
    assert evaluate_replay(run(new.replace("158 passed", "157 passed")),
                           {"output": old, "returncode": 0})["classification"] == "mismatch"
    assert evaluate_replay(run("Start at 18:02:43\n"),
                           {"output": "Start at 20:59:34\n", "returncode": 0})["classification"] == "mismatch"
