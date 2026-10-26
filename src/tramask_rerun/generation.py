"""New-run request dispatch; raw proposals stay separate from executed evidence."""
from __future__ import annotations
from pathlib import Path

from tramask_pilot.corpus import ROOT, read, receipt
from tramask_pilot.hypotheses import validate_hypothesis
from tramask_pilot.provider import call
from .prompts import build_target_request
from .study import RUN, now, write_new
from .workflow import public_packet


def target(case, run=RUN):
    run = Path(run)
    protocol = run / "protocol.json"
    if not protocol.exists():
        raise ValueError("Freeze protocol/prompts before model calls")
    out = run / "runs" / case["id"] / "target_generation"
    result_path = out / "result.json"
    if result_path.exists():
        return read(result_path)
    packet = public_packet(case, run)
    request = build_target_request(packet)
    write_new(out / "public_input.json", packet)
    write_new(out / "prepared_request.json", request)
    result = {"case_id": case["id"], "created_at": now(), "protocol": receipt(protocol),
              "request": receipt(out / "prepared_request.json"), "status": "pending"}
    if not request["dispatchable"]:
        result.update(status="material_unavailable", reason=request["reason"], physical_model_calls=0)
        write_new(result_path, result)
        return result
    manifest = call(ROOT, run, out / "provider", request, max_tokens=request["max_tokens"])
    result.update(provider_status=manifest.get("status"),
                  physical_model_calls=manifest.get("external_model_calls", 0),
                  provider_manifest=receipt(out / "provider/manifest.json"))
    proposal = manifest.get("parsed")
    if manifest.get("status") != "complete" or not isinstance(proposal, dict):
        result.update(status="provider_or_format_failure")
    else:
        try:
            validate_hypothesis(proposal, source_paths=packet["final_sources"],
                                test_paths=packet["selected_test"]["files"],
                                original_command=packet["selected_test"]["command"])
            write_new(out / "hypothesis.json", proposal)
            result.update(status="proposal_pending_execution_review" if proposal["status"] == "proposed" else "insufficient_evidence_proposal",
                          hypothesis=receipt(out / "hypothesis.json"))
        except (ValueError, TypeError, KeyError) as error:
            result.update(status="invalid_proposal", error_type=type(error).__name__, error=str(error))
    result["scientific_label"] = None
    write_new(result_path, result)
    return result
