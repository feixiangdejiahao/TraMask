"""Synthetic receipt trees and mocked subject execution only, always tmp_path."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from test_continuation_dispatch_v01 import queue, write
from test_validation_material import evidence
from tramask_rerun import continuation_candidates_v01 as direct
from tramask_rerun import continuation_dispatch_v01 as dispatch
from tramask_rerun import variants


def proposed(rank=1, new="== 2"):
    return {"rank": rank, "status": "proposed", "factor": "synthetic",
        "location": "tmp/test.py", "current_state": "one", "proposed_state": "two",
        "contract_justification": "Synthetic fixture, no scientific evidence.",
        "evidence_refs": ["synthetic"], "change_scope": "test_body_or_assertions",
        "semantic_factor_count": 1, **{flag: True for flag in variants.FLAGS},
        "edits": [{"path": "tmp/test.py", "old": "== 1", "new": new}],
        "operation_groups": [{"factor": "synthetic", "operations": [
            {"id": "op1", "description": "Synthetic fixture", "edit_indices": [0]}]}]}


@pytest.fixture
def prepared(queue, evidence):
    """Use existing pure fixture schemas; never invoke dispatch/provider."""
    run = queue["run"]
    evidence.load()
    for index, row in enumerate(queue["data"]["requests"][:36], 1):
        original_path = Path(row["original_result"]["path"])
        original = json.loads(original_path.read_text())
        original.update(case_id=f"H{index:03d}", repeat=1)
        if index == 1:
            original_path = run / "runs/H001/track_b/M1/repeat_01/stage_02/result.json"
            row_path = Path(row["prepared_request"]["path"])
            request = json.loads(row_path.read_text())
            request.update(prompt=json.dumps({"material": {"selected_test": {"id": "original"}}}),
                validation_context={"candidate_slots": 5, "original_command": evidence.test["command"],
                    "editable_paths": ["tmp/test.py"], "edit_policy": "general_augmentation",
                    "available_evidence_refs": ["synthetic"]})
            row["prepared_request"] = write(row_path, request)
            row["original_prepared_request"] = write(Path(row["original_prepared_request"]["path"]), request)
            payload, fingerprint = dispatch._payload(request)
            pp = Path(row["provider_payload"]["path"])
            pp.write_bytes(payload)
            row.update(provider_payload=dispatch._receipt(pp), provider_request_sha256=fingerprint,
                serialized_payload_utf8_bytes=len(payload),
                conservative_reservation_tokens=len(payload) + 1024 + request["max_tokens"])
            manifest = {"status": "budget_exceeded", "external_model_calls": 0, "request_sha256": fingerprint}
            row["original_provider_manifest"] = write(Path(row["original_provider_manifest"]["path"]), manifest)
            original.update(public_input=evidence.arguments[0], request=row["original_prepared_request"],
                provider_manifest=row["original_provider_manifest"])
        row["original_result"] = write(original_path, original)
    queue["bind"]()
    pre, freeze, auth = queue["receipts"]
    row = queue["data"]["requests"][0]
    stage = Path(row["original_result"]["path"]).parent.parent / "stage_01"
    planning = write(stage / "planning.json", {"status": "planned_target", "selected_test_id": "original",
        "original_command": evidence.test["command"]})
    stage1 = write(stage / "result.json", {"case_id": "H001", "method": "M1", "repeat": 1,
        "status": "planning_qualified_for_next_generation", "planning": planning, "public_input": evidence.arguments[0]})
    caps = dict(zip(direct.PHASES, [12, 20, 60, 720, 60])) | {"total_subject_test_run_cap": 872}
    protocol = write(run / "protocol.json", {"pilot4": {"execution_budget_per_method_repeat": caps}})
    baseline = write(run / "runs/H001/baseline/summary.json", {"status": "failed", "returncode": 1})
    binding = {"queue_ordinal": 1, "stage1_result": stage1, "planning": planning,
        "public_input": evidence.arguments[0], "inventory": evidence.arguments[1],
        "checkpoint_proof": evidence.keywords["checkpoint_proof_receipt"],
        "terminal_exports": evidence.keywords["terminal_export_receipts"],
        "environment": write(run / "runs/H001/environment.json", {"test_timeout_seconds": 5, "resources": {"cpus": 1}}),
        "old_baselines": [baseline], "cost_snapshot": write(run / "cost_snapshot.json",
            {"case_id": "H001", "method": "M1", "repeat": 1, "protocol": protocol,
             "prior_by_phase": {p: 0 for p in direct.PHASES}, "evidence": []})}
    materials = {"schema": "tramask.continuation-direct-materials.v1", "preflight": pre,
                "freeze": freeze, "protocol": protocol, "cells": [binding]}
    materials_receipt = write(run / "materials.json", materials)
    output = Path(queue["freeze"]["output_root"])
    report_binding = {"preflight": pre, "freeze": freeze, "authorization": auth, "output_root": str(output)}
    write(output / "queue_binding.json", report_binding)
    attempt = output / "001"
    write(attempt / "attempt.json", {**report_binding, "queue_ordinal": 1,
        "request": row["prepared_request"], "provider_request_sha256": row["provider_request_sha256"]})
    request = json.loads(Path(row["prepared_request"]["path"]).read_text())
    write(attempt / "prepared_request.json", request)
    abstain = lambda n: {"rank": n, "status": "no_proposal", "reason": "Synthetic abstention"}
    response = {"original_command": request["validation_context"]["original_command"],
        "candidates": [proposed(), {"rank": 2, "status": "bad"}, abstain(3), abstain(4), abstain(5)]}
    (attempt / "provider").mkdir()
    content = json.dumps(response)
    body = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode()
    (attempt / "provider/response.body").write_bytes(body)
    (attempt / "provider/completion.txt").write_text(content)
    manifest = {"status": "complete", "external_model_calls": 1,
        "http_status": 200, "finish_reason": "stop",
        "request_sha256": row["provider_request_sha256"], "response_sha256": hashlib.sha256(body).hexdigest()}
    write(attempt / "provider/manifest.json", manifest)
    dispatch._postprocess(row, request, attempt, manifest)
    report = write(output / "dispatch_synthetic.json", {"schema": "tramask.continuation-dispatch.v1",
        "binding": report_binding, "requests": [{"queue_ordinal": 1, "result": dispatch._receipt(attempt / "result.json")}]})
    args = {"preflight_receipt": pre, "freeze_receipt": freeze,
            "continuation_receipts": [report], "materials_receipt": materials_receipt}
    return {"args": args, "run": run, "attempt": attempt, "materials": materials,
            "binding": binding, "evidence": evidence, "queue": queue}


def plan(prepared):
    result = direct.prepare(**prepared["args"])
    slot = result["cells"][0]["slots"][0]
    assert "preparation" in slot, (result["cells"][0].get("preparation_error"), slot.get("preparation_error"))
    return slot["preparation"]


def rebind_materials(prepared):
    prepared["args"]["materials_receipt"] = write(prepared["run"] / "materials.json", prepared["materials"])


def test_pure_preparation_all36_five_slots_actual_output_only_and_failed_baseline(prepared, monkeypatch):
    monkeypatch.setattr(direct.track_b_targets, "_execute_arm", lambda *a: pytest.fail("runtime during prepare"))
    before = {p: p.read_bytes() for p in prepared["run"].rglob("*") if p.is_file()}
    result = direct.prepare(**prepared["args"])
    assert len(result["cells"]) == 36 and result["registered_slots"] == 180
    assert result["prepared_candidates"] == 1
    assert [s["status"] for s in result["cells"][0]["slots"]] == ["proposed", "invalid", "no_proposal", "no_proposal", "no_proposal"]
    assert all(c["status"] == "pending_actual_continuation_output" for c in result["cells"][1:])
    value = plan(prepared)
    assert set(value["arms"]) == set(direct.ARMS)
    assert value["repeats"] == 3 and value["subject_test_run_cap_this_candidate"] == 6
    assert value["budget"]["maximum_new_by_phase"][direct.PHASES[1]] == 2
    assert value["budget"]["maximum_new_by_phase"][direct.PHASES[2]] == 4
    assert value["old_baselines"] == prepared["binding"]["old_baselines"]
    assert value["scientific_label"] is None and value["fixed_q_receipt"] is None
    assert value["arms"]["p_candidate"]["files"]["/tmp/test.py"]["content"] == "assert value() == 2\n"
    assert before == {p: p.read_bytes() for p in prepared["run"].rglob("*") if p.is_file()}


def test_no_explicit_reports_means_no_generation_claim(prepared):
    args = {**prepared["args"], "continuation_receipts": []}
    result = direct.prepare(**args)
    assert result["prepared_candidates"] == 0
    assert all(s["status"] == "pending_output" for c in result["cells"] for s in c["slots"])


@pytest.mark.parametrize("finish,http_status,provider_status,expected", [
    ("length", 200, "incomplete", 0), ("stop", 503, "error", 0), ("stop", 200, "error", 1)])
def test_stop_and_http_gate_preserve_slots_and_recoverable_provider_error(prepared, finish, http_status, provider_status, expected):
    attempt = prepared["attempt"]
    response_path = attempt / "provider/response.body"
    response = json.loads(response_path.read_text())
    response["choices"][0]["finish_reason"] = finish
    response_bound = write(response_path, response)
    manifest_path = attempt / "provider/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(status=provider_status, error_type="JSONDecodeError", finish_reason=finish,
                    http_status=http_status, response_sha256=response_bound["sha256"])
    manifest_bound = write(manifest_path, manifest)
    result_path = attempt / "result.json"
    result = json.loads(result_path.read_text())
    result.update(provider_manifest=manifest_bound, provider_status=provider_status)
    result_bound = write(result_path, result)
    report_path = Path(prepared["args"]["continuation_receipts"][0]["path"])
    report = json.loads(report_path.read_text())
    report["requests"][0]["result"] = result_bound
    prepared["args"]["continuation_receipts"] = [write(report_path, report)]
    value = direct.prepare(**prepared["args"])
    assert value["prepared_candidates"] == expected
    assert [s["status"] for s in value["cells"][0]["slots"]] == ["proposed", "invalid", "no_proposal", "no_proposal", "no_proposal"]


@pytest.mark.parametrize("filename", ["provider/response.body", "provider/completion.txt", "candidate_slots.json", "canonical_candidates.json"])
def test_changed_raw_or_canonical_output_refused(prepared, filename):
    p = prepared["attempt"] / filename
    if filename == "provider/completion.txt":
        p.write_text("{}")
    else:
        p.write_text("{}")
    with pytest.raises((ValueError, KeyError)):
        direct.prepare(**prepared["args"])


def test_wrong_stage1_is_not_silently_substituted(prepared):
    prepared["binding"]["planning"] = write(prepared["run"] / "foreign_planning.json", {
        "selected_test_id": "original", "original_command": "python /tmp/test.py"})
    rebind_materials(prepared)
    result = direct.prepare(**prepared["args"])
    assert result["prepared_candidates"] == 0
    assert "stage1_selection_binding" in result["cells"][0]["preparation_error"]


@pytest.mark.parametrize("field", ["environment", "old_baselines"])
def test_other_case_environment_or_baseline_refused(prepared, field):
    original = prepared["binding"][field]
    original = original[0] if field == "old_baselines" else original
    replacement = write(prepared["run"] / ("foreign_" + field + ".json"), json.loads(Path(original["path"]).read_text()))
    prepared["binding"][field] = [replacement] if field == "old_baselines" else replacement
    rebind_materials(prepared)
    result = direct.prepare(**prepared["args"])
    assert result["prepared_candidates"] == 0
    assert "original_case" in result["cells"][0]["preparation_error"]


def test_forged_high_caps_cannot_replace_registered_protocol(prepared):
    protocol = copy.deepcopy(json.loads(Path(prepared["materials"]["protocol"]["path"]).read_text()))
    protocol["pilot4"]["execution_budget_per_method_repeat"][direct.PHASES[1]] = 999999
    prepared["materials"]["protocol"] = write(prepared["run"] / "unregistered_protocol.json", protocol)
    rebind_materials(prepared)
    result = direct.prepare(**prepared["args"])
    assert result["prepared_candidates"] == 0
    assert "original_registered_protocol_caps" in result["cells"][0]["preparation_error"]


def test_registered_phase_cap_enforced_before_preparation(prepared):
    path = Path(prepared["binding"]["cost_snapshot"]["path"])
    cost = json.loads(path.read_text())
    cost["prior_by_phase"][direct.PHASES[1]] = 20
    cost["evidence"] = prepared["binding"]["old_baselines"]
    prepared["binding"]["cost_snapshot"] = write(path, cost)
    rebind_materials(prepared)
    result = direct.prepare(**prepared["args"])
    assert result["prepared_candidates"] == 0
    assert "cap_exceeded" in result["cells"][0]["preparation_error"]


def test_explicit_shared_go_policy_and_preexisting_count1(tmp_path):
    staged = {"arms": {name: {"command": "go test ./..."} for name in direct.ARMS}}
    cell, material = {"case_id": "H001"}, {"test_id": "original"}
    with pytest.raises(ValueError, match="explicit_uncached"):
        direct._runner_arms(staged, {}, cell, material)
    qualification = write(tmp_path / "qualification.json", {"status": "runner_contract"})
    policy = {"kind": "go_cache_bypass", "approved_for_execution": True,
        "shared_across_all_arms": True, "case_id": "H001", "test_id": "original",
        "qualification_receipt": qualification}
    bound = write(tmp_path / "policy.json", policy)
    arms = direct._runner_arms(staged, {"runner_policy": bound}, cell, material)
    assert arms["p_original"]["command"] == arms["p_candidate"]["command"]
    assert arms["p_original"]["command"].endswith("go test ./...")
    staged = {"arms": {name: {"command": "go test -count=1 ./..."} for name in direct.ARMS}}
    assert direct._runner_arms(staged, {}, cell, material)["p_original"]["command"] == "go test -count=1 ./..."
    with pytest.raises(ValueError, match="explicit_count"):
        direct._runner_arms(staged, {"runner_policy": bound}, cell, material)
    staged = {"arms": {name: {"command": "go test -count=1 -count=2 ./..."} for name in direct.ARMS}}
    with pytest.raises(ValueError, match="conflicting_or_nonunit_count"):
        direct._runner_arms(staged, {}, cell, material)


def test_q_is_separate_after_output_freeze_and_never_direct_gate(prepared):
    value = plan(prepared)
    fixed = write(prepared["run"] / "independent_q.json", {"edits": [
        {"path": "app/code.py", "old": "return 1", "new": "return 7"}]})
    q = direct.prepare_evaluator_q(value, fixed)
    assert set(q["arms"]) == {"q_original", "q_candidate"}
    assert q["execution_authorized"] is False
    assert plan(prepared) == value
    bad_q = write(prepared["run"] / "bad_q.json", {"edits": [{"path": "app/missing.py", "old": "x", "new": "y"}]})
    with pytest.raises(ValueError):
        direct.prepare_evaluator_q(value, bad_q)
    assert plan(prepared) == value


def fake_runtime(calls, *, interrupt=False):
    def run(plan, arm, directory):
        calls.append((plan, arm, directory))
        if interrupt:
            raise RuntimeError("synthetic interruption")
        result = {"status": "completed", "execution": {"returncode": 0, "timed_out": False,
            "stdout": "FAIL synthetic assertion\n", "stderr": "", "elapsed_seconds": 0.1},
            "builds": [{"elapsed_seconds": 0.2}] if arm["build_steps"] else []}
        write(directory / "result.json", result)
        (directory / "stdout.bin").write_bytes(b"FAIL synthetic assertion\n")
        return result
    return run


def test_explicit_six_runs_raw_receipts_shell0_no_label_and_no_rerun(prepared, monkeypatch):
    value = plan(prepared)
    bound = direct.write_preparation(value, prepared["run"] / "prepared_candidate.json")
    calls = []
    monkeypatch.setattr(direct.track_b_targets, "_execute_arm", fake_runtime(calls))
    with pytest.raises(ValueError, match="explicit_execute"):
        direct.execute_preparation(bound)
    assert not calls
    result = direct.execute_preparation(bound, execute=True)
    assert len(calls) == result["subject_test_runs"] == 6
    assert len({str(c[2]) for c in calls}) == 6
    assert result["scientific_label"] is None
    assert all(r["scientific_label"] is None and r["raw_receipts"] for r in result["runs"])
    assert result["old_baselines"] == value["old_baselines"]
    with pytest.raises(FileExistsError, match="no_retry"):
        direct.execute_preparation(bound, execute=True)
    second = direct.write_preparation(value, prepared["run"] / "another_plan_filename.json")
    with pytest.raises(FileExistsError, match="no_retry"):
        direct.execute_preparation(second, execute=True)
    assert len(calls) == 6


def test_partial_candidate_is_retained_and_never_resumed(prepared, monkeypatch):
    bound = direct.write_preparation(plan(prepared), prepared["run"] / "plan.json")
    calls = []
    monkeypatch.setattr(direct.track_b_targets, "_execute_arm", fake_runtime(calls, interrupt=True))
    with pytest.raises(RuntimeError, match="synthetic"):
        direct.execute_preparation(bound, execute=True)
    with pytest.raises(FileExistsError, match="no_retry"):
        direct.execute_preparation(bound, execute=True)
    assert len(calls) == 1


def test_plan_cannot_change_candidate_or_output_even_with_new_digest(prepared):
    value = plan(prepared)
    value["output"] += "_retry"
    value.pop("plan_sha256")
    value["plan_sha256"] = direct._digest(value)
    with pytest.raises(ValueError, match="exact_frozen_candidate"):
        direct.write_preparation(value, prepared["run"] / "tampered.json")


def test_default_cli_has_no_write_or_runtime(prepared, monkeypatch, capsys):
    args = []
    for key in ("preflight_receipt", "freeze_receipt", "materials_receipt"):
        path = prepared["run"] / (key + "_argument.json")
        write(path, prepared["args"][key])
        args += ["--" + key.replace("_", "-"), str(path)]
    report_arg = prepared["run"] / "report_argument.json"
    write(report_arg, prepared["args"]["continuation_receipts"][0])
    args += ["--continuation-receipt", str(report_arg)]
    monkeypatch.setattr(direct.track_b_targets, "_execute_arm", lambda *a: pytest.fail("runtime during default CLI"))
    before = sorted(prepared["run"].rglob("*"))
    assert direct.main(args) == 0
    assert json.loads(capsys.readouterr().out)["prepared_candidates"] == 1
    assert sorted(prepared["run"].rglob("*")) == before


@pytest.mark.parametrize("scope", ["valid", "wrong_path", "wrong_case"])
def test_existing_gitlink_proof_composition_keeps_failed_summary_and_checks_raw_bytes(evidence, tmp_path, scope):
    evidence.load()
    original = json.loads(Path(evidence.keywords["checkpoint_proof_receipt"]["path"]).read_text())
    expected = "b" * 40
    previous = write(tmp_path / "old_validation.json", {"mismatches": [], "unverified": [
        {"path": "site/themes/hello-friend" if scope != "wrong_path" else "another/gitlink",
         "reason": "submodule_worktree_not_validated", "expected": {"oid": expected}}],
        "submitted_commit_tree_matches": True, "index_tree_matches_submitted_commit": True,
        "matched_existing_files": 1})
    original.update(state_validation_passed=False, validation_receipt=previous)
    summary = write(tmp_path / "historical_summary.json", original)
    snapshot = {k: {"returncode": 0, "stdout": expected + "\n" if k == "head" else
        "" if k == "status" else "tree\n"} for k in ("head", "index", "head_tree", "status")}
    snapshot["tree"] = [{"path": "synthetic", "sha256": "c" * 64}]
    raw = []
    for name in ("initial", "terminal"):
        raw.append(write(tmp_path / (name + ".stdout.bin"), snapshot))
        stderr = tmp_path / (name + ".stderr.bin")
        stderr.write_bytes(b"")
        raw.append(direct._receipt(stderr))
    qualification_value = {"checkpoint": evidence.checkpoint, "case_id": "HS005" if scope != "wrong_case" else "HS006",
        "submission_filesystem_state_status": "matched_with_initialized_gitlink_qualification",
        "subject_files_or_real_index_patched": False, "subject_commands_replayed_again": False,
        "previous_validation": previous, "expected_gitlink_commit": expected,
        "all_regular_tracked_files_matched_previously": 1,
        "snapshots": {"initial": snapshot, "terminal": copy.deepcopy(snapshot)}, "raw_receipts": raw}
    qualification = write(tmp_path / "qualification.json", qualification_value)
    active = write(tmp_path / "active.json", {**evidence.checkpoint, "state_validation_passed": True,
        "summary": summary, "validation": qualification})
    if scope != "valid":
        with pytest.raises(ValueError, match="qualification_required|unresolved_original_checkpoint_validation"):
            direct.compose_qualified_checkpoint_proof(active)
        return
    proof = direct.compose_qualified_checkpoint_proof(active)
    assert proof["state_validation_passed"] is True and proof["scientific_label"] is None
    assert json.loads(Path(summary["path"]).read_text())["state_validation_passed"] is False
    composed = write(tmp_path / "composed_proof.json", proof)
    material = direct.load_validation_material(*evidence.arguments,
        checkpoint_proof_receipt=composed, terminal_export_receipts=evidence.keywords["terminal_export_receipts"])
    assert material["checkpoint"] == evidence.checkpoint
    Path(raw[0]["path"]).write_text("{}")
    with pytest.raises(ValueError, match="receipt_hash_or_size"):
        direct.compose_qualified_checkpoint_proof(active)
