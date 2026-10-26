"""Held-out factorial generation with immutable independent physical repeats."""
from pathlib import Path

from tramask_pilot.corpus import ROOT, read, receipt
from tramask_pilot.hypotheses import validate_hypothesis
from tramask_pilot.provider import call
from .study import RUN, now, write_new
from .workflow_inventory_v05 import end_to_end_packet
from .prompts_inventory_v02 import build_end_to_end_request, _target
from .transport_adapter import recover_json, canonicalize_paths
from .variants import validate_candidate_response


def _guard_q_regions(proposal, selected):
    from .study import sha
    regions = {r["path"].lstrip("/"): r for r in selected.get("protected_test_regions", [])}
    for edit in proposal["alternative"]["edits"]:
        path = edit["path"]
        if path not in regions:
            continue
        region = regions[path]
        data = selected["files"][path].encode()
        start, end = region["selected_region_utf8_offsets"]
        if sha(data[:start]) != region["terminal_production_prefix_sha256"] or sha(data[start:end]) != region["original_test_region_sha256"]:
            raise ValueError("Mixed source/test authority mismatch")
        old = edit["old"].encode()
        offset = data.find(old)
        if offset < 0 or data.find(old, offset + 1) >= 0 or offset + len(old) > start:
            raise ValueError("Q overlaps protected original test region")


