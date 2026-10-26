"""Synthetic JSON/byte fixtures only. No Docker, provider, or study artifacts."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tramask_rerun import minimization_v01 as minimization
from tramask_rerun import variants


def artifact(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
    path.write_bytes(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def inputs(count=3, rank=1):
    files = {"tmp/test.py": "".join(f"setup_{i} = False\n" for i in range(count)) + "assert value() == 1\n"}
    candidate = {"rank": rank, "status": "proposed", "factor": "synthetic setup",
        "location": "tmp/test.py", "current_state": "disabled", "proposed_state": "enabled",
        "evidence_refs": ["synthetic-source"], "contract_justification": "Synthetic test fixture only",
        "semantic_factor_count": 1, "change_scope": "context_only",
        **{flag: True for flag in variants.FLAGS},
        "edits": [{"path": "tmp/test.py", "old": f"setup_{i} = False\n", "new": f"setup_{i} = True\n"} for i in range(count)],
        "operation_groups": [{"factor": "synthetic setup", "operations": [
            {"id": f"op{i}", "description": "synthetic operation", "edit_indices": [i]} for i in range(count)]}]}
    binding = {"schema": "tramask.execution-binding.v1", "case_id": "synthetic-only",
        "checkpoint": {"image_id": "sha256:" + "a" * 64, "head": "b" * 40},
        "source_file_sha256": {"/" + key: minimization._sha(value) for key, value in files.items()},
        "hypothesis_sha256": "c" * 64,
        "command_mapping": {name: {"command": "synthetic command only", "working_directory": "/tmp"} for name in variants.VARIANTS},
        "candidate_sha256": minimization._sha(candidate), "repeats": 1}
    return files, candidate, binding


def budget():
    return minimization.MethodRepeatBudget({"pilot4": {"execution_budget_per_method_repeat": dict(minimization.PHASE_CAPS)}})


def evidence(root, request, *, outcome="pass", oracle="unresolved", batches=None, missing_checks=(),
             invariant=None, returncode=0, runtime_status="completed"):
    """Fabricate explicitly synthetic receipts to exercise the local contract."""
    batches = batches or [request["clean_repeats"]]
    basis = artifact(root / "synthetic_basis.json", {"fixture": "synthetic; not scientific evidence", "request": request})
    runs = []
    for batch, count in enumerate(batches):
        directory = root / f"synthetic_pair_{batch}"
        binding = {**request["execution_binding"], "repeats": count}
        if request["candidate_sha256"] is not None:
            binding["candidate_sha256"] = request["candidate_sha256"]
        technical = {"approved_for_execution": True, "reviewer_id": "synthetic-technical-reviewer",
                     "binding": binding, "rationale": "Synthetic fixture, never execute"}
        artifacts = [artifact(directory / "execution_review.json", technical)]
        repeats = []
        for repeat in range(1, count + 1):
            rows = {}
            for name in variants.VARIANTS:
                out = directory / str(repeat) / name
                stdout = artifact(out / "stdout.bin", b"Synthetic bytes; shell output is not a verdict.\n")
                stderr = artifact(out / "stderr.bin", b"")
                execution = {"status": runtime_status, "timed_out": runtime_status == "timeout",
                    "command": binding["command_mapping"][name]["command"], "working_directory": "/tmp",
                    "returncode": returncode, "container": str(out),
                    "raw_stdout": stdout["path"], "stdout_bytes": stdout["bytes"], "stdout_sha256": stdout["sha256"],
                    "raw_stderr": stderr["path"], "stderr_bytes": stderr["bytes"], "stderr_sha256": stderr["sha256"]}
                result = artifact(out / "result.json", {"fixture": "synthetic", "checkpoint": binding["checkpoint"],
                    "status": runtime_status, "execution": execution})
                artifacts.extend([stdout, stderr, result])
                rows[name] = {"runtime_result": result, "diagnosis": {"event_errors": []}}
            repeats.append({"repeat": repeat, "variants": rows})
        pair = artifact(directory / "summary.json", {"schema": "tramask.qualified-pair.v1", "binding": binding,
            "review_sha256": minimization._sha(technical), "repeats": repeats, "artifacts": artifacts})
        runs.extend({"pair_receipt": pair, "repeat": i} for i in range(1, count + 1))
    checks = {f"E{i}": {"status": "pass", "evidence": [basis]} for i in range(1, 10)}
    checks["E8"]["status"], checks["E9"]["status"] = outcome, oracle
    for check in missing_checks:
        checks.pop(check)
    invariants = {key: {"status": "pass", "evidence": [basis]} for key in minimization.INVARIANTS}
    if invariant:
        invariants[invariant]["status"] = "unresolved"
    return artifact(root / "qualification.json", {"schema": "tramask.minimization-qualification.v1",
        "fixture": "synthetic; never an experiment", "reviewer_id": "synthetic-independent-reviewer",
        "independent_of_generation": True, "request_sha256": minimization._sha(request),
        "runs": runs, "checks": checks, "invariants": invariants})


def start(tmp_path, count=3, *, limit=36, shared=None, rank=1, initial_options=None):
    files, candidate, binding = inputs(count, rank)
    initial = evidence(tmp_path / "initial", minimization.initial_request(candidate, binding),
                       batches=[1, 3], **(initial_options or {}))
    state = minimization.DeletionMinimizer(files, candidate,
        validation_context={"editable_paths": list(files), "available_evidence_refs": ["synthetic-source"]},
        execution_binding=binding, initial_evidence=initial, budget=shared or budget(), max_deletion_attempts=limit)
    return state


def record(state, tmp_path, outcome="pass", **kwargs):
    proposal = state.propose()
    receipt = evidence(tmp_path, proposal, outcome=outcome, **kwargs)
    return state.record_result(receipt)


def finish_without_deletions(state, tmp_path):
    for i in range(len(state.snapshot()["retained_operation_ids"])):
        record(state, tmp_path / f"deletion{i}", "fail")
    assert state.propose()["phase"] == "final_confirmation"
    record(state, tmp_path / "final")
    assert state.propose() is None
    return state.snapshot()


def test_exact_deletion_preserves_original_edits_and_restarts_scan(tmp_path):
    state = start(tmp_path)
    first = state.propose()
    assert first == state.propose()
    original = state.snapshot()["original_candidate"]
    assert first["original_edit_indices"] == [1, 2]
    assert first["candidate"]["edits"] == original["edits"][1:]
    record(state, tmp_path / "fail", "fail")
    second = state.propose()
    assert second["removed_operation_id"] == "op1"
    record(state, tmp_path / "pass")
    restarted = state.propose()
    assert restarted["removed_operation_id"] == "op0"
    assert restarted["original_edit_indices"] == [2]
    assert restarted["candidate"]["edits"] == [original["edits"][2]]
    assert restarted["candidate"]["operation_groups"][0]["operations"][0]["edit_indices"] == [0]
    assert [r["outcome"] for r in state.snapshot()["records"]] == ["fail", "pass"]


def test_empty_projection_is_executed_as_original_pair(tmp_path):
    state = start(tmp_path, 1)
    request = state.propose()
    assert request["candidate"] is None and request["candidate_sha256"] is None
    assert request["execute_as"] == "original_pair" and request["original_edit_indices"] == []
    record(state, tmp_path / "empty", "fail")
    record(state, tmp_path / "final")
    result = state.snapshot()
    assert result["one_minimal"] and result["R2"] and not result["R3"]
    assert result["E9"]["status"] == "unresolved"
    assert result["budget"]["total_reserved_variant_invocations"] == 12 + 16 + 4 + 12


def test_worst_case_eight_operations_needs_exactly_36_attempts(tmp_path):
    state = start(tmp_path, 8)
    attempts = 0
    while state.propose()["phase"] == "deletion":
        request = state.propose()
        active = state.snapshot()["retained_operation_ids"]
        # Every scan fails until its last operation; the singleton also fails.
        outcome = "pass" if len(active) > 1 and request["removed_operation_id"] == active[-1] else "fail"
        record(state, tmp_path / f"delete{attempts}", outcome)
        attempts += 1
    assert attempts == 36
    record(state, tmp_path / "final")
    result = state.snapshot()
    assert result["one_minimal"] and result["retained_operation_ids"] == ["op0"]
    assert not result["global_minimality_claimed"]
    assert result["budget"]["total_reserved_variant_invocations"] == 184


@pytest.mark.parametrize("outcome,status", [("unresolved", "unresolved"), ("fail", "one_minimal")])
def test_unknown_is_retained_and_never_establishes_one_minimality(tmp_path, outcome, status):
    state = start(tmp_path, 1)
    record(state, tmp_path / "deletion", outcome)
    record(state, tmp_path / "final")
    result = state.snapshot()
    assert result["minimality_status"] == status
    assert result["one_minimal"] == (outcome == "fail")
    assert result["retained_operation_ids"] == ["op0"]
    assert result["records"][0]["outcome"] == outcome


def test_budget_truncation_is_separate_from_success_and_minimality(tmp_path):
    state = start(tmp_path, 3, limit=1)
    record(state, tmp_path / "deletion")
    assert state.propose()["phase"] == "final_confirmation"
    record(state, tmp_path / "final", oracle="pass")
    result = state.snapshot()
    assert result["minimality_status"] == "budget_truncated"
    assert result["R2"] and result["R3"] and not result["one_minimal"]
    assert result["deletion_attempts"] == 1


@pytest.mark.parametrize("options", [
    {"outcome": "unresolved"}, {"outcome": "fail"}, {"missing_checks": ("E7",)},
    {"missing_checks": ("E8",), "returncode": 0},
    {"invariant": "target_input_values_preserved"}, {"invariant": "instrumentation_noninterference"},
    {"runtime_status": "timeout"},
])
def test_no_qualified_initial_witness_refuses_start(tmp_path, options):
    with pytest.raises(ValueError, match="initial_stable_strict_context_witness_not_established"):
        start(tmp_path, initial_options=options)


def test_nonzero_exit_does_not_prevent_reviewed_contrast_and_unknown_oracle(tmp_path):
    state = start(tmp_path, 1, initial_options={"returncode": 1, "missing_checks": ("E9",)})
    result = finish_without_deletions(state, tmp_path)
    assert result["R2"] and not result["R3"]
    assert result["initial_witness"]["E9"]["status"] == "unresolved"


def test_timeout_retains_unknown_despite_pass_checklist(tmp_path):
    state = start(tmp_path, 1)
    record(state, tmp_path / "timeout", runtime_status="timeout")
    assert state.snapshot()["records"][0]["outcome"] == "unresolved"
    assert state.snapshot()["retained_operation_ids"] == ["op0"]


def test_unknown_noninterference_is_not_overridden_by_a_failure_vote(tmp_path):
    state = start(tmp_path, 1)
    record(state, tmp_path / "uncertain", outcome="fail", invariant="instrumentation_noninterference")
    record(state, tmp_path / "final")
    assert state.snapshot()["minimality_status"] == "unresolved"


@pytest.mark.parametrize("outcome", ["fail", "unresolved"])
def test_final_confirmation_failure_never_claims_success(tmp_path, outcome):
    state = start(tmp_path, 1, limit=0)
    record(state, tmp_path / "final", outcome)
    result = state.snapshot()
    assert not result["R2"] and not result["R3"] and not result["one_minimal"]
    assert result["initial_witness"]["outcome"] == "pass"


def test_receipt_tampering_and_wrong_request_are_rejected_without_advancing(tmp_path):
    state = start(tmp_path, 1)
    request = state.propose()
    receipt = evidence(tmp_path / "attempt", request)
    body = json.loads(Path(receipt["path"]).read_text())
    Path(body["checks"]["E7"]["evidence"][0]["path"]).write_text("tampered")
    with pytest.raises(ValueError, match="artifact_receipt_mismatch"):
        state.record_result(receipt)
    assert state.propose() == request and not state.snapshot()["records"]
    changed = copy.deepcopy(request)
    changed["removed_operation_id"] = "invented"
    wrong = evidence(tmp_path / "wrong", changed)
    with pytest.raises(ValueError, match="bind_exact_request"):
        state.record_result(wrong)


def test_same_execution_cannot_be_reused_for_final_clean_reconfirmation(tmp_path):
    state = start(tmp_path, 1, limit=0)
    request = state.propose()
    receipt = evidence(tmp_path / "final", request)
    body = json.loads(Path(receipt["path"]).read_text())
    body["runs"][1] = body["runs"][0]
    receipt = artifact(Path(receipt["path"]), body)
    with pytest.raises(ValueError, match="reused_across_clean_repetitions"):
        state.record_result(receipt)


def test_extra_unaccounted_executions_are_not_hidden_inside_a_summary(tmp_path):
    state = start(tmp_path, 1)
    request = state.propose()
    receipt = evidence(tmp_path / "extra", request, batches=[2])
    body = json.loads(Path(receipt["path"]).read_text())
    body["runs"] = body["runs"][:1]
    receipt = artifact(Path(receipt["path"]), body)
    with pytest.raises(ValueError, match="unaccounted_pair_repetitions"):
        state.record_result(receipt)


def test_final_confirmation_is_bound_to_the_final_candidate(tmp_path):
    state = start(tmp_path, 2)
    record(state, tmp_path / "accepted")
    record(state, tmp_path / "empty", "fail")
    request = state.propose()
    assert request["retained_operation_ids"] == ["op1"]
    receipt = evidence(tmp_path / "final", request)
    body = json.loads(Path(receipt["path"]).read_text())
    pair_receipt = body["runs"][0]["pair_receipt"]
    pair = json.loads(Path(pair_receipt["path"]).read_text())
    pair["binding"]["candidate_sha256"] = "f" * 64
    pair_receipt = artifact(Path(pair_receipt["path"]), pair)
    for run in body["runs"]:
        run["pair_receipt"] = pair_receipt
    receipt = artifact(Path(receipt["path"]), body)
    with pytest.raises(ValueError, match="execution_pair_binding_mismatch"):
        state.record_result(receipt)
    assert not state.snapshot()["final_witness_confirmed"]


def test_baseline_qualification_loss_does_not_certify_a_negative_deletion(tmp_path):
    state = start(tmp_path, 1)
    receipt = evidence(tmp_path / "lost_baseline", state.propose(), outcome="fail")
    body = json.loads(Path(receipt["path"]).read_text())
    body["checks"]["E3"]["status"] = "fail"
    state.record_result(artifact(Path(receipt["path"]), body))
    record(state, tmp_path / "final")
    assert state.snapshot()["minimality_status"] == "unresolved"


def test_only_three_initial_runs_cannot_start_a_scheduler(tmp_path):
    files, candidate, binding = inputs(1)
    request = minimization.initial_request(candidate, binding)
    initial = evidence(tmp_path / "insufficient", request, batches=[3])
    with pytest.raises(ValueError, match="exact_clean_repeat_count"):
        minimization.DeletionMinimizer(files, candidate,
            validation_context={"editable_paths": list(files), "available_evidence_refs": ["synthetic-source"]},
            execution_binding=binding, initial_evidence=initial, budget=budget())


def test_one_atomic_operation_removes_all_and_only_its_original_edit_indices(tmp_path):
    files, candidate, binding = inputs(3)
    candidate["operation_groups"][0]["operations"] = [
        {"id": "two-edits", "description": "one synthetic semantic operation", "edit_indices": [0, 2]},
        {"id": "middle", "description": "another synthetic operation", "edit_indices": [1]}]
    binding["candidate_sha256"] = minimization._sha(candidate)
    initial = evidence(tmp_path / "initial", minimization.initial_request(candidate, binding))
    state = minimization.DeletionMinimizer(files, candidate,
        validation_context={"editable_paths": list(files), "available_evidence_refs": ["synthetic-source"]},
        execution_binding=binding, initial_evidence=initial, budget=budget())
    request = state.propose()
    assert request["original_edit_indices"] == [1]
    assert request["candidate"]["edits"] == [candidate["edits"][1]]


def test_snapshot_and_proposal_are_detached_and_not_execution_authorizations(tmp_path):
    state = start(tmp_path, 2)
    request = state.propose()
    request["candidate"]["edits"][0]["new"] = "rewritten"
    result = state.snapshot()
    result["original_candidate"]["edits"].clear()
    assert state.propose()["candidate"]["edits"][0]["new"] != "rewritten"
    assert len(state.snapshot()["original_candidate"]["edits"]) == 2
    assert not state.propose()["execution_authorization"]
    assert not state.snapshot()["executed_by_scheduler"]


def test_shared_budget_five_slots_and_registered_phase_caps(tmp_path):
    shared = budget()
    for rank in range(1, 6):
        state = start(tmp_path / str(rank), 1, rank=rank, shared=shared, limit=0)
        record(state, tmp_path / str(rank) / "final")
    snapshot = shared.snapshot()
    assert snapshot["total_reserved_variant_invocations"] == 152
    assert snapshot["registered_candidate_ranks"] == [1, 2, 3, 4, 5]
    with pytest.raises(ValueError, match="duplicate_or_outside"):
        start(tmp_path / "duplicate", 1, shared=shared)
    changed = dict(minimization.PHASE_CAPS)
    changed["total_subject_test_run_cap"] += 1
    with pytest.raises(ValueError, match="explicit_amendment"):
        minimization.MethodRepeatBudget({"pilot4": {"execution_budget_per_method_repeat": changed}})


@pytest.mark.parametrize("mutation", ["chained", "overlap", "nine_operations", "shared_edit"])
def test_invalid_original_operation_contract_is_rejected(tmp_path, mutation):
    files, candidate, binding = inputs(9 if mutation == "nine_operations" else 2)
    if mutation == "chained":
        candidate["edits"][1]["old"] = candidate["edits"][0]["new"]
    elif mutation == "overlap":
        candidate["edits"][1]["old"] = "setup_0"
    elif mutation == "shared_edit":
        candidate["operation_groups"][0]["operations"][1]["edit_indices"] = [0]
    binding["candidate_sha256"] = minimization._sha(candidate)
    initial = evidence(tmp_path / "initial", minimization.initial_request(candidate, binding))
    with pytest.raises(ValueError):
        minimization.DeletionMinimizer(files, candidate,
            validation_context={"editable_paths": list(files), "available_evidence_refs": ["synthetic-source"]},
            execution_binding=binding, initial_evidence=initial, budget=budget())
