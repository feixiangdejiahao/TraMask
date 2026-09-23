from combination_testing.contract_checks import audit_predicate, contradictory
from combination_testing.contracts import Predicate


def fact(sequence, op, expected, line=1):
    return {"sequence": sequence, "field": "result", "op": op,
            "expected": expected, "source": {"path": "test_wire.py", "line": line}}


def permit_all():
    return Predicate("def preserves(field, op, expected, source, followup):\n    return True\n")


def test_positive_memberships_do_not_imply_negative_membership():
    assert not contradictory({"op": "contains", "expected": "first"},
                             {"op": "contains", "expected": "second"})
    result = audit_predicate(permit_all(), [fact("\x1b[42;1u", "contains", "first"),
                                          fact("\x1b[42;2u", "contains", "second", 2)])
    assert result["status"] == "not_falsified"
    assert result["unresolved_pairs"] == 2


def test_closed_container_equality_can_refute_membership():
    left = {"op": "contains", "expected": "first"}
    assert contradictory(left, {"op": "eq", "expected": ["second"]})
    assert contradictory({"op": "eq", "expected": ["second"]}, left)
    assert not contradictory(left, {"op": "eq", "expected": ["first", "second"]})


def test_one_of_constraints_are_compared_by_intersection():
    assert not contradictory({"op": "one_of", "expected": [1, 2]},
                             {"op": "one_of", "expected": [2, 3]})
    assert contradictory({"op": "one_of", "expected": [1, 2]},
                         {"op": "one_of", "expected": [3, 4]})
    assert contradictory({"op": "eq", "expected": 1},
                         {"op": "one_of", "expected": [3, 4]})
    assert not contradictory({"op": "eq", "expected": [1, 2]},
                             {"op": "eq", "expected": (1, 2)})


def test_existing_test_counterexample_keeps_both_source_spans():
    result = audit_predicate(permit_all(), [fact("\x1b[42;1:1u", "eq", "start", 12),
                                          fact("\x1b[42;1:2u", "eq", "repeat", 23)])
    assert result["status"] == "rejected"
    assert result["ordered_pairs_compared"] == 2
    assert len(result["counterexamples"]) == 2
    example = result["counterexamples"][0]
    assert example["changed_coordinate"] == "event_type"
    assert example["source"]["source"]["line"] == 12
    assert example["followup"]["source"]["line"] == 23
    assert example["source_packet"]["phase"] == "1"


def test_modifier_bits_are_coordinates_and_two_bit_changes_are_excluded():
    # Wire values 1->4 change both modifier bits; 4->3 changes one.
    result = audit_predicate(permit_all(), [fact("\x1b[42;1u", "eq", "none"),
                                          fact("\x1b[42;4u", "eq", "both"),
                                          fact("\x1b[42;3u", "eq", "second")])
    assert result["ordered_pairs_compared"] == 4
    assert all(e["changed_coordinate"].startswith("modifier_bit_") for e in result["counterexamples"])


def test_predicate_rejection_does_not_become_a_counterexample():
    predicate = Predicate('''def preserves(field, op, expected, source, followup):
    return source["phase"] == followup["phase"]
''')
    result = audit_predicate(predicate, [fact("\x1b[42;1:1u", "eq", "start"),
                                         fact("\x1b[42;1:2u", "eq", "repeat")])
    assert result["status"] == "not_falsified"
    assert result["admitted_pairs"] == 0
    assert result["soundness_claim"] is False


def test_predicate_errors_are_inconclusive_not_successful_validation():
    predicate = Predicate('''def preserves(field, op, expected, source, followup):
    return source["missing"] == followup["missing"]
''')
    result = audit_predicate(predicate, [fact("\x1b[42;1:1u", "eq", "start"),
                                         fact("\x1b[42;1:2u", "eq", "repeat")])
    assert result["status"] == "error"
    assert result["predicate_errors"]
    assert not result["counterexamples"]


def test_empty_or_singleton_corpus_is_not_falsified_not_proved():
    result = audit_predicate(permit_all(), [fact("\x1b[42u", "eq", 1)])
    assert result["status"] == "not_falsified"
    assert result["ordered_pairs_compared"] == 0
    assert result["soundness_claim"] is False
