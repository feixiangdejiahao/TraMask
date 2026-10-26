"""One bounded P1 data-construction call with fuller original source material.

This is never a retry arm for Pilot 4 Track B. Eligibility is a missing or
structurally unusable counterfactual, established before paired behavior is
examined. A valid Q is never replaced because it discriminates or fails to flip.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

from tramask_pilot.corpus import ROOT, read, receipt
from tramask_pilot.provider import call
from .study import RUN, now, write_new
from .workflow import public_packet

CAP = 262144


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def prepare(case, run=RUN):
    run = Path(run)
    directory = run / "runs" / case["id"]
    original = read(directory / "target_generation/prepared_request.json")
    if not original.get("dispatchable"):
        raise ValueError("Material construction first requires an explicit non-dispatchable-input policy")
    payload = json.loads(original["prompt"])
    material = payload["material"]
    packet = public_packet(case, run)
    selected = read(directory / "selection.json")
    changes = []
    sources = copy.deepcopy(material.get("local_sources", {}))
    for subject_path in selected["source_paths"]:
        path = subject_path.lstrip("/")
        text = packet["final_sources"].get(path)
        if text is None:
            changes.append({"path": path, "status": "original_selected_source_missing"})
            continue
        raw = text.encode()
        proposal = copy.deepcopy(sources)
        proposal[path] = [{"start_line": 1, "end_line": len(text.splitlines()), "start_byte": 0,
                           "end_byte": len(raw), "text": text}]
        candidate = copy.deepcopy(payload)
        candidate["material"]["local_sources"] = proposal
        candidate["available_evidence_refs"] = sorted(set(candidate["available_evidence_refs"]) | {"source:" + path})
        size = len(original["system"].encode()) + len(_dump(candidate).encode())
        if size > CAP:
            changes.append({"path": path, "status": "complete_file_exceeds_remaining_cap_original_view_retained",
                            "original_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            continue
        sources = proposal
        payload = candidate
        changes.append({"path": path, "status": "complete_original_source_added",
                        "original_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    prompt = _dump(payload)
    request = {"id": case["id"] + "/pilot1/reference_material_completion/repeat_01",
               "system": original["system"], "prompt": prompt, "max_tokens": original["max_tokens"],
               "dispatchable": True, "status": "prepared",
               "input_receipt": {"original_request": receipt(directory / "target_generation/prepared_request.json"),
                    "full_source_changes": changes, "input_utf8_cap": CAP,
                    "total_input_utf8_bytes": len(prompt.encode()) + len(original["system"].encode()),
                    "system_unchanged": True, "old_proposal_or_behavioral_outcomes_in_input": False,
                    "role": "P1 reference data construction, not method search or independent replicate"}}
    if not any(row["status"] == "complete_original_source_added" for row in changes):
        request.update(dispatchable=False, status="no_additional_material", prompt="")
    return request


def complete(case, run=RUN):
    run = Path(run)
    policy = read(run / "amendments/002_counterfactual_material_completion.json")
    if case["id"] not in policy["eligible_cases"]:
        raise ValueError("Not registered for material completion")
    out = run / "runs" / case["id"] / "reference_material_completion_v01"
    if (out / "result.json").exists():
        return read(out / "result.json")
    request = prepare(case, run)
    write_new(out / "prepared_request.json", request)
    result = {"case_id": case["id"], "created_at": now(), "request": receipt(out / "prepared_request.json"),
              "role": "P1 data-construction material completion; no P4B retry", "scientific_label": None}
    if not request["dispatchable"]:
        result.update(status=request["status"], physical_model_calls=0)
    else:
        manifest = call(ROOT, run, out / "provider", request, max_tokens=request["max_tokens"])
        result.update(status="awaiting_canonicalization_and_qualification", provider_status=manifest.get("status"),
                      physical_model_calls=manifest.get("external_model_calls", 0),
                      provider_manifest=receipt(out / "provider/manifest.json"))
    write_new(out / "result.json", result)
    return result
