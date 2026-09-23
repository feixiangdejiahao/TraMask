"""Existing-test consistency and calibration for finite proposal screening.

Only already extracted test assertions are read. A positive membership does not
describe the complete observed collection. Calibration labels/evidence are for
evaluation and must be omitted from the model request.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib

from combination_testing.contract_checks import _finite_values, _satisfies, contradictory
from combination_testing.protocol import Packet, canonical


def _facts(facts):
    return [fact.as_dict() if hasattr(fact, "as_dict") else fact for fact in facts]


def _packet_dict(packet):
    if isinstance(packet, Packet):
        return packet.as_dict()
    if isinstance(packet, dict):
        try:
            return Packet(str(packet["key"]), tuple(packet.get("alternate", ())),
                          int(packet.get("modifiers", 1)), str(packet.get("phase", "1")),
                          tuple(packet.get("text", ()))).as_dict()
        except (KeyError, TypeError, ValueError):
            return None
    parsed = Packet.parse(packet)
    return parsed.as_dict() if parsed else None


def entails(observed, transported):
    """Whether an existing assertion proves the transported predicate true."""
    if observed.get("op") not in {"eq", "one_of", "contains"} or transported.get("op") not in {"eq", "one_of", "contains"}:
        return False
    values = _finite_values(observed)
    if values is not None:
        return bool(values) and all(_satisfies(value, transported) is True for value in values)
    # Membership of the same value entails itself; another positive membership
    # says nothing about whether the transported member occurs in the container.
    return (observed["op"] == transported["op"] == "contains"
            and observed["expected"] == transported["expected"])


def classify_transport(proposal, facts):
    """Classify against assertions on the exact decoded follow-up packet.

    ``supported`` is stronger than mere non-contradiction: at least one existing
    assertion must entail the transported predicate. ``unknown`` is not an
    admission. Any explicit contradiction takes precedence over support.
    """
    destination = _packet_dict(proposal.get("followup_packet", proposal.get("sequence")))
    matching, support, refutation = [], [], []
    if destination is not None:
        for fact in _facts(facts):
            if fact.get("field") != proposal.get("field"):
                continue
            if _packet_dict(fact.get("sequence")) != destination:
                continue
            matching.append(fact)
            if contradictory(proposal, fact):
                refutation.append(fact)
            elif entails(fact, proposal):
                support.append(fact)
    classification = "contradicted" if refutation else "supported" if support else "unknown"
    return {"classification": classification, "followup_packet": destination,
            "exact_packet_matches": len(matching),
            "evidence": [{"role": "refutes_transport", "fact": fact} for fact in refutation]
                        + [{"role": "supports_transport", "fact": fact} for fact in support],
            "unresolved_evidence": [fact for fact in matching if fact not in refutation and fact not in support],
            "conflicting_existing_evidence": bool(refutation and support)}


def calibration_proposals(facts, max_each=8):
    """Mine up to max_each supported and contradicted one-coordinate cases.

    The returned rows have normal transport fields. ``expected_admission`` and
    ``calibration_evidence`` are evaluation-only. Selection cycles over distinct
    observed fields/coordinates/operators, without case identifiers or names.
    """
    if not isinstance(max_each, int) or max_each < 0:
        raise ValueError("max_each must be a nonnegative integer")
    facts = sorted(_facts(facts), key=canonical)
    parsed = [(fact, Packet.parse(fact.get("sequence"))) for fact in facts]
    parsed = [(fact, packet) for fact, packet in parsed if packet is not None and packet.modifiers >= 1]
    width = max([1, *[(packet.modifiers - 1).bit_length() for _, packet in parsed]])
    coordinates = ["key_representation", "alternate_codes",
                   *[f"modifier_bit_{i}" for i in range(width)], "event_type", "associated_text"]
    groups = defaultdict(list)
    for fact, packet in parsed:
        groups[fact["field"]].append((fact, packet, packet.vector(width)))
    unique = {}
    for field, group in sorted(groups.items()):
        for source, original, original_vector in group:
            for donor, followup, followup_vector in group:
                changed = [i for i, (a, b) in enumerate(zip(original_vector, followup_vector)) if a != b]
                if len(changed) != 1:
                    continue
                proposal = {"sequence": followup.encode(), "field": field,
                            "op": source["op"], "expected": source["expected"],
                            "seed": source["sequence"], "source_packet": original.as_dict(),
                            "followup_packet": followup.as_dict(),
                            "changed_coordinate": coordinates[changed[0]],
                            "source_assertion": source.get("source", {}),
                            "donor_sources": [donor.get("source", {})],
                            "relation": "existing_test_calibration"}
                label = classify_transport(proposal, facts)
                if label["classification"] == "unknown" or label["conflicting_existing_evidence"]:
                    continue
                # The fingerprint excludes the answer: IDs cannot encode labels.
                identity = canonical([proposal["source_packet"], proposal["followup_packet"],
                                      field, proposal["op"], proposal["expected"]])
                if identity in unique:
                    continue
                proposal["id"] = "cal_" + hashlib.sha256(identity.encode()).hexdigest()[:16]
                proposal["expected_admission"] = label["classification"] == "supported"
                proposal["calibration_evidence"] = label["evidence"]
                unique[identity] = proposal
    selected = []
    for expected in (True, False):
        buckets = defaultdict(list)
        for identity, proposal in sorted(unique.items()):
            if proposal["expected_admission"] == expected:
                bucket = (proposal["field"], proposal["changed_coordinate"], proposal["op"])
                buckets[bucket].append(proposal)
        queues = [deque(rows) for _, rows in sorted(buckets.items())]
        count = 0
        while any(queues) and count < max_each:
            for queue in queues:
                if queue and count < max_each:
                    selected.append(queue.popleft())
                    count += 1
    return selected
