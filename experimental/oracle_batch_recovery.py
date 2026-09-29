"""One deterministic split for a completed, malformed oracle batch.

This module never reads files, retrieves source, dispatches a model request, or
uses test execution results.  A caller supplies the frozen request, the provider
manifest, and its completion text.  ``plan_recovery`` returns new requests only
for a completed batch with invalid JSON or ``finish_reason == 'length'``.

Each child contains exactly one of the parent's offered candidates.  Its C alias
becomes C0, while its assertions retain their A aliases.  All contract, source,
input edits, assertion text, system instructions, and provider settings survive
unchanged.  Children carry depth=1 and can never be split again.  Original inputs
are not mutated; callers retain the original request and response artifacts.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re


POLICY = "completed-batch-singleton-split-v1"


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _record_sha(value):
    return _sha(json.dumps(value, sort_keys=True, ensure_ascii=True))


def validate_frozen_request(request):
    """Validate the local/wire mapping and return the already-frozen payload.

    This checks internal consistency, not the semantic correctness of the
    candidate or the issue.  No source is reparsed or added to the request.
    """
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    if not isinstance(request.get("prompt"), str) or not isinstance(request.get("system"), str):
        raise ValueError("frozen prompt and system are required")
    if request.get("id") != _sha(request["prompt"]):
        raise ValueError("frozen prompt hash changed")
    offered = request.get("offered")
    if not isinstance(offered, dict) or not 1 <= len(offered) <= 16:
        raise ValueError("offered must contain one to sixteen candidates")
    # Match the exact hashing convention of relation_search.oracle.
    if request.get("candidate_source_hash") != _record_sha(offered):
        raise ValueError("frozen candidate source hash changed")
    try:
        payload = json.loads(request["prompt"])
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("frozen prompt is not JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise ValueError("frozen prompt has no candidate list")
    if not isinstance(payload.get("issue"), str):
        raise ValueError("frozen prompt has no issue contract")
    contract_hash = request.get("issue_contract_sha256")
    if contract_hash is not None and contract_hash != _sha(payload["issue"]):
        raise ValueError("frozen issue contract hash changed")
    seen = set()
    for wire in payload["candidates"]:
        if not isinstance(wire, dict):
            raise ValueError("wire candidate must be an object")
        alias = wire.get("candidate")
        if not isinstance(alias, str) or not re.fullmatch(r"C\d+", alias):
            raise ValueError("invalid candidate alias")
        if alias in seen or alias not in offered:
            raise ValueError("duplicate or unoffered candidate alias")
        seen.add(alias)
        local = offered[alias]
        if not isinstance(local, dict) or not isinstance(local.get("candidate"), dict):
            raise ValueError("local candidate must be an object")
        candidate, holes = local["candidate"], local.get("assertions")
        if not isinstance(candidate.get("id"), str) or not isinstance(candidate.get("edits"), list):
            raise ValueError("local candidate is incomplete")
        if wire.get("source_test") != candidate.get("base_test_id"):
            raise ValueError("source test mapping changed")
        if not isinstance(wire.get("modified_test"), str):
            raise ValueError("wire candidate has no test source")
        if not isinstance(holes, dict) or not holes or not isinstance(wire.get("assertions"), list):
            raise ValueError("assertion mapping is missing")
        wire_holes = {}
        for hole in wire["assertions"]:
            if not isinstance(hole, dict):
                raise ValueError("wire assertion must be an object")
            hid = hole.get("id")
            if not isinstance(hid, str) or not re.fullmatch(r"A\d+", hid) or hid in wire_holes:
                raise ValueError("duplicate or invalid assertion alias")
            wire_holes[hid] = hole
        if set(wire_holes) != set(holes):
            raise ValueError("wire/local assertion aliases differ")
        for hid, hole in holes.items():
            if not isinstance(hole, dict) or any(wire_holes[hid].get(key) != hole.get(key)
                                                for key in ("code", "observed")):
                raise ValueError("wire/local assertion contents differ")
        try:
            changes = [dict(before=edit["before"], after=edit["after"])
                       for edit in candidate["edits"] if edit.get("role") != "semantic_expected"]
        except (TypeError, KeyError, AttributeError) as error:
            raise ValueError("local candidate edits are malformed") from error
        if wire.get("input_changes") != changes:
            raise ValueError("wire/local input edits differ")
    if seen != set(offered):
        raise ValueError("wire/local candidate aliases differ")
    return payload


def recovery_condition(request, manifest, completion_text):
    """Return ``(eligible, reason)`` without treating semantic rejection as failure.

    Timeouts, transport errors, in-progress calls, syntactically valid but wrong
    response schemas, model refusals, and empty revisions do not trigger a call.
    """
    validate_frozen_request(request)
    if not isinstance(manifest, dict) or manifest.get("request_id") != request["id"]:
        raise ValueError("completion manifest belongs to a different request")
    if manifest.get("status") != "complete":
        return False, "provider_not_complete"
    recovery = request.get("batch_recovery")
    if recovery is not None:
        return False, "already_split"
    if len(request["offered"]) <= 1:
        return False, "already_singleton"
    if not isinstance(completion_text, str):
        raise ValueError("a completed provider response requires its exact text")
    if manifest.get("finish_reason") == "length":
        return True, "completed_length_limit"
    try:
        json.loads(completion_text)
    except json.JSONDecodeError:
        return True, "completed_invalid_json"
    return False, "completed_parseable_json"


def plan_recovery(request, manifest, completion_text):
    """Return a deterministic pure-data plan, preserving the original evidence.

    Example::

        plan = plan_recovery(frozen_request, provider_manifest, completion_text)
        for child in plan["requests"]:
            # The caller records and dispatches each new child at most once.
            ...

    Evidence hashes bind the plan to the supplied original artifacts. They do
    not substitute for independently retaining those artifacts on disk.
    """
    eligible, reason = recovery_condition(request, manifest, completion_text)
    evidence = dict(parent_request_id=request["id"],
                    parent_request_sha256=_record_sha(request),
                    parent_manifest_sha256=_record_sha(manifest),
                    parent_completion_sha256=_sha(completion_text) if isinstance(completion_text, str) else None)
    plan = dict(policy=POLICY, eligible=eligible, reason=reason,
                evidence=evidence, requests=[])
    if not eligible:
        return plan
    payload = json.loads(request["prompt"])
    for index, wire in enumerate(payload["candidates"]):
        old_alias = wire["candidate"]
        child_payload = copy.deepcopy(payload)
        child_wire = copy.deepcopy(wire)
        child_wire["candidate"] = "C0"
        child_payload["candidates"] = [child_wire]
        child = copy.deepcopy(request)
        child["prompt"] = json.dumps(child_payload, ensure_ascii=False)
        child["offered"] = {"C0": copy.deepcopy(request["offered"][old_alias])}
        child["id"] = _sha(child["prompt"])
        child["candidate_source_hash"] = _record_sha(child["offered"])
        child["batch_recovery"] = dict(policy=POLICY, depth=1, reason=reason, ordinal=index,
                                      parent_alias=old_alias, child_alias="C0", **evidence)
        validate_frozen_request(child)
        plan["requests"].append(child)
    return plan
