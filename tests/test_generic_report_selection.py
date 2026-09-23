"""Selection only repairs duplicate unexecuted report rows; failures remain visible."""
import json
from pathlib import Path

import pytest

from combination_testing.test_reports import parse_report
from generic_composition import runner


def _report(tmp_path, rows, *, process=None, selected=None, suites=None):
    suites = suites or [{"name": "/repo/test.ts", "assertionResults": [
        {"fullName": name, "title": name, "status": status, "failureMessages": []}
        for name, status in rows]}]
    (tmp_path / "report.json").write_text(json.dumps({"testResults": suites}))
    return parse_report(tmp_path, {"format": "vitest-json", "path": "report.json"},
                        process or {"returncode": 0}, selected_names=selected)


def test_default_duplicate_check_unchanged(tmp_path):
    result = _report(tmp_path, [("old", "pending")] * 2 + [("chosen", "passed")])
    assert result["errors"] == ["Duplicate testcase IDs in test report"]
    assert "selection_parse" not in result
    assert len(result["tests"]) == 3


def test_explicit_selection_retains_one_unselected_skip_and_audits_exclusion(tmp_path):
    result = _report(tmp_path, [("old", "pending")] * 2 + [("chosen", "passed")],
                     selected=["chosen", "source"])
    assert result["status"] == "pass"
    assert result["counts"] == {"pass": 1, "fail": 0, "error": 0, "skip": 1}
    excluded = result["selection_parse"]["excluded_unselected_skipped_duplicates"]
    assert len(excluded) == 1 and excluded[0]["id"] == "old"
    assert result["selection_parse"]["selected_names"] == ["chosen", "source"]


@pytest.mark.parametrize("name", ["chosen", "suite::chosen", "suite::chosen[arg]", "suite::chosen/sub"])
def test_declared_duplicate_skips_stay_errors_including_parameter_subtests(tmp_path, name):
    result = _report(tmp_path, [(name, "skipped")] * 2, selected=["chosen"])
    assert result["errors"] == ["Duplicate testcase IDs in test report"]
    assert not result["selection_parse"]["excluded_unselected_skipped_duplicates"]


@pytest.mark.parametrize("status", ["failed", "passed", "unrecognized"])
def test_duplicate_unselected_executed_or_error_rows_remain_errors(tmp_path, status):
    result = _report(tmp_path, [("old", "pending"), ("old", status)], selected=["chosen"])
    assert "Duplicate testcase IDs in test report" in result["errors"]
    assert len(result["tests"]) == 2


def test_duplicate_unselected_skips_do_not_hide_collection_error(tmp_path):
    suites = [{"name": "/repo/broken.ts", "status": "failed", "message": "Cannot import dependency"},
              {"name": "/repo/old.ts", "assertionResults": [
                  {"fullName": "old", "title": "old", "status": "pending"}] * 2}]
    result = _report(tmp_path, [], selected=["chosen"], suites=suites, process={"returncode": 1})
    assert result["status"] == "error"
    assert result["counts"]["error"] == 1
    assert any(r["kind"] == "setup_or_collection" for r in result["tests"])


def test_partial_timeout_and_nonzero_exit_stay_errors(tmp_path):
    rows = [("old", "pending")] * 2 + [("chosen", "passed")]
    result = _report(tmp_path, rows, selected=["chosen"],
                     process={"returncode": None, "stage": "timeout", "error": "time limit"})
    assert result["status"] == "error" and "timeout: time limit" in result["errors"]
    result = _report(tmp_path, rows, selected=["chosen"], process={"returncode": 2})
    assert result["status"] == "error"
    assert "Nonzero command exit 2 without a failing testcase" in result["errors"]


def test_no_prefix_heuristic_and_no_passing_tests_invented(tmp_path):
    result = _report(tmp_path, [("gc_not_declared", "pending")] * 2,
                     selected=["another chosen name"])
    assert result["status"] == "inconclusive"
    assert result["counts"]["pass"] == 0
    assert len(result["selection_parse"]["excluded_unselected_skipped_duplicates"]) == 1


def test_docker_wrapper_uses_frozen_names_and_preserves_original_parse(tmp_path, monkeypatch):
    manifest = {"case_id": "any", "report": {"format": "vitest-json", "path": "report.json"},
                "metadata": {"controls": ["source"], "obligations": [
                    {"id": "suite selected", "test_name": "selected", "controls": ["source"]}]}}
    output = tmp_path / "output"
    output.mkdir()
    original = _report(output, [("old", "pending")] * 2 + [("suite selected", "passed"),
                                                               ("source", "passed")])
    original.update(process={"returncode": 0}, artifact_sha256="frozen", transport={"returncode": 0})
    monkeypatch.setattr(runner.existing, "load_artifact", lambda _: manifest)
    monkeypatch.setattr(runner.existing, "run_artifact", lambda *a, **k: dict(original))
    result = runner.run_artifact(tmp_path / "artifact", "candidate", output,
                                 registry=[{"id": "any", "image": "test-only"}])
    assert result["status"] == "pass"
    assert result["selection_parse"]["selected_names"] == ["selected", "source", "suite selected"]
    assert json.loads((output / "unfiltered_result.json").read_text()) == original
    assert json.loads((output / "result.json").read_text()) == result


def test_local_wrapper_passes_frozen_names(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    artifact = tmp_path / "artifact"
    runner.freeze_artifact(artifact, "any", {}, "true", "jsonl", "stdout.txt",
                           repository=repository, obligations=[{"id": "chosen", "controls": ["source"]}])
    calls = []
    def fake_parse(output, specification, process, *, selected_names=None):
        calls.append(selected_names)
        return {"status": "inconclusive", "tests": [], "counts": {}, "errors": []}
    monkeypatch.setattr(runner, "parse_report", fake_parse)
    runner.run_artifact(artifact, "candidate", tmp_path / "output",
                        registry=[{"id": "any", "repository": str(repository)}])
    assert calls == [["chosen", "source"]]
