"""Falsify transport predicates using independently existing test assertions.

This checks a necessary condition, not contract soundness. No counterexample in
a sparse suite means ``not_falsified``; it never means ``proved``. The checker
does not consult generated-test execution, reference patches, or target labels.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib

from combination_testing.protocol import Packet, canonical


def _equal(left, right):
    """Match the generated probe's normalization of tuple/list field values."""
    def normalize(value):
        if isinstance(value, (tuple, list)):
            return [normalize(item) for item in value]
        return value
    return normalize(left) == normalize(right)


def _contains(container, member):
    try:
        return member in container
    except (TypeError, ValueError):
        # A known literal unable to contain a member cannot satisfy ``in``.
        return False


def _finite_values(fact):
    if fact["op"] == "eq":
        return [fact["expected"]]
    if fact["op"] == "one_of" and isinstance(fact["expected"], (list, tuple, set)):
        return list(fact["expected"])
    return None


def _satisfies(value, fact):
    if fact["op"] == "eq":
        return _equal(value, fact["expected"])
    if fact["op"] == "one_of":
        return any(_equal(value, option) for option in fact["expected"])
    if fact["op"] == "contains":
        return _contains(value, fact["expected"])
    return None


def contradictory(left, right):
    """Prove incompatibility of two supported positive observation predicates.

    Different positive memberships are compatible. At least one finite value
    constraint is required to establish that the predicates cannot both hold.
    Unsupported operations are unknown, never negative membership evidence.
    """
    supported = {"eq", "one_of", "contains"}
    if left.get("op") not in supported or right.get("op") not in supported:
        return False
    left_values, right_values = _finite_values(left), _finite_values(right)
    if left_values is not None:
        return bool(left_values) and all(_satisfies(value, right) is False for value in left_values)
    if right_values is not None:
        return bool(right_values) and all(_satisfies(value, left) is False for value in right_values)
    return False


def audit_predicate(predicate, facts):
    """Return existing-test counterexamples to ``predicate.permits``.

    ``facts`` are the dictionaries in ``generate_protocol(...)[metadata][facts]``.
    Modifier bits are individual input coordinates, matching the generator.
    The audit does not call, import, or execute any subject implementation.
    """
    facts = [fact.as_dict() if hasattr(fact, "as_dict") else fact for fact in facts]
    parsed, ignored = [], []
    for index, fact in enumerate(facts):
        packet = Packet.parse(fact.get("sequence"))
        if packet is None or packet.modifiers < 1 or fact.get("op") not in {"eq", "one_of", "contains"}:
            ignored.append({"index": index, "source": fact.get("source", {}),
                            "reason": "unsupported_packet_or_assertion"})
            continue
        if fact["op"] == "one_of" and not isinstance(fact.get("expected"), (list, tuple, set)):
            ignored.append({"index": index, "source": fact.get("source", {}),
                            "reason": "nonfinite_one_of"})
            continue
        parsed.append((fact, packet))
    width = max([1, *[(packet.modifiers - 1).bit_length() for _, packet in parsed]])
    coordinates = ["key_representation", "alternate_codes",
                   *[f"modifier_bit_{i}" for i in range(width)], "event_type", "associated_text"]
    groups = defaultdict(list)
    for fact, packet in parsed:
        groups[fact["field"]].append((fact, packet, packet.vector(width)))
    counterexamples, errors, calls = [], [], {}
    compared = admitted = compatible = unresolved = 0
    for field, group in sorted(groups.items()):
        for source_fact, source_packet, source_vector in group:
            for followup_fact, followup_packet, followup_vector in group:
                changed = [i for i, (a, b) in enumerate(zip(source_vector, followup_vector)) if a != b]
                if len(changed) != 1:
                    continue
                compared += 1
                cache_key = canonical((field, source_fact["op"], source_fact["expected"],
                                       source_packet.as_dict(), followup_packet.as_dict()))
                if cache_key not in calls:
                    try:
                        calls[cache_key] = predicate.permits(
                            field=field, op=source_fact["op"], expected=source_fact["expected"],
                            source=source_packet.as_dict(), followup=followup_packet.as_dict())
                    except Exception as exc:
                        calls[cache_key] = None
                        errors.append({"type": type(exc).__name__, "message": str(exc),
                                       "source": source_fact, "followup": followup_fact})
                permitted = calls[cache_key]
                if permitted is not True:
                    continue
                admitted += 1
                if contradictory(source_fact, followup_fact):
                    example = {"field": field, "changed_coordinate": coordinates[changed[0]],
                               "source": source_fact, "followup": followup_fact,
                               "source_packet": source_packet.as_dict(),
                               "followup_packet": followup_packet.as_dict(),
                               "reason": "admitted_transport_contradicts_existing_assertion"}
                    example["id"] = hashlib.sha256(canonical(example).encode()).hexdigest()[:16]
                    counterexamples.append(example)
                elif _finite_values(source_fact) is not None or _finite_values(followup_fact) is not None:
                    compatible += 1
                else:
                    unresolved += 1
    return {"status": "rejected" if counterexamples else "error" if errors else "not_falsified",
            "method": "existing_test_one_coordinate_falsification",
            "facts": len(facts), "supported_facts": len(parsed), "ignored": ignored,
            "ordered_pairs_compared": compared, "unique_predicate_calls": len(calls),
            "admitted_pairs": admitted, "compatible_pairs": compatible,
            "unresolved_pairs": unresolved, "counterexamples": counterexamples,
            "predicate_errors": errors,
            "soundness_claim": False, "subject_execution": False, "reference_inputs": False}
