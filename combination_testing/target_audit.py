"""Evaluator-only matching of executed witnesses to frozen pilot hypotheses.

A new mismatch elsewhere in the repository must not count as target recall.
Criteria live separately from every generator and inspect only frozen metadata
and completed candidate/reference results. Matching is behavioral attribution,
not a proof of the precise source-level root cause.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from combination_testing.protocol import Packet

TARGETS = Path(__file__).resolve().parents[1] / "configs/combination_targets.json"


def _entries(metadata, key):
    value = metadata.get(key, [])
    result = list(value) if isinstance(value, list) else []
    generators = metadata.get("generators", [])
    if isinstance(generators, dict):
        generators = generators.values()
    for generator in generators:
        if isinstance(generator, dict):
            result += _entries(generator.get("metadata", generator), key)
    return result


def _name_matches(name, test_id):
    return bool(name and (name == test_id or test_id.endswith("::" + name)
                         or test_id.endswith("[" + name + "]")))


def _matching_obligations(metadata, test_id):
    return [item for item in _entries(metadata, "obligations")
            if _name_matches(item.get("id") or item.get("test"), test_id)]


def _matches(spec, metadata, test_id, candidate):
    kind = spec["kind"]
    obligations = _matching_obligations(metadata, test_id)
    if kind.startswith("protocol_"):
        for obligation in obligations:
            packet = Packet.parse(obligation.get("sequence", ""))
            if (packet is None or obligation.get("field") != spec["field"]
                    or obligation.get("op") != spec["op"]):
                continue
            if kind == "protocol_phase":
                valid = (packet.key[-1] != spec["excluded_terminal"]
                         and packet.phase in spec["phase_ids"]
                         and obligation.get("expected") in spec["expected"])
            elif kind == "protocol_text_shortcut":
                valid = (obligation.get("expected") is spec["expected"]
                         and packet.key[:-1] != "0" and bool(packet.text)
                         and bool((packet.modifiers - 1) & ~(1 << spec["shift_bit"])))
            else:
                valid = (bool(packet.alternate) and isinstance(obligation.get("expected"), str)
                         and bool((packet.modifiers - 1) & (1 << spec["represented_modifier_bit"])))
            if valid:
                return {"sequence": obligation["sequence"], "field": obligation["field"],
                        "op": obligation["op"], "expected": obligation.get("expected")}
        return None
    if kind == "path_context":
        for obligation in obligations:
            if obligation.get("operation") == spec["operation"]:
                return {"operation": obligation["operation"], "seed": obligation.get("seed"),
                        "quote": obligation.get("quote")}
        return None
    if candidate.get("relation") != spec.get("relation"):
        return None
    if kind == "host_guest_compound":
        for program in _entries(metadata, "programs"):
            if (test_id.startswith(program["id"] + "/")
                    and re.search(r"\breturn\s*\{", program.get("lifted", ""))
                    and any(binding.get("function") for binding in program.get("bindings", []))):
                return {"program_id": program["id"], "relation": candidate["relation"],
                        "compound_factory": True, "callable_binding": True}
    elif kind == "clone_shared_observer":
        observed, expected = candidate.get("observed"), candidate.get("expected")
        if (isinstance(observed, list) and isinstance(expected, list)
                and len(observed) == len(expected) == 2 and observed[1] == expected[1]
                and isinstance(observed[0], list) and isinstance(expected[0], list)
                and len(observed[0]) == len(expected[0])):
            comparisons = [(a, b) for a, b in zip(observed[0], expected[0])
                           if isinstance(a, dict) and isinstance(b, dict)]
            if any(actual != wanted for actual, wanted in comparisons):
                return {"relation": candidate["relation"], "shared_observer_trace_disagrees": True,
                        "source_state_stable": True}
    elif kind == "recursive_nonidentity":
        for obligation in obligations:
            donor = obligation.get("donor")
            if donor and donor.get("proof") == "object spread followed by constant property writes":
                return {"relation": candidate["relation"], "donor": donor["path"],
                        "donor_line": donor.get("line"), "nonidentity_shape": donor["proof"]}
    return None


def audit_known_target(case_id, metadata, compared_rows, candidate_tests, *, targets_path=TARGETS):
    targets_path = Path(targets_path)
    data = json.loads(targets_path.read_text())
    spec = data["cases"].get(case_id)
    witnesses, additional = [], []
    if spec:
        for compared in compared_rows:
            if not compared.get("confirmed_witness"):
                continue
            test_id = compared["id"]
            evidence = _matches(spec, metadata, test_id, candidate_tests[test_id])
            if evidence:
                witnesses.append({"id": test_id, "evidence": evidence})
            else:
                additional.append(test_id)
    return {"detected": bool(witnesses), "criterion": spec,
            "criteria_sha256": hashlib.sha256(targets_path.read_bytes()).hexdigest(),
            "matching_witnesses": witnesses, "additional_differential_candidates": additional,
            "scope": "Post-generation evaluator-only behavioral match to the known pilot; unrelated mismatches do not count as target detection."}
