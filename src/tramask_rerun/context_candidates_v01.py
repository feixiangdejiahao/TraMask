"""Prepare HF012's frozen context slots, then explicitly execute a reviewed slot.

Preparation is read-only and has no provider or subject calls. The sole execution
entry point runs one four-variant base comparison in a fixed output directory.
Additional confirmation, deletion minimization and semantic judgment are separate
steps. A structural preservation claim is never an E7 decision.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from . import continuation_dispatch_v01 as dispatch
from . import paired, provider_continuation_v01 as provider, transport_adapter, variants


def _read(receipt):
    return json.loads(provider.read_receipt(receipt))


def _receipt(path):
    receipt = dispatch._receipt(Path(path))
    provider.read_receipt(receipt)
    return receipt


def _response_binding(manifest, result, directory):
    """Bind completion bytes to the response digest in the frozen manifest.

    The provider may mark missing JSON closures as a parsing error. A complete stop
    response may still pass the separately frozen transport recovery; a token-
    truncated response cannot. This checks transport facts, not candidate merit.
    """
    response = directory / "provider/response.body"
    completion = directory / "provider/completion.txt"
    if not response.is_file():
        if completion.exists() or manifest.get("status") == "complete":
            raise ValueError("completion_missing_its_bound_raw_response")
        return False, []
    receipt = _receipt(response)
    if receipt["sha256"] != manifest.get("response_sha256"):
        raise ValueError("raw_provider_response_digest_mismatch")
    receipts = [receipt]
    try:
        raw = _read(receipt)
        choice = raw["choices"][0]
        content = choice["message"]["content"]
    except (ValueError, TypeError, KeyError, IndexError):
        if completion.exists():
            raise ValueError("completion_without_bound_response_content")
        return False, receipts
    if completion.exists():
        cr = _receipt(completion)
        if not isinstance(content, str) or provider.read_receipt(cr) != content.encode("utf-8"):
            raise ValueError("completion_differs_from_bound_raw_response")
        receipts.append(cr)
    else:
        return False, receipts
    complete = (type(manifest.get("http_status")) is int and 200 <= manifest["http_status"] < 300
        and manifest.get("finish_reason") == choice.get("finish_reason") == "stop"
        and type(manifest.get("external_model_calls")) is int
        and type(result.get("physical_model_calls")) is int
        and manifest.get("external_model_calls") == result.get("physical_model_calls") == 1
        and manifest.get("status") == result.get("provider_status"))
    return complete, receipts


def _canonical_slots(row, request, directory):
    """Recompute the frozen dispatcher's transport conversion from raw output."""
    raw = directory / "provider/completion.txt"
    receipts = []
    if raw.is_file():
        receipts.append(_receipt(raw))
    try:
        proposal = transport_adapter.recover_json(raw.read_text())["value"]
        sources, tests = dispatch._candidate_sources(row, request)
        canonical = proposal
        if isinstance(proposal, dict) and isinstance(proposal.get("candidates"), list):
            canonical = {**proposal, "candidates": []}
            for candidate in proposal["candidates"]:
                try:
                    adapted = transport_adapter.canonicalize_paths(
                        {"candidates": [candidate]}, sources, tests)
                    canonical["candidates"].append(adapted["proposal"]["candidates"][0])
                except (ValueError, TypeError, KeyError):
                    canonical["candidates"].append(candidate)
        stored = directory / "canonical_candidates.json"
        if not stored.is_file() or _read(_receipt(stored)) != canonical:
            raise RuntimeError("canonical_response_differs_from_raw_provider_output")
        receipts.append(_receipt(stored))
        context = {**request["validation_context"], "source_files": {**sources, **tests}}
        slots = variants.validate_candidate_response(canonical, context)
    except (ValueError, TypeError, KeyError, OSError, StopIteration):
        slots = variants.validate_candidate_response(None, request.get("validation_context", {}))
    stored = directory / "candidate_slots.json"
    if not stored.is_file() or _read(_receipt(stored)) != slots:
        raise ValueError("registered_slots_differ_from_raw_provider_output")
    receipts.append(_receipt(stored))
    return slots, receipts


def _material(row, request):
    receipt = row["construction_provenance_only"]["measurement_inputs"]
    inputs = _read(receipt)
    # This adapter deliberately covers the enrolled Python case. Generated
    # executables require a separately frozen build/executable qualification.
    if (inputs["case"]["id"] != "HF012" or inputs["case"]["language"] != "python"
            or inputs["generated_runtime"] or inputs["build_commands"]):
        raise ValueError("adapter_requires_frozen_HF012_interpreted_pair")
    dispatch._verify_tree(inputs["bound_artifacts"])
    dispatch._verify_tree(inputs["case"]["checkpoint"])
    material = json.loads(request["prompt"])["material"]
    selected, hypothesis = material["selected_test"], inputs["hypothesis"]
    if (material["target"] != hypothesis["target"]
            or material["alternative"]["edits"] != hypothesis["alternative"]["edits"]
            or material["alternative"]["kind"] != hypothesis["alternative"]["kind"]
            or selected["command"] != hypothesis["original_command"]
            or request["validation_context"]["original_command"] != selected["command"]
            or set(selected["files"]) != set(inputs["test_paths"])
            or any(inputs["source_files"].get(p) != t for p, t in selected["files"].items())):
        raise ValueError("fixed_target_Q_test_or_command_changed")
    return inputs, receipt


