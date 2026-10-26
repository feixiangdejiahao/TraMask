"""Synthetic tmp_path artifacts only. No provider, Docker or scientific results."""
import copy
import json
from pathlib import Path

import pytest

from tramask_rerun import context_candidates_v01 as context
from tramask_rerun import continuation_dispatch_v01 as dispatch, variants


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")
    return context._receipt(path)


@pytest.fixture
def cell(tmp_path, monkeypatch):
    root = tmp_path / "synthetic"
    files = {"app/code.py": "def value():\n    return 1\n",
             "tmp/test.py": "setup = 0\nresult = value()\nassert result == 1\n"}
    h = {"status": "proposed", "reason": "synthetic only", "original_command": "python /tmp/test.py",
        "target": {"source_path": "app/code.py", "behavior": "value", "anchor": "return",
                   "logical_effect": "value", "public_observation": "result"},
        "alternative": {"kind": "targeted_mutation", "rationale": "synthetic", "action_ids": [],
                        "edits": [{"path": "app/code.py", "old": "return 1", "new": "return 2"}]},
        "instrumentation": {"command": "python /tmp/test.py", "noninterference": "pending",
            "shared_anchors": [
                {"id": "effect", "channel": "effect", "p_location": "return", "q_location": "return", "meaning": "value"},
                {"id": "observation", "channel": "observation", "p_location": "assert", "q_location": "assert", "meaning": "result"}],
            "common_edits": [], "p_edits": [], "q_edits": [], "helper_files": []}}
    selected = {"id": "original", "command": h["original_command"], "files": {"tmp/test.py": files["tmp/test.py"]}}
    packet = write(root / "packet.json", {"selected_test": selected, "final_sources": files})
    inputs = {"case": {"id": "HF012", "language": "python", "test_timeout_seconds": 30,
                       "checkpoint": {"image_id": "sha256:" + "0" * 64, "head": "0" * 40}},
              "source_files": files, "hypothesis": h, "source_origins": {}, "test_paths": ["tmp/test.py"],
              "build_commands": [], "generated_runtime": False, "observation_paths": [], "bound_artifacts": []}
    inputs_receipt = write(root / "inputs.json", inputs)
    request = {"id": "HF012/synthetic", "system": "Synthetic fixture only", "max_tokens": 8192,
        "prompt": json.dumps({"material": {"target": h["target"], "alternative": h["alternative"], "selected_test": selected}}),
        "validation_context": {"original_command": h["original_command"], "candidate_slots": 5,
                               "editable_paths": ["tmp/test.py"], "available_evidence_refs": ["issue"], "edit_policy": "context_only"}}
    request_receipt = write(root / "request.json", request)
    row = {"queue_ordinal": 38, "category": "HF012_context_track_a", "condition": "C2", "repeat": 1,
           "prepared_request": request_receipt, "provider_request_sha256": "f" * 64,
           "construction_provenance_only": {"public_packet": packet, "measurement_inputs": inputs_receipt}}
    output = root / "continuation_execution_test"
    pre = write(root / "preflight.json", {"requests": [row]})
    fr = write(root / "freeze.json", {"preflight": pre, "output_root": str(output)})
    monkeypatch.setattr(dispatch, "inspect_queue", lambda p, f: {
        "preflight": {"requests": [row]}, "output_root": output})
    candidate = {"rank": 1, "status": "proposed", "factor": "setup", "location": "tmp/test.py",
        "current_state": "0", "proposed_state": "1", "evidence_refs": ["issue"],
        "contract_justification": "synthetic", "semantic_factor_count": 1, "change_scope": "context_only",
        **{flag: True for flag in variants.FLAGS},
        "edits": [{"path": "tmp/test.py", "old": "setup = 0", "new": "setup = 1"}],
        "operation_groups": [{"factor": "setup", "operations": [{"id": "op1", "description": "setup", "edit_indices": [0]}]}]}
    response = {"original_command": h["original_command"], "candidates": [candidate] + [
        {"rank": i, "status": "no_proposal", "reason": "synthetic abstention"} for i in range(2, 6)]}
    directory = output / "038"
    fixture = {"pre": pre, "freeze": fr, "row": row, "inputs": inputs, "request": request,
               "candidate": candidate, "response": response, "directory": directory, "root": root}

    def deliver(*, text=None, finish="stop", status="complete"):
        directory.mkdir(parents=True)
        (directory / "prepared_request.json").write_bytes(Path(request_receipt["path"]).read_bytes())
        write(directory / "attempt.json", {"queue_ordinal": 38, "request": request_receipt,
            "provider_request_sha256": row["provider_request_sha256"], "preflight": pre, "freeze": fr})
        text = json.dumps(response) if text is None else text
        body = {"choices": [{"finish_reason": finish, "message": {"content": text}}]}
        body_receipt = write(directory / "provider/response.body", body)
        (directory / "provider/completion.txt").write_text(text)
        manifest = {"status": status, "external_model_calls": 1, "http_status": 200,
                    "finish_reason": finish, "response_sha256": body_receipt["sha256"],
                    "request_sha256": row["provider_request_sha256"]}
        write(directory / "provider/manifest.json", manifest)
        dispatch._postprocess(row, request, directory, manifest)
        report = {"schema": "tramask.continuation-dispatch.v1",
                  "binding": {"preflight": pre, "freeze": fr, "output_root": str(output)},
                  "requests": [{"queue_ordinal": 38, "result": context._receipt(directory / "result.json")}]}
        fixture["report"] = write(root / "dispatch_report.json", report)
        return fixture["report"]

    fixture["deliver"] = deliver
    fixture["prepare"] = lambda: context.prepare(pre, fr, 38, dispatch_report_receipt=fixture.get("report"))
    return fixture


