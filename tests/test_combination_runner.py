import json
from pathlib import Path

import pytest

from combination_testing.runner import compare_pair, freeze_artifact, load_artifact, safe_relative
from combination_testing.test_reports import parse_report


def test_frozen_artifact_rejects_changed_test(tmp_path):
    artifact = tmp_path / "artifact"
    freeze_artifact(artifact, "P1", {"tests/test_generated.py": "assert True\n"},
                    "python -m pytest", "pytest-junit", "junit.xml")
    assert load_artifact(artifact)["files"][0]["target"] == "tests/test_generated.py"
    (artifact / "files/tests/test_generated.py").write_text("assert False\n")
    with pytest.raises(ValueError, match="Frozen artifact changed"):
        load_artifact(artifact)


@pytest.mark.parametrize("path", ["/etc/passwd", "../test.py", "tests/../../test.py", "."])
def test_generated_paths_cannot_escape_repo(path):
    with pytest.raises(ValueError):
        safe_relative(path)


def test_compilation_failure_is_not_test_failure(tmp_path):
    (tmp_path / "report.jsonl").write_text(json.dumps({"Action": "fail", "Package": "x", "Output": "build failed"}) + "\n")
    result = parse_report(tmp_path, {"format": "go-json", "path": "report.jsonl"}, {"returncode": 1})
    assert result["status"] == "error"
    assert result["counts"]["fail"] == 0


def test_invalid_generated_obligation_is_explicit_error(tmp_path):
    (tmp_path / "stdout.txt").write_text('CC_RESULT {"id":"x","status":"invalid","reason":"unsupported shape"}\n')
    result = parse_report(tmp_path, {"format": "jsonl", "path": "stdout.txt"}, {"returncode": 0})
    assert result["status"] == "error"
    assert result["tests"][0]["reason"] == "unsupported shape"


def test_partial_report_timeout_remains_error(tmp_path):
    (tmp_path / "stdout.txt").write_text('CC_RESULT {"id":"x","status":"pass"}\n')
    result = parse_report(tmp_path, {"format": "jsonl", "path": "stdout.txt"},
                          {"returncode": None, "stage": "timeout", "error": "timeout"})
    assert result["status"] == "error"


def test_pytest_assertion_and_setup_failure_differ(tmp_path):
    (tmp_path / "junit.xml").write_text('<testsuites><testsuite><testcase classname="m" name="a"><failure message="assert 1 == 2">AssertionError</failure></testcase><testcase classname="m" name="b"><error message="fixture missing"/></testcase></testsuite></testsuites>')
    result = parse_report(tmp_path, {"format": "pytest-junit", "path": "junit.xml"}, {"returncode": 1})
    assert [t["status"] for t in result["tests"]] == ["fail", "error"]
    assert result["tests"][0]["kind"] == "assertion"


def test_reference_rejection_cannot_be_called_defect():
    common = {"case_id": "P1", "artifact_sha256": "a", "status": "fail"}
    candidate = {**common, "tests": [{"id": "x", "status": "fail"}, {"id": "y", "status": "fail"}]}
    reference = {**common, "tests": [{"id": "x", "status": "pass"}, {"id": "y", "status": "fail"}]}
    result = compare_pair(candidate, reference)
    assert result["counts"]["differential_witness"] == 1
    assert result["counts"]["reference_rejected_test"] == 1


def test_pair_rejects_different_artifacts():
    with pytest.raises(ValueError, match="different frozen artifacts"):
        compare_pair({"artifact_sha256": "a"}, {"artifact_sha256": "b"})


def test_pair_does_not_count_partial_timeout_witness():
    common = {"case_id": "P1", "artifact_sha256": "a", "status": "fail"}
    candidate = {**common, "errors": ["timeout"], "tests": [{"id": "x", "status": "fail"}]}
    reference = {**common, "tests": [{"id": "x", "status": "pass"}]}
    result = compare_pair(candidate, reference)
    assert result["counts"]["differential_witness"] == 0
    assert result["counts"]["execution_error"] == 1


def test_invalid_probe_does_not_hide_valid_sibling():
    common = {"case_id": "P1", "artifact_sha256": "a", "status": "error", "errors": []}
    invalid = {"id": "invalid", "status": "error", "kind": "invalid_input_or_oracle"}
    candidate = {**common, "tests": [invalid, {"id": "valid", "status": "fail"}]}
    reference = {**common, "tests": [invalid, {"id": "valid", "status": "pass"}]}
    result = compare_pair(candidate, reference)
    assert result["counts"]["differential_witness"] == 1
    assert result["counts"]["oracle_precondition_rejected"] == 1


def test_aggregate_declared_control_blocks_candidate_alarm(tmp_path):
    from combination_testing.evaluate import evaluate_case
    from combination_testing.runner import sha256
    artifact, execution = tmp_path / "artifact", tmp_path / "execution"
    freeze_artifact(artifact, "P1", {}, "true", "jsonl", "stdout.txt",
                    metadata={"obligations": [{"id": "combined", "control": "seed"}]})
    common = {"case_id": "P1", "artifact_sha256": sha256(artifact / "manifest.json"),
              "status": "fail", "errors": []}
    for program, seed_status, combined_status in [("candidate", "fail", "fail"), ("reference", "pass", "pass")]:
        p = execution / program
        p.mkdir(parents=True)
        (p / "result.json").write_text(json.dumps({**common, "tests": [
            {"id": "seed", "status": seed_status}, {"id": "combined", "status": combined_status}]}))
    result = evaluate_case(artifact, execution)
    assert not result["detected"]
    assert not result["candidate_alarm"]
    assert result["counts"]["blocked_by_control"] == 1
    assert result["counts"]["controls"] == 1


