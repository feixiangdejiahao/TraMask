"""Synthetic reviewer packets; no Docker subjects, provider calls, or real labels."""
import json
from pathlib import Path

from tramask_pilot import evidence


def fixture_packet(tmp_path, monkeypatch, *, qualification=True):
    case = tmp_path / "runs/F042"
    inputs = tmp_path / "inputs/F042"
    replay = case / "replay"
    replay.mkdir(parents=True)
    inputs.mkdir(parents=True)
    (inputs / "instruction.md").write_text("Preserve the public behavior.\n")
    (inputs / "model.patch").write_text("public patch\n")
    primary = {"test_command": "python /tmp/test.py", "working_directory": "/app/subproject",
               "observation_paths": ["/tmp/observations.log"], "target": "public result", "target_anchor": "compute"}
    monkeypatch.setattr(evidence, "_selection", lambda path: (dict(primary), ["app/code.py"], ["tmp/test.py"], {}))
    monkeypatch.setattr(evidence, "selected_tree_files", lambda path, **kwargs: {
        "app/code.py": "def compute(): return 1\n", "tmp/test.py": "assert compute() == 1\n"})
    reset = {"event": "restart_after_timeout", "filesystem_preserved": True, "process_state_reset": True,
             "restoration_deviation": True, "success": True, "returncode": 0,
             "name": "SECRET_CONTAINER", "docker_argv": ["SECRET_DOCKER_ARGS"],
             "model": "SECRET_MODEL", "after_repair": {"success": "SECRET_AFTER"}}
    record = {"command": primary["test_command"], "working_directory": primary["working_directory"],
              "stdout": "1 passed\n", "stderr": "", "returncode": 0, "timed_out": False,
              "transport_error": False, "prior_restoration_deviations": [reset],
              "cohort": "SECRET_COHORT", "model": "SECRET_MODEL", "after_repair": "SECRET_AFTER",
              "observation_files": [{"subject_path": "/tmp/observations.log", "content": "public=1\n",
                                     "bytes": 9, "model": "SECRET_MODEL"}]}
    (replay / "summary.json").write_text(json.dumps({name: record for name in
        ("original_command_execution", "historical_test_only", "final_test_only")}))
    if qualification:
        report = {
            "case_id": "F042", "cohort": "SECRET_COHORT", "model": "SECRET_MODEL",
            "after_repair": "SECRET_AFTER", "scientific_masking_verdict": "SECRET_MASK_LABEL",
            "selected_call": "s2_c0", "needs_manual_review": True, "eligibility_suggestion": "pending_manual_review",
            "manual_review_reasons": ["restoration_chain_process_state_was_reset"],
            "chain_counts": {"process_state_resets": 1, "timeouts": 1, "after_successes": "SECRET_AFTER"},
            "restoration_actions": [{"call_id": "s1_c0", "timed_out": True, "returncode": 124,
                "prior_restoration_deviations": [reset], "raw_result_path": "/home/private/SECRET_HOST",
                "after_repair": "SECRET_AFTER"}],
            "lifecycle_events": [reset],
            "selected_output_fidelity": {"classification": "exact", "supports_output_fidelity": True,
                "actual_test_evidence": {"summaries": [{"runner": "pytest_like", "counts": [["passed", 1]],
                                                        "model": "SECRET_MODEL"}], "observed_test_evidence": True},
                "masking_or_correctness_verdict": "SECRET_MASK_LABEL"},
            "test_snapshot_checks": {"verified": True, "files": [{"subject_path": "/tmp/test.py",
                "historical_test_bytes_match": True, "final_test_bytes_match": True, "after_repair": "SECRET_AFTER"}]},
            "evidence_issues": ["missing_receipt:" + str(case / "replay/missing.json")],
            "evidence_receipts": [{"path": "/home/private/SECRET_HOST", "model": "SECRET_MODEL"}],
        }
        (replay / "fidelity_check.json").write_text(json.dumps(report))
    return case, inputs, record


def test_review_packet_keeps_earlier_reset_and_qualification_without_leaking_labels(tmp_path, monkeypatch):
    case, inputs, record = fixture_packet(tmp_path, monkeypatch)
    destination = tmp_path / "blinded"
    evidence.build_before_review_packet(case, inputs, destination,
        hypothesis={"status": "insufficient_evidence", "reason": "Boundary not established"},
        before_records={"p_original": record}, opaque_id="pair_blind")
    replay = json.loads((destination / "replay.json").read_text())
    assert replay["historical_test_only"]["returncode"] == 0
    assert replay["historical_test_only"]["prior_restoration_deviations"][0]["process_state_reset"] is True
    qualification = json.loads((destination / "replay_qualification.json").read_text())
    assert qualification["chain_counts"]["process_state_resets"] == 1
    assert qualification["restoration_actions"][0]["timed_out"]
    assert qualification["selected_output_fidelity"]["classification"] == "exact"
    assert qualification["test_snapshot_checks"]["verified"]
    selected = json.loads((destination / "selected_test.json").read_text())
    assert selected["working_directory"] == "/app/subproject"
    assert selected["observation_paths"] == ["/tmp/observations.log"]
    brief = json.loads((destination / "review_brief.json").read_text())
    assert "process_state_reset_requires_relevance_review" in brief["recorded_review_requirements"]
    contents = "\n".join(path.read_text() for path in destination.rglob("*") if path.is_file())
    assert "SECRET_" not in contents and "F042" not in contents and str(case) not in contents
    manifest = json.loads((destination / "manifest.json").read_text())
    assert {"replay_qualification.json", "review_brief.json"} <= {row["path"] for row in manifest["artifacts"]}


def test_missing_qualification_remains_visible_and_does_not_imply_no_deviation(tmp_path, monkeypatch):
    case, inputs, record = fixture_packet(tmp_path, monkeypatch, qualification=False)
    destination = tmp_path / "blinded"
    evidence.build_before_review_packet(case, inputs, destination,
        hypothesis={"status": "insufficient_evidence", "reason": "Boundary not established"},
        before_records={"p_original": record}, opaque_id="pair_blind")
    qualification = json.loads((destination / "replay_qualification.json").read_text())
    assert qualification["status"] == "qualification_unavailable" and qualification["needs_manual_review"]
    brief = json.loads((destination / "review_brief.json").read_text())
    assert "replay_qualification_unavailable" in brief["recorded_review_requirements"]
    assert "process_state_reset_requires_relevance_review" in brief["recorded_review_requirements"]


def test_immediate_restart_is_sanitized_and_retained():
    value = evidence._public_execution({"restart_after_timeout": {"event": "restart_after_timeout",
        "success": False, "process_state_reset": True, "error": "container_restart_failed",
        "docker_argv": ["SECRET_ARG"], "model": "SECRET_MODEL"}}, lambda text: text)
    assert value["restart_after_timeout"]["process_state_reset"]
    assert value["restart_after_timeout"]["error"] == "container_restart_failed"
    assert "SECRET" not in json.dumps(value)
