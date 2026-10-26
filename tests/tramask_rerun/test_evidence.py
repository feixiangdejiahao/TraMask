"""Evidence and alignment boundary checks; no subject execution or providers."""
import hashlib
import json

import pytest

from tramask_rerun.evidence import (
    CHECKS, SEMANTIC_GATES, adjudicate_semantic_reviews, compare_events,
    derive_classification, validate_receipt,
)


def artifact(path, body):
    raw = json.dumps(body, sort_keys=True).encode()
    path.write_bytes(raw)
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def receipt(tmp_path):
    return artifact(tmp_path / "evidence.json", {"source": "synthetic execution evidence"})


def checks_through(number, receipt):
    return {key: {"status": "pass", "evidence": [receipt]} for key in CHECKS[:number]}


@pytest.mark.parametrize("number,classification,flags", [
    (5, "unresolved", (False, False, False)),
    (6, "masking_candidate", (True, False, False)),
    (8, "confirmed_behavioral_masking", (True, True, False)),
    (9, "oracle_qualified_repair", (True, True, True)),
])
def test_levels_are_exact_check_conjunctions(number, classification, flags, receipt):
    result = derive_classification(checks_through(number, receipt))
    assert result["classification"] == classification
    assert tuple(result[key] for key in ("candidate", "confirmed", "oracle_qualified")) == flags
    assert not result["count_as_nonmask"]


def test_pass_and_fail_need_actual_evidence_and_mutated_artifacts_are_rejected(receipt):
    for status in ("pass", "fail"):
        with pytest.raises(ValueError, match="resolved_check_requires_evidence"):
            derive_classification({"E1": {"status": status, "evidence": []}})
    invalid = {**receipt, "sha256": "0" * 64}
    with pytest.raises(ValueError, match="artifact_receipt_mismatch"):
        derive_classification({"E1": {"status": "pass", "evidence": [invalid]}})


def test_failed_search_keeps_candidate_and_unresolved_witness(receipt):
    checks = checks_through(6, receipt)
    checks["E7"] = {"status": "fail", "evidence": [receipt], "reason": "five searched edits were illegal"}
    checks["E8"] = {"status": "fail", "evidence": [receipt], "reason": "no successful edit within budget"}
    result = derive_classification(checks)
    assert result["candidate"] and result["classification"] == "masking_candidate"
    assert result["witness_status"] == "unresolved" and not result["count_as_nonmask"]
    with pytest.raises(ValueError, match="finite_search_failure"):
        derive_classification(checks, nonmask_findings={"no_witness_found": checks["E8"]})


def test_nonmask_requires_explicit_evidence_not_missing_markers(receipt):
    assert derive_classification({})["classification"] == "unresolved"
    checks = {"E2": {"status": "fail", "evidence": [receipt]}}
    assert derive_classification(checks)["classification"] == "unresolved"
    finding = {"target_bypass": {"status": "pass", "evidence": [receipt]}}
    result = derive_classification(checks, nonmask_findings=finding)
    assert result["classification"] == "target_bypass" and result["count_as_nonmask"]
    conflict = derive_classification(checks_through(8, receipt), nonmask_findings=finding)
    assert conflict["classification"] == "unresolved_conflicting_evidence"
    assert not conflict["confirmed"] and not conflict["count_as_nonmask"]


@pytest.mark.parametrize("category", ["invalid_counterfactual", "incomplete_evidence"])
def test_invalid_or_incomplete_evidence_is_not_counted_negative(category, receipt):
    result = derive_classification({}, nonmask_findings={category: {"status": "pass", "evidence": [receipt]}})
    assert result["classification"] == category and result["disposition"] == "unresolved"
    assert not result["count_as_nonmask"]


def event(channel="effect", value=1, *, test="target", input="stimulus", invocation=1, reached=True):
    return {"channel": channel, "anchor": channel + "-anchor", "test": test,
            "input": input, "invocation": invocation, "value": value, "target_reached": reached}


def test_alignment_uses_semantic_identity_not_global_order():
    p = [event(value=1, invocation=1), event(value=2, invocation=2), event("observation", [])]
    q = [event("observation", []), event(value=2, invocation=2), event(value=9, invocation=1)]
    result = compare_events(p, q)
    assert result["target_reached"]["both"] is True
    assert result["effect_difference"] is True and result["observation_equality"] is True
    matches = result["channels"]["effect"]["matches"]
    assert [(row["identity"]["invocation"], row["value_equal"]) for row in matches] == [(1, False), (2, True)]


def test_repeated_unidentified_events_are_unresolved_even_when_values_equal():
    events = [event(), event()]
    for row in events:
        row.pop("invocation")
    result = compare_events(events, events)
    assert result["effect_difference"] is None and result["observation_equality"] is None
    assert result["channels"]["effect"]["duplicates"]


def test_missing_or_unmatched_markers_never_become_observation_equality():
    assert compare_events([], [])["observation_equality"] is None
    result = compare_events([event("observation", 0)], [event("observation", 0, input="other")])
    assert result["observation_equality"] is None
    assert len(result["channels"]["observation"]["unmatched"]) == 2


def test_caller_cannot_drop_test_identity_to_force_cross_test_alignment():
    with pytest.raises(ValueError, match="cannot_drop_present_semantic_identity"):
        compare_events([event(test="a")], [event(test="b")], identity_fields=("anchor",))


@pytest.mark.parametrize("left,right", [(True, 1), (False, 0), (1, 1.0), (0.0, -0.0), ({"value": True}, {"value": 1}), ([1, 2], [2, 1])])
def test_exact_json_values_keep_types_and_order(left, right):
    result = compare_events([event("observation", left)], [event("observation", right)])
    assert result["observation_equality"] is False


