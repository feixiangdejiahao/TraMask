"""Evidence conjunctions and scoped comparisons, never reviewer masking votes.

Resolved checklist entries require byte-bound artifact receipts. Trace matching
is by explicit semantic identity, with missing or ambiguous events unresolved.
Semantic reviewers judge Q relevance, context legality and oracle support;
their judgments remain distinct from mechanically derived experiment labels.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


CHECKS = tuple(f"E{i}" for i in range(1, 10))
STATUSES = {"pass", "fail", "unresolved"}
SEMANTIC_GATES = {"counterfactual_relevance": "E3", "context_legality": "E7", "oracle_validity": "E9"}
NONMASK_FINDINGS = {
    "target_bypass", "target_not_activated", "observation_gap", "weak_oracle",
    "original_test_discriminates", "invalid_counterfactual", "incomplete_evidence",
}
IDENTITY_FIELDS = ("anchor", "test", "input", "call", "invocation")


def validate_receipt(receipt: dict, *, verify_file: bool = True) -> dict:
    """Validate a path/bytes/SHA256 receipt and, by default, the actual artifact."""
    if not isinstance(receipt, dict) or not {"path", "bytes", "sha256"} <= receipt.keys():
        raise ValueError("evidence_requires_artifact_receipt")
    path, size, digest = receipt["path"], receipt["bytes"], receipt["sha256"]
    if (not isinstance(path, str) or not Path(path).is_absolute()
            or type(size) is not int or size < 0
            or not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("invalid_artifact_receipt")
    result = {"path": path, "bytes": size, "sha256": digest}
    if verify_file:
        raw = Path(path).read_bytes()
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("artifact_receipt_mismatch")
    return result


def _check(value, *, verify_receipts):
    if (not isinstance(value, dict) or not isinstance(value.get("status"), str)
            or value["status"] not in STATUSES):
        raise ValueError("check_requires_pass_fail_or_unresolved")
    evidence = value.get("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("evidence_must_be_receipt_list")
    if value["status"] != "unresolved" and not evidence:
        raise ValueError("resolved_check_requires_evidence")
    receipts = [validate_receipt(row, verify_file=verify_receipts) for row in evidence]
    return {**value, "evidence": receipts}


def derive_classification(checks: dict, *, nonmask_findings: dict | None = None,
                          verify_receipts: bool = True) -> dict:
    """Derive candidate/confirmed/oracle levels from E1..E9 conjunctions.

    Missing checks become unresolved. Failing E7/E8 establishes only that an
    examined edit did not qualify, not that no legal witness exists. A nonmask
    category requires a separate, explicit evidence-backed finding; invalid Q
    and incomplete evidence remain unanalyzable, never negative observations.
    """
    if not isinstance(checks, dict) or set(checks) - set(CHECKS):
        raise ValueError("checks_must_be_named_E1_through_E9")
    normalized = {key: _check(checks.get(key, {"status": "unresolved", "evidence": [],
                  "reason": "check_not_supplied"}), verify_receipts=verify_receipts) for key in CHECKS}
    findings = {} if nonmask_findings is None else nonmask_findings
    if not isinstance(findings, dict) or set(findings) - NONMASK_FINDINGS:
        raise ValueError("unknown_nonmask_finding; finite_search_failure_is_not_a_nonmask_category")
    findings = {key: _check(value, verify_receipts=verify_receipts) for key, value in findings.items()}
    active = sorted(key for key, row in findings.items() if row["status"] == "pass")
    conjunctions = {
        "candidate": all(normalized[key]["status"] == "pass" for key in CHECKS[:6]),
        "confirmed": all(normalized[key]["status"] == "pass" for key in CHECKS[:8]),
        "oracle_qualified": all(normalized[key]["status"] == "pass" for key in CHECKS),
    }
    # A competing explicit diagnosis and a positive conjunction must be
    # reconciled, rather than silently choosing whichever produces a positive.
    conflict = bool(active and conjunctions["candidate"]) or len(active) > 1
    if conflict:
        classification, disposition = "unresolved_conflicting_evidence", "unresolved"
    elif active:
        classification = active[0]
        disposition = "unresolved" if classification in {"invalid_counterfactual", "incomplete_evidence"} else "nonmask"
    elif conjunctions["oracle_qualified"]:
        classification, disposition = "oracle_qualified_repair", "confirmed"
    elif conjunctions["confirmed"]:
        classification, disposition = "confirmed_behavioral_masking", "confirmed"
    elif conjunctions["candidate"]:
        classification, disposition = "masking_candidate", "candidate"
    else:
        classification, disposition = "unresolved", "unresolved"
    return {
        "classification": classification, "disposition": disposition,
        "candidate": conjunctions["candidate"] and not conflict,
        "confirmed": conjunctions["confirmed"] and not conflict,
        "oracle_qualified": conjunctions["oracle_qualified"] and not conflict,
        "check_conjunctions": conjunctions,
        "count_as_nonmask": disposition == "nonmask",
        "checks": normalized, "nonmask_findings": findings,
        "failed_checks": [key for key, row in normalized.items() if row["status"] == "fail"],
        "unresolved_checks": [key for key, row in normalized.items() if row["status"] == "unresolved"],
        "witness_status": "established" if conjunctions["confirmed"] and not conflict else "unresolved",
        "finite_search_failure_is_nonmask_evidence": False,
        "label_source": "E1-E9 evidence conjunctions and explicit diagnostic evidence; no reviewer masking vote",
        "receipt_validation": "artifact_bytes_verified" if verify_receipts else "receipt_structure_only",
    }


def _typed(value):
    """Hashable exact JSON representation; bool is never integer 1/0."""
    if value is None:
        return ("null",)
    if type(value) is bool:
        return ("boolean", value)
    if type(value) is int:
        return ("integer", value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite_json_value")
        return ("float", value.hex())
    if type(value) is str:
        return ("string", value)
    if type(value) is list:
        return ("array", tuple(_typed(item) for item in value))
    if type(value) is dict and all(type(key) is str for key in value):
        return ("object", tuple((key, _typed(value[key])) for key in sorted(value)))
    raise ValueError("event_values_must_be_exact_json_types")


def _event(value):
    if (not isinstance(value, dict) or not isinstance(value.get("channel"), str)
            or value["channel"] not in {"effect", "observation"}
            or not isinstance(value.get("anchor"), str) or not value["anchor"]
            or type(value.get("target_reached")) is not bool or "value" not in value):
        raise ValueError("invalid_semantic_event")
    result = dict(value)
    for alias, canonical in (("test_id", "test"), ("call_id", "call")):
        if alias in value:
            if canonical in value and _typed(value[canonical]) != _typed(value[alias]):
                raise ValueError("conflicting_event_identity_alias")
            result[canonical] = value[alias]
    _typed(result["value"])
    for key in IDENTITY_FIELDS:
        if key in result:
            _typed(result[key])
    return result


def _matches(event, scope):
    return all(key in event and _typed(event[key]) == _typed(value) for key, value in scope.items())


def _align(p_events, q_events, identity_fields):
    def index(events):
        result = {}
        for event in events:
            key = tuple((field, _typed(event[field]) if field in event else ("missing",)) for field in identity_fields)
            result.setdefault(key, []).append(event)
        return result
    p, q = index(p_events), index(q_events)
    duplicates = []
    for version, rows in (("p", p), ("q", q)):
        for key, events in rows.items():
            if len(events) > 1:
                duplicates.append({"version": version, "identity": {field: events[0][field] for field in identity_fields if field in events[0]},
                                   "count": len(events)})
    unmatched = []
    for version, own, other in (("p", p, q), ("q", q, p)):
        for key in own.keys() - other.keys():
            unmatched.append({"version": version, "identity": {field: own[key][0][field] for field in identity_fields if field in own[key][0]}})
    matches = []
    for key in sorted(p.keys() & q.keys(), key=repr):
        if len(p[key]) != 1 or len(q[key]) != 1:
            continue
        left, right = p[key][0], q[key][0]
        matches.append({"identity": {field: left[field] for field in identity_fields if field in left},
                        "p_value": left["value"], "q_value": right["value"],
                        "p_target_reached": left["target_reached"], "q_target_reached": right["target_reached"],
                        "value_equal": _typed(left["value"]) == _typed(right["value"])})
    complete = bool(p and q and matches) and not duplicates and not unmatched
    return {"status": "aligned" if complete else "unresolved", "p_count": len(p_events), "q_count": len(q_events),
            "missing_markers": not p_events or not q_events, "duplicates": duplicates,
            "unmatched": sorted(unmatched, key=lambda row: json.dumps(row, sort_keys=True)), "matches": matches,
            "values_equal": all(row["value_equal"] for row in matches) if complete else None,
            "values_differ": any(not row["value_equal"] for row in matches) if complete else None}


def compare_events(p_events: list, q_events: list, *, scope: dict | None = None,
                   identity_fields=IDENTITY_FIELDS, test_outcomes: dict | None = None) -> dict:
    """Align scoped effect/observation events without global positional zipping.

    Stable anchor/test/input/call/invocation identities are included by default.
    Repeated identical identities are ambiguous, even if their values agree.
    ``test_outcomes`` optionally maps p/q -> {test_name: pass|fail|error|unknown};
    only an explicit pass/fail contrast establishes test discrimination. An
    observation contrast alone says nothing about whether its assertion failed.
    """
    if not isinstance(p_events, list) or not isinstance(q_events, list):
        raise ValueError("events_must_be_lists")
    scope = {} if scope is None else scope
    if not isinstance(scope, dict) or set(scope) - set(IDENTITY_FIELDS):
        raise ValueError("scope_requires_explicit_semantic_identity_fields")
    fields = tuple(identity_fields)
    if (not fields or "anchor" not in fields or len(set(fields)) != len(fields)
            or set(fields) - set(IDENTITY_FIELDS)):
        raise ValueError("invalid_event_identity_fields")
    for value in scope.values():
        _typed(value)
    versions = {"p": [_event(event) for event in p_events], "q": [_event(event) for event in q_events]}
    populated_fields = {key for events in versions.values() for event in events
                        for key in IDENTITY_FIELDS if key in event}
    if populated_fields - set(fields):
        raise ValueError("cannot_drop_present_semantic_identity_fields")
    selected = {v: [event for event in events if _matches(event, scope)] for v, events in versions.items()}
    channels = {}
    for channel in ("effect", "observation"):
        channels[channel] = _align(*([event for event in selected[v] if event["channel"] == channel] for v in ("p", "q")), fields)
    reached = {}
    for version in ("p", "q"):
        effects = [event for event in selected[version] if event["channel"] == "effect"]
        reached[version] = any(event["target_reached"] for event in effects) if effects else None
    reached["both"] = (reached["p"] and reached["q"]) if all(reached[v] is not None for v in ("p", "q")) else None
    outside = {v: [event for event in events if scope and not _matches(event, scope)
                   and event["channel"] == "observation"] for v, events in versions.items()}
    outside_alignment = _align(outside["p"], outside["q"], fields)
    verdicts = []
    if test_outcomes is not None:
        if (not isinstance(test_outcomes, dict) or set(test_outcomes) != {"p", "q"}
                or any(not isinstance(test_outcomes[v], dict) for v in ("p", "q"))):
            raise ValueError("test_outcomes_require_p_and_q_mappings")
        for version in ("p", "q"):
            if any(not isinstance(name, str) or not isinstance(value, str)
                   or value not in {"pass", "fail", "error", "unknown"}
                   for name, value in test_outcomes[version].items()):
                raise ValueError("invalid_test_outcome")
        for name in sorted(set(test_outcomes["p"]) | set(test_outcomes["q"])):
            p, q = (test_outcomes[v].get(name, "unknown") for v in ("p", "q"))
            discriminates = p != q if p in {"pass", "fail"} and q in {"pass", "fail"} else None
            verdicts.append({"test": name, "p": p, "q": q, "discriminates": discriminates,
                             "outside_scoped_test": "test" in scope and _typed(name) != _typed(scope["test"])})
    other = [row for row in verdicts if row["outside_scoped_test"]]
    other_discrimination = (True if any(row["discriminates"] is True for row in other) else
                            False if other and all(row["discriminates"] is False for row in other) else None)
    return {"scope": scope, "identity_fields": list(fields), "target_reached": reached,
            "effect_difference": channels["effect"]["values_differ"],
            "observation_equality": channels["observation"]["values_equal"],
            "channels": channels, "outside_scope_observations": outside_alignment,
            "test_outcomes": verdicts, "other_tests_already_discriminated": other_discrimination,
            "interpretation": "Raw aligned values and supplied test outcomes only; no masking, noninterference, legality or oracle label."}


def _review(value, pair_id, pair_receipt, *, verify_receipts, arbitration=False):
    required = {"reviewer_id", "pair_id", "pair_receipt", "judgments", "receipt"}
    if arbitration:
        required.add("review_receipts")
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("semantic_review_requires_bound_identity_judgments_and_receipt")
    if not isinstance(value["reviewer_id"], str) or not value["reviewer_id"].strip():
        raise ValueError("reviewer_identity_required")
    if value["pair_id"] != pair_id:
        raise ValueError("review_pair_id_mismatch")
    bound = validate_receipt(value["pair_receipt"], verify_file=verify_receipts)
    if bound != pair_receipt:
        raise ValueError("review_pair_receipt_mismatch")
    if not isinstance(value["judgments"], dict) or set(value["judgments"]) != set(SEMANTIC_GATES):
        raise ValueError("review_requires_three_semantic_judgments")
    judgments = {key: _check(row, verify_receipts=verify_receipts) for key, row in value["judgments"].items()}
    receipt = validate_receipt(value["receipt"], verify_file=verify_receipts)
    body = {key: item for key, item in value.items() if key != "receipt"}
    if verify_receipts and _typed(json.loads(Path(receipt["path"]).read_bytes())) != _typed(body):
        raise ValueError("review_content_not_bound_to_receipt")
    return {**value, "judgments": judgments, "receipt": receipt}


def adjudicate_semantic_reviews(pair_id: str, pair_receipt: dict, reviews: list, *,
                               arbitration: dict | None = None, verify_receipts: bool = True) -> dict:
    """Combine two distinct reviewers' semantic judgments; never OR votes.

    Each review's receipt must point to JSON containing that review without its
    own ``receipt`` field. A third review binds the exact initial review receipts
    using ``review_receipts`` and can resolve disagreements with cited evidence.
    Distinct reviewer IDs are checked; real-world independence remains a study
    procedure, not a property that this code can establish.
    """
    if not isinstance(pair_id, str) or not pair_id:
        raise ValueError("pair_identity_required")
    pair_receipt = validate_receipt(pair_receipt, verify_file=verify_receipts)
    if not isinstance(reviews, list) or len(reviews) != 2:
        raise ValueError("exactly_two_initial_semantic_reviews_required")
    first = [_review(row, pair_id, pair_receipt, verify_receipts=verify_receipts) for row in reviews]
    identities = [row["reviewer_id"] for row in first]
    if len(set(identities)) != 2:
        raise ValueError("initial_reviewers_must_have_distinct_identities")
    third = None
    if arbitration is not None:
        third = _review(arbitration, pair_id, pair_receipt, verify_receipts=verify_receipts, arbitration=True)
        if third["reviewer_id"] in identities:
            raise ValueError("arbitrator_must_be_a_third_identity")
        references = third["review_receipts"]
        if not isinstance(references, list) or len(references) != 2:
            raise ValueError("arbitration_requires_both_initial_review_receipts")
        references = [validate_receipt(row, verify_file=verify_receipts) for row in references]
        expected = [row["receipt"] for row in first]
        canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
        if canonical(references) != canonical(expected):
            raise ValueError("arbitration_review_receipts_mismatch")
    judgments, checks = {}, {}
    for topic, gate in SEMANTIC_GATES.items():
        values = [row["judgments"][topic]["status"] for row in first]
        agreed = values[0] == values[1] and values[0] != "unresolved"
        status = values[0] if agreed else "unresolved"
        source = "two_reviewer_agreement" if agreed else "awaiting_third_adjudication"
        evidence = [row["receipt"] for row in first]
        for row in first:
            evidence.extend(row["judgments"][topic]["evidence"])
        if third is not None and not agreed:
            status = third["judgments"][topic]["status"]
            source = "third_reviewer_adjudication" if status != "unresolved" else "third_review_unresolved"
            evidence += [third["receipt"], *third["judgments"][topic]["evidence"]]
        elif third is not None and third["judgments"][topic]["status"] not in {status, "unresolved"}:
            status, source = "unresolved", "arbitration_conflicts_with_initial_agreement"
            evidence += [third["receipt"], *third["judgments"][topic]["evidence"]]
        row = {"status": status, "evidence": evidence, "initial_statuses": values,
               "initial_agreement": values[0] == values[1], "resolution": source}
        judgments[topic] = row
        checks[gate] = row
    return {"pair_id": pair_id, "pair_receipt": pair_receipt, "reviewer_ids": identities,
            "arbitrator_id": third["reviewer_id"] if third else None,
            "judgments": judgments, "gate_checks": checks,
            "unresolved_topics": [key for key, row in judgments.items() if row["status"] == "unresolved"],
            "masking_vote_used": False,
            "identity_scope": "Distinct declared reviewer identities and bound artifacts; independence requires study procedure."}