def test_aggregate_keeps_reference_alarm_visible(tmp_path):
    from combination_testing.evaluate import evaluate_case
    from combination_testing.runner import sha256
    artifact, execution = tmp_path / "artifact", tmp_path / "execution"
    freeze_artifact(artifact, "P1", {}, "true", "jsonl", "stdout.txt")
    common = {"case_id": "P1", "artifact_sha256": sha256(artifact / "manifest.json"),
              "status": "fail", "errors": [], "tests": [{"id": "combined", "status": "fail"}]}
    for program in ("candidate", "reference"):
        p = execution / program
        p.mkdir(parents=True)
        (p / "result.json").write_text(json.dumps(common))
    result = evaluate_case(artifact, execution)
    assert result["candidate_alarm"] and result["reference_alarm"]
    assert not result["detected"]
    assert result["counts"]["reference_rejected"] == 1


def test_early_manifest_control_partition_requires_exact_seed_count():
    from combination_testing.evaluate import _dependency_map
    metadata = {"seed_controls": 2, "obligations": [{"id": "new"}]}
    _, controls = _dependency_map(metadata, ["new", "original_a", "original_b"])
    assert controls == {"original_a", "original_b"}
    metadata["seed_controls"] = 1
    assert _dependency_map(metadata, ["new", "original_a", "original_b"])[1] == set()


def test_known_target_does_not_count_unrelated_protocol_difference():
    from combination_testing.target_audit import audit_known_target
    row = {"id": "new", "confirmed_witness": True}
    metadata = {"obligations": [{"id": "new", "sequence": "\x1b[0;5:1;97u",
                                 "field": "character", "op": "eq", "expected": "a"}]}
    result = audit_known_target("P3", metadata, [row], {"new": {"status": "fail"}})
    assert not result["detected"]
    assert result["additional_differential_candidates"] == ["new"]


def test_known_clone_target_requires_source_state_stability():
    from combination_testing.target_audit import audit_known_target
    row = {"id": "new", "confirmed_witness": True}
    test = {"relation": "clone_fresh", "observed": [[1, {"x": 0}], {"x": 2}],
            "expected": [[1, {"x": 1}], {"x": 0}]}
    assert not audit_known_target("P6", {}, [row], {"new": test})["detected"]
    test["observed"][1] = {"x": 0}
    assert audit_known_target("P6", {}, [row], {"new": test})["detected"]


def test_known_recursive_target_rejects_identity_donor():
    from combination_testing.target_audit import audit_known_target
    metadata = {"obligations": [{"id": "new", "donor": None}]}
    assert not audit_known_target("P7", metadata, [{"id": "new", "confirmed_witness": True}],
                                  {"new": {"relation": "recursive_unfold"}})["detected"]


def test_counts_separate_static_controls_and_runtime_obligations(tmp_path):
    from combination_testing.evaluate import evaluate_case
    from combination_testing.runner import sha256
    artifact, execution = tmp_path / "artifact", tmp_path / "execution"
    metadata = {"obligations": [
        {"id": "identity", "is_control": True},
        {"id": "combined", "control_id": "identity"},
        {"id": "unexecuted_combination"},
        {"id": "unexecuted_control", "is_control": True},
    ], "controls": ["identity"]}
    freeze_artifact(artifact, "P7", {}, "true", "jsonl", "stdout.txt", metadata=metadata)
    common = {"case_id": "P7", "artifact_sha256": sha256(artifact / "manifest.json"),
              "status": "fail", "errors": []}
    for program in ("candidate", "reference"):
        path = execution / program
        path.mkdir(parents=True)
        status = "fail" if program == "candidate" else "pass"
        (path / "result.json").write_text(json.dumps({**common, "tests": [
            {"id": "identity", "status": "pass", "is_control": True},
            {"id": "combined", "status": status},
            {"id": "runtime_seed", "status": "pass", "is_control": True},
            {"id": "runtime_combined", "status": status, "control_id": "runtime_seed"},
        ]}))
    result = evaluate_case(artifact, execution)
    counts = result["counts"]
    assert counts["observed_obligations"] == 2
    assert counts["static_declared_obligations"] == counts["declared_obligations"] == 2
    assert counts["static_declared_controls"] == 2
    assert counts["observed_controls"] == counts["controls"] == 2
    assert counts["runtime_only_obligations"] == counts["runtime_only_controls"] == 1
    assert counts["statically_declared_observed_obligations"] == 1
    assert result["declared_unexecuted"] == ["unexecuted_combination"]
    assert result["declared_controls_unexecuted"] == ["unexecuted_control"]
    # Count reporting must not change independent alarm/control semantics.
    assert counts["candidate_alerts"] == counts["confirmed_witnesses"] == 2
    assert counts["reference_alerts"] == 0


def test_parameterized_records_are_observed_expansions_of_one_declaration():
    from combination_testing.evaluate import _declaration_counts
    metadata = {"obligations": [{"id": "combined", "control": "seed"}]}
    counts, missing, missing_controls = _declaration_counts(
        metadata, {"suite::combined[first]", "suite::combined[second]"}, {"suite::seed"})
    assert counts["static_declared_obligations"] == 1
    assert counts["observed_obligations"] == counts["statically_declared_observed_obligations"] == 2
    assert counts["runtime_only_obligations"] == 0
    assert counts["static_declared_controls"] == 1
    assert not missing and not missing_controls