def test_object_field_order_does_not_matter_and_nonfinite_values_rejected():
    result = compare_events([event("observation", {"a": 1, "b": 2})], [event("observation", {"b": 2, "a": 1})])
    assert result["observation_equality"] is True
    with pytest.raises(ValueError, match="nonfinite"):
        compare_events([event(value=float("nan"))], [])


def test_scoped_witness_does_not_hide_other_test_discrimination():
    p = [event(value=0), event("observation", []), event("observation", 0, test="other")]
    q = [event(value=1), event("observation", []), event("observation", 1, test="other")]
    result = compare_events(p, q, scope={"test": "target", "input": "stimulus"},
        test_outcomes={"p": {"target": "pass", "other": "pass"}, "q": {"target": "pass", "other": "fail"}})
    assert result["effect_difference"] and result["observation_equality"]
    assert result["outside_scope_observations"]["values_differ"]
    assert result["other_tests_already_discriminated"] is True
    no_verdict = compare_events(p, q, scope={"test": "target"})
    assert no_verdict["other_tests_already_discriminated"] is None


def test_test_errors_do_not_count_as_assertion_discrimination():
    result = compare_events([], [], scope={"test": "selected"},
        test_outcomes={"p": {"other": "pass"}, "q": {"other": "error"}})
    assert result["other_tests_already_discriminated"] is None


def review(tmp_path, identity, pair_receipt, receipt, statuses=None, *, pair_id="pair", initial=None):
    statuses = statuses or {}
    body = {"reviewer_id": identity, "pair_id": pair_id, "pair_receipt": pair_receipt,
            "judgments": {topic: {"status": statuses.get(topic, "pass"), "evidence": [receipt]}
                          for topic in SEMANTIC_GATES}}
    if initial is not None:
        body["review_receipts"] = [row["receipt"] for row in initial]
    return {**body, "receipt": artifact(tmp_path / (identity + ".json"), body)}


def test_two_reviewers_provide_semantic_gate_components_not_mask_vote(tmp_path, receipt):
    pair = artifact(tmp_path / "pair.json", {"id": "pair", "checkpoint": "frozen"})
    reviews = [review(tmp_path, name, pair, receipt) for name in ("a", "b")]
    result = adjudicate_semantic_reviews("pair", pair, reviews)
    assert set(result["gate_checks"]) == {"E3", "E7", "E9"}
    assert all(row["status"] == "pass" for row in result["judgments"].values())
    assert result["masking_vote_used"] is False and "confirmed_mask" not in result
    # Semantic components alone cannot establish the other execution checks.
    assert derive_classification(result["gate_checks"])["classification"] == "unresolved"


def test_review_disagreement_needs_distinct_bound_third_adjudication(tmp_path, receipt):
    pair = artifact(tmp_path / "pair.json", {"id": "pair"})
    reviews = [review(tmp_path, "a", pair, receipt),
               review(tmp_path, "b", pair, receipt, {"context_legality": "fail"})]
    unresolved = adjudicate_semantic_reviews("pair", pair, reviews)
    assert unresolved["gate_checks"]["E7"]["status"] == "unresolved"
    third = review(tmp_path, "c", pair, receipt, {"context_legality": "fail"}, initial=reviews)
    resolved = adjudicate_semantic_reviews("pair", pair, reviews, arbitration=third)
    assert resolved["gate_checks"]["E7"]["status"] == "fail"
    assert resolved["gate_checks"]["E7"]["resolution"] == "third_reviewer_adjudication"


def test_review_identity_pair_and_content_binding_are_checked(tmp_path, receipt):
    pair = artifact(tmp_path / "pair.json", {"id": "pair"})
    a = review(tmp_path, "a", pair, receipt)
    with pytest.raises(ValueError, match="distinct_identities"):
        adjudicate_semantic_reviews("pair", pair, [a, a])
    wrong_pair = review(tmp_path, "b", pair, receipt, pair_id="different")
    with pytest.raises(ValueError, match="pair_id_mismatch"):
        adjudicate_semantic_reviews("pair", pair, [a, wrong_pair])
    tampered = review(tmp_path, "b", pair, receipt)
    tampered["judgments"]["oracle_validity"]["status"] = "fail"
    with pytest.raises(ValueError, match="content_not_bound"):
        adjudicate_semantic_reviews("pair", pair, [a, tampered])


def test_arbitration_must_bind_exact_initial_reviews_and_third_identity(tmp_path, receipt):
    pair = artifact(tmp_path / "pair.json", {"id": "pair"})
    reviews = [review(tmp_path, name, pair, receipt) for name in ("a", "b")]
    third = review(tmp_path, "c", pair, receipt, initial=reviews)
    body = {key: value for key, value in third.items() if key != "receipt"}
    body["review_receipts"] = [reviews[0]["receipt"], reviews[0]["receipt"]]
    third = {**body, "receipt": artifact(tmp_path / "c.json", body)}
    with pytest.raises(ValueError, match="arbitration_review_receipts_mismatch"):
        adjudicate_semantic_reviews("pair", pair, reviews, arbitration=third)


def test_masking_vote_is_not_accepted_as_semantic_review(tmp_path, receipt):
    pair = artifact(tmp_path / "pair.json", {"id": "pair"})
    a, b = (review(tmp_path, name, pair, receipt) for name in ("a", "b"))
    b["confirmed_mask"] = True
    with pytest.raises(ValueError, match="semantic_review_requires"):
        adjudicate_semantic_reviews("pair", pair, [a, b])
