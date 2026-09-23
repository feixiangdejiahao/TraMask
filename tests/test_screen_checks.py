from combination_testing.screen_checks import calibration_proposals, classify_transport, entails


def fact(sequence, op, expected, line=1, field="result"):
    return {"sequence": sequence, "field": field, "op": op, "expected": expected,
            "source": {"path": "test_wire.py", "line": line, "assertion": "existing assertion"}}


def proposal(sequence, op, expected, field="result"):
    return {"sequence": sequence, "field": field, "op": op, "expected": expected}


def test_exact_followup_refutation_preserves_evidence():
    existing = fact("\x1b[42;1u", "eq", "old", 12)
    result = classify_transport(proposal("\x1b[42u", "eq", "new"), [existing])
    assert result["classification"] == "contradicted"
    assert result["evidence"][0]["fact"]["source"]["line"] == 12
    assert result["exact_packet_matches"] == 1


def test_different_followup_and_different_field_do_not_refute():
    existing = [fact("\x1b[42u", "eq", "old"),
                fact("\x1b[43u", "eq", "old", field="other")]
    assert classify_transport(proposal("\x1b[43u", "eq", "new"), existing)["classification"] == "unknown"


def test_memberships_need_closed_collection_for_negative_evidence():
    target = proposal("\x1b[42u", "contains", "first")
    assert classify_transport(target, [fact("\x1b[42u", "contains", "second")])["classification"] == "unknown"
    assert classify_transport(target, [fact("\x1b[42u", "contains", "first")])["classification"] == "supported"
    assert classify_transport(target, [fact("\x1b[42u", "eq", ["second"])])["classification"] == "contradicted"
    assert classify_transport(target, [fact("\x1b[42u", "eq", ["first", "second"])])["classification"] == "supported"


def test_support_requires_entailment_not_nonempty_intersection():
    existing = [fact("\x1b[42u", "one_of", [1, 2])]
    assert classify_transport(proposal("\x1b[42u", "one_of", [2, 3]), existing)["classification"] == "unknown"
    assert classify_transport(proposal("\x1b[42u", "one_of", [1, 2, 3]), existing)["classification"] == "supported"
    assert classify_transport(proposal("\x1b[42u", "one_of", [3, 4]), existing)["classification"] == "contradicted"


def test_contradiction_takes_precedence_and_marks_conflicting_facts():
    target = proposal("\x1b[42u", "eq", 1)
    result = classify_transport(target, [fact("\x1b[42u", "eq", 1), fact("\x1b[42u", "eq", 2)])
    assert result["classification"] == "contradicted"
    assert result["conflicting_existing_evidence"]


def test_calibration_balances_positive_and_negative_examples_with_spans():
    facts = [fact("\x1b[42;1:1u", "eq", "first", 1),
             fact("\x1b[42;1:2u", "eq", "second", 2),
             fact("\x1b[43;1:1u", "eq", "first", 3)]
    rows = calibration_proposals(facts, max_each=1)
    assert len(rows) == 2
    assert {row["expected_admission"] for row in rows} == {True, False}
    assert all(row["source_assertion"] and row["donor_sources"] for row in rows)
    assert all(row["calibration_evidence"] for row in rows)
    assert len({row["id"] for row in rows}) == len(rows)
    assert rows == calibration_proposals(list(reversed(facts)), max_each=1)


def test_two_changed_modifier_bits_are_not_one_coordinate():
    facts = [fact("\x1b[42;1u", "eq", "none"), fact("\x1b[42;4u", "eq", "both")]
    assert calibration_proposals(facts) == []


def test_positive_membership_difference_never_becomes_negative_calibration():
    facts = [fact("\x1b[42;1u", "contains", "first"), fact("\x1b[42;2u", "contains", "second")]
    assert calibration_proposals(facts) == []


def test_membership_can_be_supported_by_all_finite_collection_alternatives():
    observed = {"op": "one_of", "expected": [["x", "y"], ["x"]]}
    assert entails(observed, {"op": "contains", "expected": "x"})
    assert not entails(observed, {"op": "contains", "expected": "y"})
