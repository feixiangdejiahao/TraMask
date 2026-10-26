"""Record mechanical recovery and separate a fixed Q from its proposed probes.

Extracting a syntactically applicable Q is not an E3 judgment. It is permitted
only from an actual model-proposed alternative, with unchanged replacement code.
The original full-proposal failure remains visible alongside the extracted Q.
"""
import copy
from pathlib import Path

from tramask_pilot.corpus import read, receipt
from tramask_pilot.hypotheses import validate_hypothesis, _edits
from .transport_adapter import recover_json, canonicalize_paths, TransportAdapterError
from .study import RUN, now, write_new
from .workflow_primary_v02 import public_packet


def canonicalize(case, generation, output, run=RUN):
    run, generation, output = Path(run), Path(generation), Path(output)
    if (output / "result.json").exists():
        return read(output / "result.json")
    if output.exists():
        raise FileExistsError("Partial canonicalization retained: " + str(output))
    packet = public_packet(case, run)
    tests = packet["selected_test"]["files"]
    files = {**packet["final_sources"], **tests}
    result = {"case_id": case["id"], "created_at": now(), "generation": receipt(generation / "result.json"),
              "scientific_label": None, "executed": False,
              "full_proposal_status": "not_parsed", "fixed_Q_status": "not_available"}
    raw = generation / "provider/completion.txt"
    try:
        result["raw_completion"] = receipt(raw)
        decoded = recover_json(raw.read_text())
        result["json_recovery"] = decoded["receipt"]
        proposal = decoded["value"]
        write_new(output / "decoded_proposal.json", proposal)
    except (ValueError, OSError) as error:
        result["error"] = {"type": type(error).__name__, "reason": str(error)}
        write_new(output / "result.json", result)
        return result
    try:
        full = canonicalize_paths(proposal, files, tests)
        result["full_path_adapter"] = full["receipt"]
        write_new(output / "canonical_proposal.json", full["proposal"])
        validate_hypothesis(full["proposal"], source_paths=packet["final_sources"], test_paths=tests,
                            original_command=packet["selected_test"]["command"])
        result["full_proposal_status"] = "structurally_valid_" + full["proposal"]["status"]
    except (ValueError, TypeError, KeyError) as error:
        result["full_proposal_status"] = "invalid"
        result["full_proposal_error"] = {"type": type(error).__name__, "reason": str(error)}
        if isinstance(error, TransportAdapterError):
            result["full_path_adapter"] = error.receipt
    # No repair to Q. Probe defects cannot alone invalidate a separately
    # applicable alternative, which still requires static and dynamic review.
    try:
        if not isinstance(proposal, dict) or proposal.get("status") != "proposed":
            raise ValueError("No proposed counterfactual")
        if proposal.get("original_command") != packet["selected_test"]["command"]:
            raise ValueError("Original command differs")
        core = {key: copy.deepcopy(proposal[key]) for key in ("status", "reason", "original_command", "target", "alternative")}
        normalized = canonicalize_paths(core, files, tests)
        core = normalized["proposal"]
        edits = _edits(core["alternative"]["edits"])
        if not edits:
            raise ValueError("Empty alternative")
        if core["target"]["source_path"] not in packet["final_sources"]:
            raise ValueError("Target must be original production source")
        if any(e["path"] not in packet["final_sources"] for e in edits):
            raise ValueError("Q modifies test or unavailable production path")
        if core["alternative"].get("kind") not in {"historical_edit", "local_revert", "targeted_mutation"}:
            raise ValueError("Unknown alternative kind")
        if core["alternative"]["kind"] == "historical_edit" and not core["alternative"].get("action_ids"):
            raise ValueError("Historical edit requires cited actions")
        write_new(output / "fixed_counterfactual.json", core)
        result.update(fixed_Q_status="exactly_applicable_pending_semantic_and_execution_qualification",
                      fixed_counterfactual=receipt(output / "fixed_counterfactual.json"), Q_path_adapter=normalized["receipt"],
                      interpretation="Q replacement bytes unchanged. Proposed probes are separate and may be unusable; no Q relevance, nontriviality, build, E3, or masking claim.")
    except (ValueError, TypeError, KeyError) as error:
        result["fixed_Q_error"] = {"type": type(error).__name__, "reason": str(error)}
    write_new(output / "result.json", result)
    return result