def test_no_response_stays_missing_and_prepare_has_no_writes(cell):
    before = sorted(cell["root"].rglob("*"))
    plan = cell["prepare"]()
    assert plan["status"] == "provider_result_not_supplied"
    assert [x["status"] for x in plan["slots"]] == ["not_executed"] * 5
    assert sorted(cell["root"].rglob("*")) == before
    assert not cell["directory"].exists()


def test_five_slots_fixed_Q_and_shared_arms(cell):
    cell["deliver"]()
    before = sorted(cell["root"].rglob("*"))
    plan = cell["prepare"]()
    assert len(plan["slots"]) == 5 and plan["slots"][0]["execution_eligible"]
    assert plan["shared_track_a_methods"] == ["M3"]
    assert plan["base_subject_run_cap"] == 20
    assert plan["slots"][0]["execution_binding"]["repeats"] == 1
    assert plan["inputs"]["hypothesis"] == cell["inputs"]["hypothesis"]
    assert all(x["scientific_label"] is None for x in plan["slots"])
    assert sorted(cell["root"].rglob("*")) == before


def test_registered_transport_recovery_can_use_complete_stop_response(cell):
    cell["deliver"](text=json.dumps(cell["response"])[:-1], status="error")
    assert cell["prepare"]()["slots"][0]["execution_eligible"]


def test_truncated_valid_json_is_retained_but_never_executed(cell):
    cell["deliver"](finish="length", status="incomplete")
    plan = cell["prepare"]()
    assert plan["status"] == "provider_incomplete_no_execution"
    assert plan["slots"][0]["status"] == "proposed"
    assert not any(s["execution_eligible"] for s in plan["slots"])


def test_malformed_actual_response_keeps_five_invalid_slots(cell):
    cell["deliver"](text="This is not JSON", status="error")
    plan = cell["prepare"]()
    assert [x["status"] for x in plan["slots"]] == ["invalid"] * 5
    assert not any(x["execution_eligible"] for x in plan["slots"])


def test_raw_completion_and_derived_files_cannot_be_replaced_together(cell):
    cell["deliver"]()
    directory = cell["directory"]
    cell["response"]["candidates"][0]["edits"][0]["new"] = "setup = 99"
    (directory / "provider/completion.txt").write_text(json.dumps(cell["response"]))
    write(directory / "canonical_candidates.json", cell["response"])
    with pytest.raises(ValueError, match="completion_differs"):
        cell["prepare"]()


def test_raw_response_cannot_be_replaced_behind_manifest_receipt(cell):
    cell["deliver"]()
    path = cell["directory"] / "provider/response.body"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="response_digest"):
        cell["prepare"]()


def test_saved_canonical_and_slots_must_match_raw_output(cell):
    cell["deliver"]()
    write(cell["directory"] / "canonical_candidates.json", {"different": True})
    with pytest.raises(RuntimeError, match="canonical_response_differs"):
        cell["prepare"]()


def test_fixed_input_Q_cannot_be_changed(cell):
    cell["inputs"]["hypothesis"]["alternative"]["edits"][0]["new"] = "return 99"
    # Deliberately update the synthetic fixture receipt; cross-input binding
    # must still reject mismatch with the frozen request's Q.
    cell["row"]["construction_provenance_only"]["measurement_inputs"] = write(
        cell["root"] / "inputs.json", cell["inputs"])
    with pytest.raises(ValueError, match="fixed_target_Q_test"):
        cell["prepare"]()


def test_report_must_bind_this_cell(cell):
    cell["deliver"]()
    report = json.loads(Path(cell["report"]["path"]).read_text())
    report["requests"] = []
    cell["report"] = write(cell["root"] / "dispatch_report.json", report)
    with pytest.raises(ValueError, match="does_not_bind_completed_cell"):
        cell["prepare"]()


def test_execute_requires_exact_review_and_fixed_output(cell, monkeypatch):
    cell["deliver"]()
    plan = cell["prepare"]()
    slot = plan["slots"][0]
    calls = []
    monkeypatch.setattr(context.paired, "execute_candidate_pair", lambda *a, **kw: calls.append((a, kw)) or {"synthetic": True})
    with pytest.raises(ValueError, match="technical_execution_review"):
        context.execute_base(plan, 1, {})
    changed = copy.deepcopy(plan)
    changed["slots"][0]["execution_output"] += "_retry"
    with pytest.raises(ValueError, match="plan_changed"):
        context.execute_base(changed, 1, {})
    review = {"approved_for_execution": True, "reviewer_id": "synthetic", "rationale": "unit test",
              "binding": slot["execution_binding"]}
    context.execute_base(plan, 1, review)
    assert len(calls) == 1 and calls[0][1]["repeats"] == 1
    assert calls[0][0][-1] == slot["execution_output"]
    assert calls[0][0][2] == cell["inputs"]["hypothesis"]
    with pytest.raises(ValueError, match="not_eligible"):
        context.execute_base(plan, 2, review)


def test_partial_execution_directory_is_never_retried(cell):
    cell["deliver"]()
    plan = cell["prepare"]()
    slot = plan["slots"][0]
    out = Path(slot["execution_output"])
    out.mkdir(parents=True)
    review = {"approved_for_execution": True, "reviewer_id": "synthetic", "rationale": "unit test",
              "binding": slot["execution_binding"]}
    with pytest.raises((ValueError, FileExistsError), match="incomplete|partial|completion"):
        context.execute_base(plan, 1, review)
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("ordinal", [True, 37, 39])
def test_other_queue_entries_cannot_be_used(cell, ordinal):
    with pytest.raises(ValueError):
        context.prepare(cell["pre"], cell["freeze"], ordinal)