def prepare(preflight_receipt, freeze_receipt, queue_ordinal, *, dispatch_report_receipt=None):
    """Keep all five slots; absent provider work is missing, never five failures.

    A completed response must be named by an immutable dispatch report. Exact
    raw output is re-parsed and compared with the saved canonical slots. The
    returned plan includes all inputs needed to review a base execution binding.
    """
    context = dispatch.inspect_queue(preflight_receipt, freeze_receipt)
    if type(queue_ordinal) is not int:
        raise ValueError("integer_queue_ordinal_required")
    row = next((r for r in context["preflight"]["requests"]
                if r["queue_ordinal"] == queue_ordinal), None)
    if row is None or row["category"] != "HF012_context_track_a":
        raise ValueError("enrolled_HF012_context_cell_required")
    request = _read(row["prepared_request"])
    inputs, measurement_receipt = _material(row, request)
    directory = context["output_root"] / f"{queue_ordinal:03d}"
    plan = {"schema": "tramask.context-candidate-plan.v1", "case_id": "HF012",
        "condition": row["condition"], "physical_repeat": row["repeat"],
        "queue_ordinal": queue_ordinal, "registered_candidate_slots": 5,
        "preflight": preflight_receipt, "freeze": freeze_receipt,
        "prepared_request": row["prepared_request"], "measurement_inputs": measurement_receipt,
        "dispatch_report": dispatch_report_receipt, "input_receipts": [],
        "shared_track_a_methods": {"C2": ["M3"], "C3": ["M4"]}.get(row["condition"], []),
        "shared_methods_extra_model_calls": 0, "shared_methods_extra_subject_calls": 0,
        "base_subject_run_cap": 20, "base_repeats_per_candidate": 1,
        "scientific_label": None, "executed": False, "slots": [],
        "inputs": inputs}
    if dispatch_report_receipt is None:
        plan.update(status="provider_result_not_supplied", slots=[
            {"rank": rank, "status": "not_executed", "scientific_label": None}
            for rank in range(1, 6)])
        return plan
    report = _read(dispatch_report_receipt)
    if (report.get("schema") != "tramask.continuation-dispatch.v1"
            or report["binding"]["preflight"] != preflight_receipt
            or report["binding"]["freeze"] != freeze_receipt
            or report["binding"]["output_root"] != str(context["output_root"])):
        raise ValueError("dispatch_report_queue_binding_mismatch")
    records = [r for r in report["requests"] if r["queue_ordinal"] == queue_ordinal]
    if len(records) != 1 or "result" not in records[0]:
        raise ValueError("dispatch_report_does_not_bind_completed_cell")
    result_receipt = records[0]["result"]
    if result_receipt["path"] != str(directory / "result.json"):
        raise ValueError("dispatch_result_outside_fixed_cell")
    result = _read(result_receipt)
    manifest = _read(result["provider_manifest"])
    attempt_receipt = _receipt(directory / "attempt.json")
    attempt = _read(attempt_receipt)
    if (result["provider_manifest"]["path"] != str(directory / "provider/manifest.json")
            or manifest["request_sha256"] != row["provider_request_sha256"]
            or attempt["provider_request_sha256"] != row["provider_request_sha256"]
            or attempt["queue_ordinal"] != queue_ordinal
            or attempt["request"] != row["prepared_request"]
            or attempt["preflight"] != preflight_receipt or attempt["freeze"] != freeze_receipt
            or (directory / "prepared_request.json").read_bytes() != provider.read_receipt(row["prepared_request"])):
        raise ValueError("provider_result_request_binding_mismatch")
    completed, response_receipts = _response_binding(manifest, result, directory)
    slots, receipts = _canonical_slots(row, request, directory)
    plan["input_receipts"] = [result_receipt, result["provider_manifest"], attempt_receipt,
                              *response_receipts, *receipts]
    plan["status"] = "slots_prepared_pending_execution_review" if completed else "provider_incomplete_no_execution"
    for slot in slots["slots"]:
        entry = copy.deepcopy(slot)
        entry.update(scientific_label=None, execution_eligible=False)
        if completed and slot["status"] == "proposed" and slot["structural_valid"]:
            candidate = slot["normalized_candidate"]
            kwargs = {k: inputs[k] for k in ("source_origins", "test_paths", "build_commands",
                                           "generated_runtime", "observation_paths")}
            binding = paired.execution_binding(inputs["case"], inputs["source_files"], inputs["hypothesis"],
                candidate=candidate, repeats=1, **kwargs)
            entry.update(execution_eligible=True, execution_binding=binding,
                execution_output=str(directory / "context_execution_v01" / f"rank_{slot['rank']:02d}" / "base"))
        plan["slots"].append(entry)
    return plan


def execute_base(plan, rank, review):
    """Explicit subject execution; no new provider requests or inferred labels.

    Reconstruct the plan immediately before executing. Output is fixed by queue
    ordinal and rank, so changing the destination cannot create hidden retries.
    The paired backend only reuses complete, receipt-verified artifacts and
    rejects partial or changed bindings.
    """
    if type(rank) is not int or not 1 <= rank <= 5:
        raise ValueError("registered_rank_required")
    fresh = prepare(plan["preflight"], plan["freeze"], plan["queue_ordinal"],
                    dispatch_report_receipt=plan["dispatch_report"])
    if fresh != plan:
        raise ValueError("candidate_plan_changed")
    slot = plan["slots"][rank - 1]
    if not slot.get("execution_eligible"):
        raise ValueError("slot_not_eligible_for_execution")
    paired._review(review, slot["execution_binding"])
    inputs = plan["inputs"]
    kwargs = {k: inputs[k] for k in ("source_origins", "test_paths", "build_commands",
                                   "generated_runtime", "observation_paths")}
    return paired.execute_candidate_pair(inputs["case"], inputs["source_files"], inputs["hypothesis"],
        slot["normalized_candidate"], slot["execution_output"], review=review, repeats=1, **kwargs)
