"""Receipt-bound Track B direct candidates from the frozen continuation queue.

``prepare(preflight, freeze, reports, materials)`` is read-only. ``reports`` are
receipts of actual continuation dispatch reports, not directories to discover.
Missing outputs retain five pending slots. Invalid/abstaining slots are kept.
Only ``execute_preparation(receipt, execute=True)`` or CLI ``--execute`` runs
subjects; there is no provider call, retry, label, or inferred PASS here.

Materials JSON schema ``tramask.continuation-direct-materials.v1`` contains
``preflight``, ``freeze``, ``protocol`` receipts and ``cells``. Each cell binds
``queue_ordinal``, ``stage1_result``, ``planning``, ``public_input``, ``inventory``,
``checkpoint_proof``, ``terminal_exports`` (receipt list), ``environment``,
``old_baselines`` (receipt list), and ``cost_snapshot``. A cost snapshot has
``case_id``, ``method``, ``repeat``, ``protocol``, ``prior_by_phase`` (all five
protocol phase keys, nonnegative counts), and ``evidence`` (receipt list).
Zero prior counts are an explicit declaration; nonzero counts need evidence.
Optional ``runner_policy`` is an explicit receipt following track_b_targets'
shared policy contract, additionally binding ``case_id`` and ``test_id``.
Go commands must already have -count=1 or bind the Go bypass policy.

Three clean clones per P/original and P/candidate are attempted. The first
pair is charged to candidate screening, the other two to confirmation. Builds
are separately counted, with fresh executable receipt gates before testing.
Output locations are fixed by queue ordinal and rank; complete and partial
attempts are never rerun, including with another preparation filename.

CLI receipt arguments name files containing {path, bytes, sha256}. Default
prints preparation JSON without writing. ``--write-plan`` explicitly freezes a
new preparation document, selected by --rank and --queue-ordinal; ``--execute``
needs --preparation-receipt. Q staging is separate, after output freezing.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re

from tramask_pilot.fidelity import test_evidence
from tramask_pilot.submission_replay import ENV
from . import continuation_dispatch_v01 as dispatch
from . import cache_qualification, paired, runtime, track_b_targets, transport_adapter, variants
from .validation_material import _checkpoint, _digest, _read, load_validation_material, plan_validation


ARMS = ("p_original", "p_candidate")
PHASES = ("target_qualification_runs", "five_candidate_four_variant_runs",
          "success_three_repeat_runs", "minimization_eight_operations_worst_36_deletion_attempts_runs",
          "final_three_repeat_runs")
REGISTERED_CAPS = dict(zip(PHASES, (12, 20, 60, 720, 60))) | {"total_subject_test_run_cap": 872}


def _receipt(path):
    return paired._receipt(paired._output(path))


def _read_path(path, receipts):
    bound = _receipt(path)
    receipts.append(bound)
    return _read(bound)


def _implementation():
    return [_receipt(path) for path in (Path(__file__), Path(dispatch.__file__),
        Path(runtime.__file__), Path(paired.__file__), Path(track_b_targets.__file__),
        Path(cache_qualification.__file__), Path(variants.__file__), Path(transport_adapter.__file__),
        Path(__file__).with_name("validation_material.py"), Path(__file__).with_name("evidence.py"))]


def _pending_slots():
    return [{"rank": rank, "status": "pending_output", "structural_valid": False,
             "candidate": None, "scientific_label": None} for rank in range(1, 6)]


def compose_qualified_checkpoint_proof(active_state_receipt):
    """Pure adapter for an already recorded initialized-gitlink qualification.

    The historical replay summary remains unchanged. Return a separate proof
    object to freeze explicitly before using its receipt as checkpoint_proof.
    This reproduces the existing qualification checks; it runs no subject and
    adds no scientific verdict. All raw source receipts remain referenced.
    """
    active = _read(active_state_receipt)
    summary, qualification = _read(active["summary"]), _read(active["validation"])
    checkpoint = _checkpoint(active)
    if (active.get("state_validation_passed") is not True
            or qualification.get("case_id") != "HS005"
            or _checkpoint(summary["checkpoint"]) != checkpoint
            or _checkpoint(qualification["checkpoint"]) != checkpoint
            or qualification.get("submission_filesystem_state_status") != "matched_with_initialized_gitlink_qualification"
            or qualification.get("subject_files_or_real_index_patched") is not False
            or qualification.get("subject_commands_replayed_again") is not False):
        raise ValueError("existing_initialized_gitlink_qualification_required")
    previous_receipt = qualification["previous_validation"]
    if previous_receipt != summary["validation_receipt"]:
        raise ValueError("qualification_original_validation_binding_changed")
    previous = _read(previous_receipt)
    unverified = previous.get("unverified", [])
    if (previous.get("mismatches") or len(unverified) != 1
            or unverified[0].get("path") != "site/themes/hello-friend"
            or unverified[0].get("reason") != "submodule_worktree_not_validated"
            or unverified[0].get("expected", {}).get("oid") != qualification["expected_gitlink_commit"]
            or previous.get("submitted_commit_tree_matches") is not True
            or previous.get("index_tree_matches_submitted_commit") is not True
            or previous.get("matched_existing_files") != qualification["all_regular_tracked_files_matched_previously"]):
        raise ValueError("unresolved_original_checkpoint_validation")
    snapshots = qualification["snapshots"]
    if set(snapshots) != {"initial", "terminal"} or snapshots["initial"]["tree"] != snapshots["terminal"]["tree"]:
        raise ValueError("qualified_gitlink_trees_differ")
    raw = {Path(b["path"]).name: b for b in qualification["raw_receipts"]}
    if set(raw) != {"initial.stdout.bin", "initial.stderr.bin", "terminal.stdout.bin", "terminal.stderr.bin"}:
        raise ValueError("complete_gitlink_raw_receipts_required")
    for name, snapshot in snapshots.items():
        if (any(snapshot[k]["returncode"] != 0 for k in ("head", "index", "head_tree", "status"))
                or snapshot["head"]["stdout"].strip() != qualification["expected_gitlink_commit"]
                or snapshot["index"]["stdout"] != snapshot["head_tree"]["stdout"]
                or snapshot["status"]["stdout"] != ""
                or json.loads(_read(raw[name + ".stdout.bin"], json_value=False)) != snapshot):
            raise ValueError("gitlink_qualification_snapshot_mismatch")
        _read(raw[name + ".stderr.bin"], json_value=False)
    inventory = _read(summary["inventory"])
    if inventory.get("errors"):
        raise ValueError("incomplete_checkpoint_filesystem_inventory")
    return {"schema": "tramask.qualified-checkpoint-proof-composition.v1",
            "state_validation_passed": True, "checkpoint": checkpoint, "inventory": summary["inventory"],
            "active_state_receipt": active_state_receipt, "original_replay_summary": active["summary"],
            "existing_qualification": active["validation"], "previous_validation": previous_receipt,
            "raw_receipts": qualification["raw_receipts"], "new_subject_executions": 0,
            "historical_records_overwritten": False, "scientific_label": None}


def _actual_slots(row, result_receipt, context, report_binding):
    """Recheck raw provider bytes through exactly the frozen parsing policy."""
    directory = context["output_root"] / f'{row["queue_ordinal"]:03d}'
    if Path(result_receipt["path"]) != directory / "result.json":
        raise ValueError("continuation_result_outside_registered_ordinal")
    receipts = [result_receipt]
    result = _read(result_receipt)
    attempt = _read_path(directory / "attempt.json", receipts)
    expected = {**report_binding, "queue_ordinal": row["queue_ordinal"],
                "request": row["prepared_request"], "provider_request_sha256": row["provider_request_sha256"]}
    if attempt != expected:
        raise ValueError("continuation_attempt_binding_changed")
    request_receipt = _receipt(directory / "prepared_request.json")
    receipts.append(request_receipt)
    if _read(request_receipt, json_value=False) != _read(row["prepared_request"], json_value=False):
        raise ValueError("continuation_request_bytes_changed")
    request = _read(request_receipt)
    manifest_receipt = _receipt(directory / "provider/manifest.json")
    if result.get("provider_manifest") != manifest_receipt:
        raise ValueError("continuation_provider_manifest_binding_changed")
    receipts.append(manifest_receipt)
    manifest = _read(manifest_receipt)
    http_status = manifest.get("http_status")
    execution_eligible = (manifest.get("external_model_calls") == 1
        and type(http_status) is int and 200 <= http_status < 300 and manifest.get("finish_reason") == "stop")
    if (manifest.get("request_sha256") != row["provider_request_sha256"]
            or result.get("physical_model_calls") != manifest.get("external_model_calls")
            or result.get("provider_status") != manifest.get("status")):
        raise ValueError("continuation_provider_identity_changed")
    recorded = _read_path(directory / "candidate_slots.json", receipts)
    if result.get("status") != "candidates_pending_execution_and_semantic_review":
        if any(s.get("status") == "proposed" for s in recorded.get("slots", [])):
            raise ValueError("unavailable_output_cannot_propose_candidates")
        expected_slots = variants.validate_candidate_response(None, request.get("validation_context", {}))
    else:
        if manifest.get("external_model_calls") != 1:
            raise ValueError("candidate_requires_actual_single_provider_output")
        raw_receipt = _receipt(directory / "provider/response.body")
        receipts.append(raw_receipt)
        if raw_receipt["sha256"] != manifest.get("response_sha256"):
            raise ValueError("provider_raw_response_binding_changed")
        response = _read(raw_receipt)
        if response["choices"][0].get("finish_reason") != manifest.get("finish_reason"):
            raise ValueError("provider_finish_reason_binding_changed")
        completion_receipt = _receipt(directory / "provider/completion.txt")
        receipts.append(completion_receipt)
        raw = _read(completion_receipt, json_value=False).decode()
        if response["choices"][0]["message"]["content"] != raw:
            raise ValueError("completion_differs_from_provider_response")
        decoded = transport_adapter.recover_json(raw)
        if (_read_path(directory / "decoded_response.json", receipts) != decoded["value"]
                or _read_path(directory / "transport_recovery.json", receipts) != decoded["receipt"]):
            raise ValueError("frozen_transport_recovery_changed")
        sources, tests = dispatch._candidate_sources(row, request)
        proposal, adaptations = decoded["value"], []
        canonical = proposal
        if isinstance(proposal, dict) and isinstance(proposal.get("candidates"), list):
            canonical = {**proposal, "candidates": []}
            for candidate in proposal["candidates"]:
                try:
                    adapted = transport_adapter.canonicalize_paths({"candidates": [candidate]}, sources, tests)
                    canonical["candidates"].append(adapted["proposal"]["candidates"][0])
                    adaptations.append(adapted["receipt"])
                except (ValueError, TypeError, KeyError) as error:
                    canonical["candidates"].append(candidate)
                    adaptations.append({"error": str(error), "raw_slot_retained": True})
        if (_read_path(directory / "canonical_candidates.json", receipts) != canonical
                or _read_path(directory / "path_adaptation.json", receipts) != adaptations):
            raise ValueError("canonical_model_output_changed")
        expected_slots = variants.validate_candidate_response(canonical,
            {**request["validation_context"], "source_files": {**sources, **tests}})
    if recorded != expected_slots or [s["rank"] for s in recorded["slots"]] != list(range(1, 6)):
        raise ValueError("frozen_five_slots_changed")
    return recorded["slots"], receipts, execution_eligible


def inspect_continuation(preflight_receipt, freeze_receipt, continuation_receipts=()):
    """Read only explicitly receipt-bound reports; return all 36 direct cells."""
    context = dispatch.inspect_queue(preflight_receipt, freeze_receipt)
    results = {}
    report_artifacts = []
    for bound in continuation_receipts:
        report = _read(bound)
        binding = report.get("binding", {})
        if (report.get("schema") != "tramask.continuation-dispatch.v1"
                or binding.get("preflight") != preflight_receipt or binding.get("freeze") != freeze_receipt
                or binding.get("output_root") != str(context["output_root"])):
            raise ValueError("continuation_report_queue_binding_mismatch")
        queue_binding = _read_path(context["output_root"] / "queue_binding.json", report_artifacts)
        if queue_binding != binding:
            raise ValueError("continuation_queue_binding_changed")
        # This verifies bytes, not authorization for any new provider call.
        _read(binding["authorization"])
        report_artifacts.extend([bound, binding["authorization"]])
        for record in report["requests"]:
            if "result" not in record:
                continue
            ordinal = record["queue_ordinal"]
            value = (record["result"], binding)
            if ordinal in results and results[ordinal] != value:
                raise ValueError("conflicting_continuation_output_receipts")
            results[ordinal] = value
    cells = []
    for row in context["preflight"]["requests"]:
        if row["category"] != "track_b_stage2":
            continue
        original = _read(row["original_result"])
        cell = {"queue_ordinal": row["queue_ordinal"], "case_id": original["case_id"],
                "method": original["method"], "repeat": original["repeat"],
                "run_dir": str(context["run_dir"]),
                "original_refusal": row["original_result"], "prepared_request": row["prepared_request"],
                "status": "pending_actual_continuation_output", "slots": _pending_slots(),
                "output_receipts": [], "execution_eligible": False, "scientific_label": None}
        if row["queue_ordinal"] in results:
            receipt, binding = results[row["queue_ordinal"]]
            cell["slots"], cell["output_receipts"], cell["execution_eligible"] = _actual_slots(row, receipt, context, binding)
            cell["status"] = "actual_output_recorded"
            if not cell["execution_eligible"]:
                cell["preparation_error"] = "provider_requires_single_call_http2xx_finish_stop; raw_slots_retained"
        cells.append(cell)
    if len(cells) != 36 or len({(c["case_id"], c["method"], c["repeat"]) for c in cells}) != 36:
        raise ValueError("requires_36_unique_registered_direct_cells")
    return {"cells": cells, "output_root": str(context["output_root"]),
            "report_artifacts": report_artifacts, "subject_execution_performed": False}


def _material(cell, binding):
    original = _read(cell["original_refusal"])
    old_stage = Path(cell["original_refusal"]["path"]).parent
    directory = Path(cell["run_dir"]) / "runs" / cell["case_id"]
    expected_stage = directory / "track_b" / cell["method"] / f'repeat_{cell["repeat"]:02d}' / "stage_02"
    if old_stage != expected_stage:
        raise ValueError("original_direct_cell_path_mismatch")
    stage = old_stage.parent / "stage_01"
    first, planning = _read(binding["stage1_result"]), _read(binding["planning"])
    if (Path(binding["stage1_result"]["path"]) != stage / "result.json"
            or Path(binding["planning"]["path"]) != stage / "planning.json"
            or first.get("planning") != binding["planning"]
            or first.get("public_input") != binding["public_input"]
            or first.get("status") != "planning_qualified_for_next_generation"
            or any(first.get(key) != cell[key] for key in ("case_id", "method", "repeat"))):
        raise ValueError("original_stage1_selection_binding_mismatch")
    if _read(binding["public_input"], json_value=False) != _read(original["public_input"], json_value=False):
        raise ValueError("stage1_stage2_public_material_changed")
    request = _read(cell["prepared_request"])
    selected = json.loads(request["prompt"])["material"]["selected_test"]
    if selected["id"] != planning["selected_test_id"]:
        raise ValueError("prepared_request_stage1_test_selection_changed")
    if not binding.get("terminal_exports"):
        raise ValueError("explicit_terminal_export_receipts_required")
    proof = _read(binding["checkpoint_proof"])
    if proof.get("schema") == "tramask.qualified-checkpoint-proof-composition.v1":
        if proof != compose_qualified_checkpoint_proof(proof["active_state_receipt"]):
            raise ValueError("qualified_checkpoint_proof_composition_changed")
    material = load_validation_material(binding["public_input"], binding["inventory"],
        planning["selected_test_id"], checkpoint_proof_receipt=binding["checkpoint_proof"],
        terminal_export_receipts=binding["terminal_exports"])
    if planning["original_command"] != material["command"] or material["case_id"] != cell["case_id"]:
        raise ValueError("stage1_command_or_case_changed")
    if Path(binding["environment"]["path"]) != directory / "environment.json":
        raise ValueError("original_case_environment_receipt_required")
    environment = _read(binding["environment"])
    dispatch._verify_tree(environment)
    timeout = runtime._timeout(environment["test_timeout_seconds"])
    if not binding.get("old_baselines"):
        raise ValueError("original_baseline_receipts_required_even_when_failed")
    baselines = {directory / name / "summary.json" for name in ("baseline", "baseline_capsule", "baseline_uncached")
                 if (directory / name / "summary.json").is_file()}
    if (not baselines or {Path(b["path"]) for b in binding["old_baselines"]} != baselines):
        raise ValueError("all_original_case_baseline_receipts_required")
    for bound in binding["old_baselines"]:
        dispatch._verify_tree(_read(bound))
    return material, timeout, environment.get("resources", {})


def _budget(cell, binding, protocol_receipt, proposed):
    protocol, spent = _read(protocol_receipt), _read(binding["cost_snapshot"])
    caps = protocol["pilot4"]["execution_budget_per_method_repeat"]
    if Path(protocol_receipt["path"]) != Path(cell["run_dir"]) / "protocol.json" or caps != REGISTERED_CAPS:
        raise ValueError("original_registered_protocol_caps_required")
    if (spent.get("protocol") != protocol_receipt
            or any(spent.get(k) != cell[k] for k in ("case_id", "method", "repeat"))):
        raise ValueError("cell_cost_snapshot_binding_mismatch")
    prior = spent.get("prior_by_phase", {})
    if set(prior) != set(PHASES) or any(type(v) is not int or v < 0 for v in prior.values()):
        raise ValueError("explicit_nonnegative_prior_phase_costs_required")
    if sum(prior.values()) and not spent.get("evidence"):
        raise ValueError("prior_costs_require_evidence_receipts")
    for bound in spent.get("evidence", []):
        _read(bound, json_value=False)
    additions = {phase: 0 for phase in PHASES}
    additions[PHASES[1]], additions[PHASES[2]] = proposed * 2, proposed * 4
    if (proposed > 5 or any(prior[p] + additions[p] > caps[p] for p in PHASES)
            or sum(prior.values()) + proposed * 6 > caps["total_subject_test_run_cap"]):
        raise ValueError("registered_cell_execution_cap_exceeded")
    return {"protocol": protocol_receipt, "cost_snapshot": binding["cost_snapshot"],
            "prior_by_phase": prior, "maximum_new_by_phase": additions,
            "maximum_new_subject_runs": proposed * 6, "registered_caps": caps,
            "build_costs_counted_separately": True}


def _runner_arms(staged, binding, cell, material):
    policy_receipt = binding.get("runner_policy")
    policy = _read(policy_receipt) if policy_receipt else None
    if policy and (policy.get("case_id") != cell["case_id"] or policy.get("test_id") != material["test_id"]):
        raise ValueError("runner_policy_test_binding_mismatch")
    arms = copy.deepcopy(staged["arms"])
    for arm in arms.values():
        original = arm["command"]
        go = bool(re.search(r"\bgo\s+test\b", original))
        counts = re.findall(r"(?:^|\s)-count(?:=|\s+)([^\s;&|]+)", original)
        explicit_one = counts == ["1"]
        if go and counts and not explicit_one:
            raise ValueError("go_conflicting_or_nonunit_count_requires_review")
        if go and not explicit_one and (not policy or policy.get("kind") != "go_cache_bypass"):
            raise ValueError("go_requires_explicit_uncached_runner_policy")
        effective = track_b_targets._runner_command(original, policy)
        arm.update(proposed_command=original, command=effective,
                   runner_adaptation_applied=effective != original)
    return arms


def prepare(preflight_receipt, freeze_receipt, continuation_receipts, materials_receipt):
    """Pure preparation. No files, Docker, provider, baseline, or ledger writes."""
    inspected = inspect_continuation(preflight_receipt, freeze_receipt, continuation_receipts)
    materials = _read(materials_receipt)
    if (materials.get("schema") != "tramask.continuation-direct-materials.v1"
            or materials.get("preflight") != preflight_receipt or materials.get("freeze") != freeze_receipt):
        raise ValueError("explicit_material_queue_binding_required")
    bindings = {b["queue_ordinal"]: b for b in materials["cells"]}
    if len(bindings) != len(materials["cells"]) or not set(bindings) <= {c["queue_ordinal"] for c in inspected["cells"]}:
        raise ValueError("duplicate_or_unregistered_material_cell")
    arguments = {"preflight_receipt": preflight_receipt, "freeze_receipt": freeze_receipt,
                 "continuation_receipts": list(continuation_receipts), "materials_receipt": materials_receipt}
    implementation = _implementation()
    for cell in inspected["cells"]:
        if not cell["execution_eligible"]:
            continue
        eligible = [s for s in cell["slots"] if s["status"] == "proposed" and s["structural_valid"] is True]
        if not eligible:
            continue
        binding = bindings.get(cell["queue_ordinal"])
        if binding is None:
            cell["preparation_error"] = "explicit_material_binding_missing"
            continue
        try:
            material, timeout, resources = _material(cell, binding)
            budget = _budget(cell, binding, materials["protocol"], len(eligible))
        except (ValueError, KeyError, TypeError, OSError) as error:
            cell["preparation_error"] = str(error)
            continue
        for slot in eligible:
            try:
                staged = plan_validation(material, slot["candidate"])
                arms = _runner_arms(staged, binding, cell, material)
                output = Path(inspected["output_root"]) / f'{cell["queue_ordinal"]:03d}' / "candidate_execution_v01" / f'rank_{slot["rank"]:02d}'
                plan = {"schema": "tramask.continuation-direct-candidate.v1", "arguments": arguments,
                    "queue_ordinal": cell["queue_ordinal"], "case_id": cell["case_id"],
                    "method": cell["method"], "repeat": cell["repeat"], "rank": slot["rank"],
                    "candidate": slot["candidate"], "arms": arms, "checkpoint": material["checkpoint"],
                    "test_timeout_seconds": timeout, "resources": resources, "environment": copy.deepcopy(ENV),
                    "observation_paths": sorted({p for a in arms.values() for p in a["after_sha256"]}),
                    "repeats": 3, "subject_test_run_cap_this_candidate": 6, "budget": budget,
                    "output": str(output), "material_binding": binding, "material_authorities": material["authorities"],
                    "output_receipts": cell["output_receipts"], "implementation": implementation,
                    "old_baselines": binding["old_baselines"], "counterfactual_gate": False,
                    "fixed_q_receipt": None, "subject_execution_performed": False,
                    "scientific_label": None, "syntax_repaired": False}
                plan["plan_sha256"] = _digest(plan)
                slot["preparation"] = plan
            except (ValueError, KeyError, TypeError, OSError) as error:
                slot["preparation_error"] = str(error)
    return {"schema": "tramask.continuation-direct-preparation.v1", "arguments": arguments,
            "cells": inspected["cells"], "registered_cells": 36, "registered_slots": 180,
            "prepared_candidates": sum("preparation" in s for c in inspected["cells"] for s in c["slots"]),
            "subject_execution_performed": False, "scientific_label": None}


def _verify_plan(plan):
    value = copy.deepcopy(plan)
    digest = value.pop("plan_sha256", None)
    if digest != _digest(value) or plan.get("repeats") != 3 or set(plan.get("arms", {})) != set(ARMS):
        raise ValueError("direct_preparation_changed")
    fresh = prepare(**plan["arguments"])
    cell = next(c for c in fresh["cells"] if c["queue_ordinal"] == plan["queue_ordinal"])
    expected = cell["slots"][plan["rank"] - 1].get("preparation")
    if plan != expected:
        raise ValueError("direct_preparation_not_exact_frozen_candidate")


def write_preparation(plan, path):
    """Explicitly freeze one new candidate plan; preparation itself is pure."""
    _verify_plan(plan)
    paired._write(paired._output(path), plan)
    return _receipt(path)


def prepare_evaluator_q(plan, fixed_q_receipt):
    """Separate read-only evaluator staging after the direct output is frozen.

    Never feeds Q into direct preparation or execution. Caller must separately
    register and budget any future comparator execution; this API only stages.
    """
    _verify_plan(plan)
    cell = {k: plan[k] for k in ("case_id", "method", "repeat")}
    fresh = inspect_continuation(plan["arguments"]["preflight_receipt"],
        plan["arguments"]["freeze_receipt"], plan["arguments"]["continuation_receipts"])
    original = next(c for c in fresh["cells"] if c["queue_ordinal"] == plan["queue_ordinal"])
    material, _, _ = _material(original, plan["material_binding"])
    frozen = next(b for b in plan["output_receipts"] if Path(b["path"]).name == "canonical_candidates.json")
    staged = plan_validation(material, plan["candidate"], fixed_q_receipt=fixed_q_receipt, frozen_output_receipt=frozen)
    arms = _runner_arms(staged, plan["material_binding"], cell, material)
    return {"schema": "tramask.continuation-direct-evaluator-staging.v1",
            "direct_plan_sha256": plan["plan_sha256"], "frozen_output_receipt": frozen,
            "fixed_q_receipt": fixed_q_receipt, "arms": {k: arms[k] for k in ("q_original", "q_candidate")},
            "execution_authorized": False, "counterfactual_gate": False, "scientific_label": None}


def execute_preparation(preparation_receipt, *, execute=False):
    """Explicit bounded runtime. Existing output always fails before a run."""
    if execute is not True:
        raise ValueError("explicit_execute_true_required")
    plan = _read(preparation_receipt)
    _verify_plan(plan)
    out = paired._output(plan["output"])
    if out.exists():
        raise FileExistsError("candidate_output_exists_complete_or_partial_no_retry")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()  # Atomic rank claim also prevents racing/new-file retries.
    paired._write(out / "execution_binding.json", {"preparation": preparation_receipt,
        "plan_sha256": plan["plan_sha256"], "subject_test_run_cap": 6})
    records = []
    for repeat in range(1, 4):
        for name in ARMS:
            directory = out / f"repeat_{repeat:02d}" / name
            result = track_b_targets._execute_arm(plan, plan["arms"][name], directory)
            execution = result.get("execution") or {}
            facts = test_evidence(execution.get("stdout", "") + "\n" + execution.get("stderr", ""))
            artifacts = [_receipt(p) for p in sorted(directory.rglob("*")) if p.is_file()]
            record = {"repeat": repeat, "arm": name, "status": result.get("status"),
                "result": _receipt(directory / "result.json"), "raw_receipts": artifacts,
                "returncode": execution.get("returncode"), "timed_out": execution.get("timed_out"),
                "subject_run_attempted": result.get("execution") is not None,
                "subject_seconds": execution.get("elapsed_seconds"), "build_commands": len(result.get("builds", [])),
                "build_seconds": sum(x.get("elapsed_seconds", 0) or 0 for x in result.get("builds", [])),
                "runner_text_facts": facts, "scientific_label": None,
                "charged_phase": PHASES[1] if repeat == 1 else PHASES[2]}
            paired._write(directory / "candidate_record.json", record)
            records.append(record)
    summary = {"schema": "tramask.continuation-direct-execution.v1", "preparation": preparation_receipt,
        "queue_ordinal": plan["queue_ordinal"], "rank": plan["rank"], "runs": records,
        "reserved_subject_runs": 6, "subject_test_runs": sum(r["subject_run_attempted"] for r in records),
        "build_commands": sum(r["build_commands"] for r in records),
        "build_seconds": sum(r["build_seconds"] for r in records),
        "old_baselines": plan["old_baselines"], "counterfactual_gate": False, "scientific_label": None,
        "status": "executed_pending_independent_oracle_and_outcome_review"}
    paired._write(out / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-receipt")
    parser.add_argument("--freeze-receipt")
    parser.add_argument("--continuation-receipt", action="append", default=[])
    parser.add_argument("--materials-receipt")
    parser.add_argument("--write-plan")
    parser.add_argument("--preparation-receipt")
    parser.add_argument("--queue-ordinal", type=int)
    parser.add_argument("--rank", type=int, choices=range(1, 6))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    load = lambda p: json.loads(Path(p).read_text())
    if args.execute:
        if not args.preparation_receipt:
            parser.error("--execute requires --preparation-receipt")
        result = execute_preparation(load(args.preparation_receipt), execute=True)
    else:
        if not all((args.preflight_receipt, args.freeze_receipt, args.materials_receipt)):
            parser.error("preparation requires preflight, freeze, and materials receipts")
        result = prepare(load(args.preflight_receipt), load(args.freeze_receipt),
                         [load(p) for p in args.continuation_receipt], load(args.materials_receipt))
        if args.write_plan:
            if args.queue_ordinal is None or args.rank is None:
                parser.error("--write-plan requires --queue-ordinal and --rank")
            cell = next(c for c in result["cells"] if c["queue_ordinal"] == args.queue_ordinal)
            result = write_preparation(cell["slots"][args.rank - 1]["preparation"], args.write_plan)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