def generate(case, method, repeat, stage=1, run=RUN):
    run = Path(run)
    if method not in {"M1", "M2", "M3", "M4"} or repeat not in {1, 2} or stage not in {1, 2}:
        raise ValueError("Unregistered Track B cell")
    policy = read(run / "amendments/011_remaining_inventory_regions.json")
    for bound in policy["implementation"]:
        if receipt(bound["path"]) != bound:
            raise ValueError("Frozen Track B implementation changed")
    if case.get("partition") != "reserved":
        raise ValueError("Track B population is the fixed20 reserved cases")
    root = run / "runs" / case["id"] / "track_b" / method / f"repeat_{repeat:02d}"
    out = root / f"stage_{stage:02d}"
    if (out / "result.json").exists():
        return read(out / "result.json")
    if out.exists():
        raise FileExistsError("Partial generation retained; no implicit retry")
    if stage == 1:
        bound = policy["inventory_bindings"][case["id"]]
        if receipt(bound["path"]) != bound:
            raise ValueError("Registered inventory changed")
        packet = end_to_end_packet(case, run, qualification_path=bound["path"])
    else:
        first_receipt = read(root / "stage_01/result.json")["public_input"]
        if receipt(first_receipt["path"]) != first_receipt:
            raise ValueError("Frozen stage1 packet changed")
        packet = read(first_receipt["path"])
    planning, evidence = None, None
    if stage == 2:
        first = read(root / "stage_01/result.json")
        allowed = {"planning_requires_Q_execution_qualification"} if method in {"M3", "M4"} else {"planning_qualified_for_next_generation"}
        if first.get("status") not in allowed:
            raise ValueError("Stage1 did not qualify; no stage2 request allowed")
        planning = read(root / "stage_01/planning.json")
        if method in {"M3", "M4"}:
            qualification = read(root / "target_execution/qualification.json")
            if qualification.get("qualified_for_stage2") is not True:
                raise ValueError("Two-flip target execution did not qualify")
            if qualification.get("planning") != receipt(root / "stage_01/planning.json"):
                raise ValueError("Target feedback is not bound to this independent planning call")
            bound = qualification["public_feedback"]
            if receipt(bound["path"]) != bound:
                raise ValueError("Raw target feedback receipt changed")
            raw_feedback = read(bound["path"])
            evidence = {key: raw_feedback[key] for key in ("before_effects", "original_observations") if key in raw_feedback}
            if set(evidence) != {"before_effects", "original_observations"}:
                raise ValueError("Both actual measurement channels required for two-flip stage2")
    request = build_end_to_end_request(packet, method, repeat, stage, planning=planning, evidence=evidence)
    write_new(out / "public_input.json", packet)
    write_new(out / "prepared_request.json", request)
    result = {"case_id": case["id"], "method": method, "repeat": repeat, "stage": stage,
              "created_at": now(), "status": "prepared", "scientific_label": None,
              "request": receipt(out / "prepared_request.json"), "public_input": receipt(out / "public_input.json"), "physical_model_calls": 0}
    if not request["dispatchable"]:
        result.update(status="input_unavailable", reason=request.get("reason"))
        write_new(out / "result.json", result)
        return result
    manifest = call(ROOT, run, out / "provider", request, max_tokens=request["max_tokens"])
    result.update(provider_manifest=receipt(out / "provider/manifest.json"), provider_status=manifest["status"],
                  physical_model_calls=manifest.get("external_model_calls", 0))
    try:
        decoded = recover_json((out / "provider/completion.txt").read_text())
        result["transport_recovery"] = decoded["receipt"]
        proposal = decoded["value"]
        if not isinstance(proposal, dict):
            raise ValueError("Response must be an object")
        if stage == 1:
            if proposal.get("status") == "insufficient_evidence":
                if not isinstance(proposal.get("reason"), str) or not proposal["reason"]:
                    raise ValueError("Abstention requires a reason")
                result.update(status="explicit_planning_abstention", reason=proposal["reason"])
                write_new(out / "planning.json", proposal)
            else:
                selected = next((t for t in packet["validation_tests"] if t["id"] == proposal.get("selected_test_id")), None)
                if selected is None or proposal.get("original_command") != selected["command"]:
                    raise ValueError("Selected test or exact original command changed")
                if method in {"M1", "M2"}:
                    if proposal.get("status") not in {"planned_target", "proposed"}:
                        raise ValueError("Direct planning requires planned_target")
                    proposal = {key: proposal[key] for key in ("status", "reason", "selected_test_id", "original_command", "target")}
                    proposal["status"] = "planned_target"
                adapted = canonicalize_paths(proposal, {p: t for p, t in packet["final_sources"].items() if p not in selected["files"]}, selected["files"])
                proposal = adapted["proposal"]
                result["path_adapter"] = adapted["receipt"]
                _target(proposal["target"])
                if not isinstance(proposal.get("reason"), str) or not proposal["reason"]:
                    raise ValueError("Planning requires public justification")
                if method in {"M3", "M4"}:
                    validate_hypothesis(proposal, source_paths=packet["final_sources"], test_paths=set(selected["files"]) - {r["path"].lstrip("/") for r in selected.get("protected_test_regions", [])}, original_command=selected["command"])
                    _guard_q_regions(proposal, selected)
                write_new(out / "planning.json", proposal)
                result.update(status="planning_requires_Q_execution_qualification" if method in {"M3", "M4"} else "planning_qualified_for_next_generation",
                              planning=receipt(out / "planning.json"))
        else:
            selected = next(t for t in packet["validation_tests"] if t["id"] == planning["selected_test_id"])
            # One invalid anchor must not erase other registered candidate slots.
            canonical = dict(proposal)
            adapter_rows = []
            if isinstance(proposal.get("candidates"), list):
                canonical["candidates"] = []
                for index, candidate in enumerate(proposal["candidates"]):
                    try:
                        adapted = canonicalize_paths({"candidates": [candidate]}, {p: t for p, t in packet["final_sources"].items() if p not in selected["files"]}, selected["files"])
                        canonical["candidates"].append(adapted["proposal"]["candidates"][0])
                        adapter_rows.append({"index": index, "receipt": adapted["receipt"]})
                    except (ValueError, TypeError, KeyError) as error:
                        canonical["candidates"].append(candidate)
                        adapter_rows.append({"index": index, "error": str(error), "raw_slot_retained_for_validation": True})
            result["path_adapter"] = adapter_rows
            context = {**request["validation_context"], "source_files": {**packet["final_sources"], **selected["files"]}}
            slots = validate_candidate_response(canonical, context)
            write_new(out / "canonical_candidates.json", canonical)
            write_new(out / "candidate_slots.json", slots)
            result.update(status="candidates_pending_execution_and_oracle_qualification", registered_candidate_slots=5,
                          structurally_proposed=slots["n_structurally_proposed"], invalid_slots=slots["n_invalid"], no_proposal_slots=slots["n_no_proposal"])
    except (ValueError, TypeError, KeyError, OSError) as error:
        result.update(status="invalid_response", error_type=type(error).__name__, error=str(error),
                      registered_candidate_slots=5 if stage == 2 else 0)
    write_new(out / "result.json", result)
    return result
