"""Balanced, independent Pilot 2/4 dispatch on already double-reviewed masks."""
from pathlib import Path

from .corpus import ROOT, RUN, calls, read, receipt, write
from .evidence import selected_tree_files
from .proposals import ARMS, build_proposal_request


def confirmed_packet(case_id, scoped_test, *, input_id=None):
    case = RUN / "runs" / case_id
    mapping = next(row for row in read(RUN / "review_private_mapping.json")["packets"]
                   if row["case_id"] == case_id)
    reviews = [RUN / "blind_review" / ("reviewer_" + name) / (mapping["pair_id"] + ".json")
               for name in ("a", "b")]
    assert all(read(path).get("confirmed_mask") is True for path in reviews), "requires_two_confirmations"
    out = case / "downstream"
    packet_path = out / "input.json"
    if packet_path.exists():
        return read(packet_path)
    hdir = Path(read(case / "active_hypothesis.json")["directory"])
    hypothesis = read(hdir / "hypothesis.json")
    q_input = read(case / "target_hypothesis/input.json")
    files = selected_tree_files(case)
    tests = {path: files[path] for path in q_input["selected_test"]["files"]}
    def events(channel):
        result = {}
        for variant in ("p", "q"):
            record = read(case / "before_pair" / (variant + "_instrumented") / "execution.json")
            result[variant] = [event for event in record["events"]
                               if event["channel"] == channel and scoped_test in
                               str(event.get("test", event.get("test_id", ""))) and
                               (input_id is None or event.get("input") == input_id)]
            assert result[variant], "scoped_original_events_missing"
        return result
    packet = {"pair_id": case_id, "issue": (RUN / "inputs" / case_id / "instruction.md").read_text(),
              "target": hypothesis["target"], "alternative": hypothesis["alternative"],
              "selected_test": {"command": hypothesis["original_command"], "files": tests},
              "final_patch": (RUN / "inputs" / case_id / "model.patch").read_text(),
              "local_sources": {path: text for path, text in files.items() if path not in tests},
              "actions": calls(read(RUN / "inputs" / case_id / "trajectory.json")),
              "before_effects": events("effect"), "original_observations": events("observation")}
    # Build all arms before writing: an essential-material quota failure must
    # affect the entire balanced block, not selectively change an arm's input.
    requests = [build_proposal_request(packet, pilot, arm, repeat)
                for pilot, arms in ARMS.items() for arm in arms for repeat in (1, 2)]
    write(out / "confirmation.json", {"review_receipts": [receipt(path) for path in reviews],
          "scoped_test": scoped_test, "hypothesis": receipt(hdir / "hypothesis.json"),
          "scoped_input_id": input_id,
          "candidate_slots_per_call": 5, "physical_calls": 14, "independent_repeats": 2,
          "no_repair_results_in_review_packets": True})
    write(packet_path, packet)
    for request in requests:
        _, pilot, arm, repeat = request["id"].split("/")
        write(out / pilot / arm / repeat / "prepared_request.json", request)
    return packet


def dispatch(case_id, pilot, arm, repeat):
    from .provider import call
    out = RUN / "runs" / case_id / "downstream" / ("pilot" + str(pilot)) / arm / f"repeat_{repeat:02d}"
    request = read(out / "prepared_request.json")
    manifest = out / "manifest.json"
    if manifest.exists():
        return {"id": request["id"], "status": read(manifest).get("status"), "existing": True}
    result = call(ROOT, RUN, out, request, max_tokens=8192)
    return {"id": request["id"], "status": result.get("status")}


def recover_candidates(request_directory):
    """Record raw schema failures; recover only fixed envelope/escaping mechanics.

    No candidate semantics, ranks, assertions, or missing candidate fields are
    invented. Invalid slots do not prevent auditing later independent slots.
    """
    import copy
    from .proposals import validate_proposals
    request_directory = Path(request_directory)
    req = read(request_directory / "prepared_request.json")
    raw = read(request_directory / "manifest.json").get("parsed")
    result = {"request": receipt(request_directory / "prepared_request.json"),
              "raw_response": receipt(request_directory / "manifest.json"), "slots": []}
    try:
        validate_proposals(raw, req["validation_context"])
        result["raw_schema_valid"] = True
    except ValueError as error:
        result.update(raw_schema_valid=False, raw_schema_error=str(error))
    if not isinstance(raw, dict) or not isinstance(raw.get("candidates"), list):
        result["status"] = "unrecoverable_response"
        write(request_directory / "candidate_recovery.json", result)
        return result
    context = req["validation_context"]
    case_dir = request_directory.parents[3]
    packet = read(case_dir / "downstream/input.json")
    files = packet["selected_test"]["files"]
    for candidate in raw["candidates"]:
        candidate = copy.deepcopy(candidate)
        rank = candidate.get("rank")
        if type(rank) is not int or not 1 <= rank <= 5:
            raise ValueError("invalid_original_rank")
        repairs = []
        for edit in candidate.get("edits", []):
            source = files.get(edit.get("path"), "")
            old = edit.get("old", "")
            if old and source.count(old) != 1:
                # Decode only an additional backslash layer in embedded source
                # literals, and only when it recovers one exact original anchor.
                decoded = old.replace("\\\\n", "\\n").replace("\\\\t", "\\t")
                if decoded != old and source.count(decoded) == 1:
                    edit["old"] = decoded
                    edit["new"] = edit["new"].replace("\\\\n", "\\n").replace("\\\\t", "\\t")
                    repairs.append("one_extra_escape_layer_in_embedded_code_literal")
        envelope = {"edit_policy": raw.get("edit_policy", context["edit_policy"]),
                    "original_command": raw.get("original_command", context["original_command"]),
                    "candidates": [candidate if i == rank else
                                   {"rank": i, "status": "no_proposal", "reason": "Other original slot validated independently."}
                                   for i in range(1, 6)]}
        row = {"rank": rank, "candidate_status": candidate.get("status"), "mechanical_repairs": repairs,
               "envelope_binding": "Missing command/policy bound to immutable prepared request; extra top-level type metadata ignored. No alternate command accepted."}
        try:
            validate_proposals(envelope, context)
            for edit in candidate.get("edits", []):
                if files.get(edit["path"], "").count(edit["old"]) != 1:
                    raise ValueError("candidate_anchor_not_unique_in_original_test")
            row["status"] = "pending_manual_legality" if candidate["status"] == "proposed" else "no_proposal"
        except ValueError as error:
            row.update(status="invalid_candidate", reason=str(error))
        destination = request_directory / f"candidate_{rank:02d}"
        write(destination / "candidate.json", candidate)
        write(destination / "validation.json", row)
        result["slots"].append(row)
    write(request_directory / "candidate_recovery.json", result)
    return result
