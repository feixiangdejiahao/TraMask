"""Receipt-bound serial continuation; importing or the default CLI never dispatches.

CLI receipt arguments name JSON files containing {path, bytes, sha256} receipts.
Execution additionally requires --execute, --authorization-receipt and
--project-root. No authorization document, ledger cap or HF012 enrollment is
created here. A frozen amendment must bind preflight, implementation receipts,
baseline_ledger_snapshot, output_root, and HF012 enrollment/shared arms.

Budget authorization format is documented by provider_continuation_v01.
New output directories are keyed by frozen queue ordinal, not completion success.
Any existing attempt, including a partial attempt, is never dispatched again.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import uuid

from tramask_pilot import hypotheses
from . import provider_continuation_v01 as provider
from . import transport_adapter, variants


def _receipt(path):
    path = Path(path).absolute()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _read(receipt):
    return json.loads(provider.read_receipt(receipt))


def _write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _path(value):
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise ValueError("noncanonical_continuation_path")
    return path


def _verify_tree(value):
    if isinstance(value, dict):
        if {"path", "bytes", "sha256"} <= value.keys():
            provider.read_receipt(value)
        else:
            for row in value.values():
                _verify_tree(row)
    elif isinstance(value, list):
        for row in value:
            _verify_tree(row)


def _payload(request):
    payload = {"model": provider.MODEL, "temperature": 0, "max_tokens": request["max_tokens"],
        "messages": [{"role": "system", "content": request["system"]},
                     {"role": "user", "content": request["prompt"]}],
        "response_format": {"type": "json_object"}, "stream": False,
        "thinking": {"type": "disabled"}}
    raw = provider._encoded(payload)
    fingerprint = hashlib.sha256(provider._encoded({"id": request["id"], "payload": payload})).hexdigest()
    return raw, fingerprint


def inspect_queue(preflight_receipt, freeze_receipt):
    """Pure read-only verification, including requests, original refusals and code."""
    preflight, freeze = _read(preflight_receipt), _read(freeze_receipt)
    if (preflight.get("schema") != "tramask.continuation-budget-preflight.v02"
            or freeze.get("schema") != "tramask.continuation-freeze.v1"
            or freeze.get("status") != "frozen" or freeze.get("preflight") != preflight_receipt):
        raise ValueError("frozen_continuation_preflight_required")
    run = _path(preflight["ledger"]["path"]).parent
    output = _path(freeze["output_root"])
    if output.parent != run or not output.name.startswith("continuation_execution_"):
        raise ValueError("new_run_local_continuation_output_required")
    implementation = freeze.get("implementation", [])
    _verify_tree(implementation)
    required_code = {str(Path(p).absolute()) for p in
        (__file__, provider.__file__, transport_adapter.__file__, variants.__file__, hypotheses.__file__)}
    if not required_code <= {x["path"] for x in implementation}:
        raise ValueError("dispatcher_provider_and_response_code_must_be_frozen")
    _verify_tree(preflight["prompt_builder"]["code"])
    _verify_tree(preflight["provider_accounting"]["code"])
    _verify_tree(preflight["mechanical_construction_amendment"])
    snapshot_receipt = freeze.get("baseline_ledger_snapshot")
    snapshot = _read(snapshot_receipt)
    if any(snapshot_receipt[k] != preflight["ledger"][k] for k in ("bytes", "sha256")):
        raise ValueError("baseline_ledger_snapshot_mismatch")
    if snapshot["limit_tokens"] != provider.BUDGET_TOKENS:
        raise ValueError("baseline_budget_mismatch")
    enrollment = freeze.get("enrollments", {}).get("HF012", {})
    if (enrollment.get("status") != "enrolled"
            or enrollment.get("conditions") != ["C1", "C2", "C3", "C4", "M1", "M2"]
            or enrollment.get("shared_arms") != {"M3": "C2", "M4": "C3"}):
        raise ValueError("explicit_HF012_enrollment_amendment_required")
    rows = preflight["requests"]
    expected_counts = {"track_b_stage2": 36, "HS005_reference_completion": 1, "HF012_context_track_a": 12}
    if len(rows) != 49 or Counter(r["category"] for r in rows) != expected_counts:
        raise ValueError("frozen_49_request_queue_required")
    if [r["queue_ordinal"] for r in rows] != list(range(1, 50)):
        raise ValueError("frozen_queue_order_changed")
    request_ids, fingerprints, hf_cells = set(), set(), set()
    for row in rows:
        _verify_tree(row)
        request = _read(row["prepared_request"])
        if not row.get("dispatchable") or not request.get("dispatchable"):
            raise ValueError("non_dispatchable_request")
        raw, fingerprint = _payload(request)
        if (fingerprint != row["provider_request_sha256"]
                or raw != provider.read_receipt(row["provider_payload"])
                or len(raw) != row["serialized_payload_utf8_bytes"]
                or len(raw) + provider.WRAPPER_TOKENS + request["max_tokens"] != row["conservative_reservation_tokens"]):
            raise ValueError("prepared_provider_payload_or_reservation_changed")
        if request["id"] in request_ids or fingerprint in fingerprints:
            raise ValueError("duplicate_physical_request")
        request_ids.add(request["id"])
        fingerprints.add(fingerprint)
        if row["category"] != "HF012_context_track_a":
            original = _read(row["original_result"])
            manifest = _read(row["original_provider_manifest"])
            if (original.get("provider_status") != "budget_exceeded"
                    or original.get("physical_model_calls") != 0
                    or manifest.get("status") != "budget_exceeded"
                    or manifest.get("external_model_calls") != 0):
                raise ValueError("original_attempt_was_not_zero_call_budget_refusal")
            if (original["request"] != row["original_prepared_request"]
                    or original["provider_manifest"] != row["original_provider_manifest"]
                    or provider.read_receipt(row["original_prepared_request"]) != provider.read_receipt(row["prepared_request"])
                    or manifest["request_sha256"] != fingerprint):
                raise ValueError("original_request_binding_changed")
            if row["category"] == "track_b_stage2":
                # These direct methods require a qualified target, never a Q gate.
                if original.get("method") not in {"M1", "M2"} or original.get("stage") != 2:
                    raise ValueError("unregistered_stage2_method")
                _verify_tree(original["public_input"])
        else:
            hf_cells.add((row["condition"], row["repeat"]))
            if row["fixed_pair_sha256"] != preflight["HF012_provenance"]["fixed_pair_sha256"]:
                raise ValueError("HF012_pair_binding_changed")
    if hf_cells != {(c, n) for c in enrollment["conditions"] for n in (1, 2)}:
        raise ValueError("HF012_physical_cells_changed")
    if any(entry["request_sha256"] in fingerprints for entry in snapshot["calls"].values()):
        raise ValueError("request_already_charged_before_continuation")
    return {"preflight": preflight, "freeze": freeze, "baseline": snapshot,
            "run_dir": run, "output_root": output, "dispatch_authorized": False}


def _authorized_context(preflight_receipt, freeze_receipt, authorization_receipt):
    context = inspect_queue(preflight_receipt, freeze_receipt)
    auth = provider.validate_authorization(context["run_dir"], authorization_receipt)
    if auth["preflight"] != preflight_receipt or auth["freeze"] != freeze_receipt:
        raise ValueError("authorization_queue_binding_changed")
    ledger = json.loads((context["run_dir"] / "provider_budget.json").read_text())
    if ledger["limit_tokens"] != auth["authorized_total_token_limit"]:
        raise ValueError("authorized_ledger_limit_mismatch")
    for key, entry in context["baseline"]["calls"].items():
        if ledger["calls"].get(key) != entry:
            raise ValueError("baseline_ledger_entry_changed")
    expected = {hashlib.sha256(str(context["output_root"] / f'{r["queue_ordinal"]:03d}' / "provider").encode()).hexdigest():
                r["provider_request_sha256"] for r in context["preflight"]["requests"]}
    for key, entry in ledger["calls"].items():
        if key not in context["baseline"]["calls"] and expected.get(key) != entry["request_sha256"]:
            raise ValueError("unbound_continuation_ledger_attempt")
    context.update(authorization=auth, ledger=ledger)
    return context


def _candidate_sources(row, request):
    if row["category"] == "HF012_context_track_a":
        packet = _read(row["construction_provenance_only"]["public_packet"])
        selected = packet["selected_test"]
    else:
        original = _read(row["original_result"])
        packet = _read(original["public_input"])
        selected_id = json.loads(request["prompt"])["material"]["selected_test"]["id"]
        selected = next(x for x in packet["validation_tests"] if x["id"] == selected_id)
    tests = selected["files"]
    sources = {p: t for p, t in packet["final_sources"].items() if p not in tests}
    return sources, tests


def _postprocess(row, request, directory, manifest):
    result = {"provider_status": manifest["status"],
              "physical_model_calls": manifest.get("external_model_calls", 0),
              "provider_manifest": _receipt(directory / "provider/manifest.json"),
              "scientific_label": None, "status": "provider_recorded_no_retry"}
    # Preserve the raw manifest receipt before any response parsing can fail.
    _write(directory / "provider_receipt.json", result)
    try:
        raw = (directory / "provider/completion.txt").read_text()
        decoded = transport_adapter.recover_json(raw)
        _write(directory / "transport_recovery.json", decoded["receipt"])
        proposal = decoded["value"]
        _write(directory / "decoded_response.json", proposal)
        if row["category"] == "HS005_reference_completion":
            result["status"] = "P1_completion_pending_root_canonical_review"
            result["reference_replaced"] = False
        else:
            sources, tests = _candidate_sources(row, request)
            canonical, adaptations = proposal, []
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
            context = {**request["validation_context"], "source_files": {**sources, **tests}}
            slots = variants.validate_candidate_response(canonical, context)
            _write(directory / "path_adaptation.json", adaptations)
            _write(directory / "canonical_candidates.json", canonical)
            _write(directory / "candidate_slots.json", slots)
            result.update(status="candidates_pending_execution_and_semantic_review", registered_candidate_slots=5,
                          structurally_proposed=slots["n_structurally_proposed"], invalid_slots=slots["n_invalid"],
                          no_proposal_slots=slots["n_no_proposal"])
    except (ValueError, TypeError, KeyError, OSError, StopIteration) as error:
        result.update(status="response_unavailable_or_invalid_no_retry", error_type=type(error).__name__, error=str(error))
        if row["category"] != "HS005_reference_completion":
            slots = variants.validate_candidate_response(None, request.get("validation_context", {}))
            _write(directory / "candidate_slots.json", slots)
            result.update(registered_candidate_slots=5, invalid_slots=5)
    _write(directory / "result.json", result)
    return result


def dispatch(preflight_receipt, freeze_receipt, authorization_receipt, *, project_root):
    """Explicit serial execution only. Failed/partial attempts are never retried."""
    context = _authorized_context(preflight_receipt, freeze_receipt, authorization_receipt)
    output, run = context["output_root"], context["run_dir"]
    binding = {"preflight": preflight_receipt, "freeze": freeze_receipt,
               "authorization": authorization_receipt, "output_root": str(output)}
    if output.exists():
        path = output / "queue_binding.json"
        if not path.exists() or json.loads(path.read_text()) != binding:
            raise ValueError("partial_or_different_queue_root_no_dispatch")
    else:
        output.mkdir()
        _write(output / "queue_binding.json", binding)
    records = []
    ledger = provider.BudgetLedger(run, authorization_receipt)
    initial = ledger.snapshot()
    for row in context["preflight"]["requests"]:
        directory = output / f'{row["queue_ordinal"]:03d}'
        if directory.exists():
            records.append({"queue_ordinal": row["queue_ordinal"], "status": "existing_attempt_not_redispatched",
                            "complete_result_present": (directory / "result.json").is_file(), "new_physical_calls": 0})
            continue
        snapshot = ledger.snapshot()  # Receipt and authorized cap rechecked under lock.
        if any(e["request_sha256"] == row["provider_request_sha256"] for e in snapshot["calls"].values()):
            records.append({"queue_ordinal": row["queue_ordinal"], "status": "existing_ledger_attempt_not_redispatched", "new_physical_calls": 0})
            continue
        if snapshot["committed_tokens"] + row["conservative_reservation_tokens"] > snapshot["limit_tokens"]:
            records.append({"queue_ordinal": row["queue_ordinal"], "status": "budget_unavailable_queue_stopped", "new_physical_calls": 0})
            break
        # Check immutable request/code/authorization immediately before its attempt.
        _authorized_context(preflight_receipt, freeze_receipt, authorization_receipt)
        raw_request = provider.read_receipt(row["prepared_request"])
        request = json.loads(raw_request)
        try:
            directory.mkdir()  # Atomic claim; an interrupted claim is never reused.
        except FileExistsError:
            records.append({"queue_ordinal": row["queue_ordinal"], "status": "concurrent_existing_attempt_not_redispatched", "new_physical_calls": 0})
            continue
        (directory / "prepared_request.json").write_bytes(raw_request)
        _write(directory / "attempt.json", {**binding, "queue_ordinal": row["queue_ordinal"],
                "request": row["prepared_request"], "provider_request_sha256": row["provider_request_sha256"]})
        try:
            manifest = provider.call(project_root, run, directory / "provider", request,
                                     max_tokens=request["max_tokens"], authorization_receipt=authorization_receipt)
            result = _postprocess(row, request, directory, manifest)
            records.append({"queue_ordinal": row["queue_ordinal"], "status": result["status"],
                            "new_physical_calls": result["physical_model_calls"], "result": _receipt(directory / "result.json")})
            if manifest["status"] == "budget_exceeded":
                break
        except Exception as error:
            # Configuration/transport/settlement failures keep every raw byte.
            # A reserved interrupted attempt remains charged; no redispatch.
            _write(directory / "dispatcher_error.json", {"error_type": type(error).__name__,
                    "status": "interrupted_or_failed_no_retry", "error_text_omitted": "may contain credentials"})
            records.append({"queue_ordinal": row["queue_ordinal"], "status": "interrupted_or_failed_no_retry",
                            "new_physical_calls": None})
            break
    final = ledger.snapshot()
    report = {"schema": "tramask.continuation-dispatch.v1", "binding": binding, "requests": records,
              "spent_before": initial["committed_tokens"], "spent_after": final["committed_tokens"],
              "charged_tokens_this_invocation": final["committed_tokens"] - initial["committed_tokens"],
              "limit_tokens": final["limit_tokens"], "remaining_tokens": final["limit_tokens"] - final["committed_tokens"],
              "new_physical_calls_known": sum(x.get("new_physical_calls") or 0 for x in records),
              "calls_with_unknown_physical_count": sum(x.get("new_physical_calls") is None for x in records),
              "retry_performed": False, "shared_arms_extra_calls": 0}
    _write(output / f"dispatch_{time.time_ns()}_{uuid.uuid4().hex}.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-receipt", required=True)
    parser.add_argument("--freeze-receipt", required=True)
    parser.add_argument("--authorization-receipt")
    parser.add_argument("--project-root")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    load = lambda p: json.loads(Path(p).read_text())
    preflight, freeze = load(args.preflight_receipt), load(args.freeze_receipt)
    if not args.execute:
        context = inspect_queue(preflight, freeze)
        print(json.dumps({"status": "verified_not_dispatched", "requests": len(context["preflight"]["requests"]),
                          "requires_explicit_budget_authorization_and_execute_flag": True}))
        return 0
    if not args.authorization_receipt or not args.project_root:
        parser.error("--execute requires --authorization-receipt and --project-root")
    print(json.dumps(dispatch(preflight, freeze, load(args.authorization_receipt), project_root=args.project_root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
