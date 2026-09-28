"""Finite execution lanes over the exact, source-only model-offered set.

The model may revise expected values but cannot delete a source witness. No
evaluation labels, execution outcomes, repository names, or case IDs are read.
"""
from copy import deepcopy
import hashlib
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def execution_lanes(requests, validations, static_candidates):
    if len(requests) > 2:
        raise ValueError("At most two frozen requests per case")
    static = {row["id"]: row for row in static_candidates}
    offered, origins = {}, {}
    for request in requests:
        records = request["candidate_records"]
        if len(records) > 64:
            raise ValueError("At most 64 offered witnesses per request")
        for candidate in records:
            identifier = candidate["id"]
            if identifier not in static or canonical(candidate) != canonical(static[identifier]):
                raise ValueError("Offered candidate differs from frozen preparation")
            if identifier in offered:
                raise ValueError("Repeated offered candidate across request budget")
            offered[identifier] = candidate
            origins[identifier] = request["id"]
    if len(offered) > 128:
        raise ValueError("Source hypothesis execution budget exceeded")
    model, model_errors = {}, []
    if len(validations) > 2:
        model_errors.append({"reason": "too_many_validation_artifacts"})
        validations = []
    for validation_index, validation in enumerate(validations):
        if not isinstance(validation, dict) or "accepted" not in validation:
            model_errors.append({"validation": validation_index, "reason": "invalid_validation_document"})
            continue
        accepted = validation.get("accepted", [])
        if not isinstance(accepted, list) or len(accepted) > 32:
            model_errors.append({"validation": validation_index, "reason": "invalid_model_row_budget"})
            continue
        for row_index, candidate in enumerate(accepted):
            if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
                model_errors.append({"validation": validation_index, "row": row_index, "reason": "invalid_model_row"})
                continue
            identifier = candidate["id"]
            def reject(reason):
                model_errors.append({"validation": validation_index, "row": row_index,
                                     "candidate_id": identifier, "reason": reason})
            if identifier not in offered or identifier in model:
                reject("model_candidate_absent_from_offered_or_repeated")
                continue
            original = offered[identifier]
            if any(candidate.get(field) != original.get(field) for field in ("base_test_id", "source_test_ids", "imports")):
                reject("model_changed_source_provenance")
                continue
            if not isinstance(candidate.get("edits"), list) or not all(isinstance(e, dict) for e in candidate["edits"]):
                reject("invalid_model_edits")
                continue
            original_edits = [e for e in original["edits"] if e.get("role") != "semantic_expected"]
            input_edits = [e for e in candidate["edits"] if e.get("role") != "semantic_expected"]
            if canonical(input_edits) != canonical(original_edits):
                reject("model_changed_program_owned_edits")
                continue
            model[identifier] = candidate
    if len(model) > 64:
        raise ValueError("Model revision budget exceeded")
    emitted, ledger = [], []
    for identifier, original in offered.items():
        source = deepcopy(original)
        source["execution_lane"] = "source_q"
        source["static_parent_id"] = identifier
        source["oracle"] = {**source.get("oracle", {}), "applicability": "unknown_hypothesis_requires_independent_evaluation"}
        source.pop("semantic_admission", None)
        accepted = model.get(identifier)
        source["semantic_model_judgment"] = deepcopy(accepted.get("semantic_admission")) if accepted else None
        emitted.append(source)
        row = {"static_parent_id": identifier, "request_id": origins[identifier],
               "source_q_id": identifier, "model_validated": accepted is not None,
               "llm_q_id": None, "status": "source_hypothesis_always_retained"}
        if accepted is not None:
            if canonical(accepted["edits"]) == canonical(original["edits"]):
                row["status"] = "model_retained_same_q_reuses_source_execution"
            else:
                revised = deepcopy(accepted)
                revised["id"] = "llm_" + hashlib.sha256(canonical([identifier, accepted["edits"]]).encode()).hexdigest()[:24]
                revised["execution_lane"] = "llm_q"
                revised["static_parent_id"] = identifier
                revised["generation_parent_candidate_id"] = original.get("parent_candidate_id")
                revised["parent_candidate_id"] = identifier
                revised["semantic_model_judgment"] = revised.pop("semantic_admission", None)
                revised["oracle"] = {**revised.get("oracle", {}), "applicability": "unknown_hypothesis_requires_independent_evaluation"}
                emitted.append(revised)
                row.update(llm_q_id=revised["id"], status="separate_model_expected_revision")
        ledger.append(row)
    return emitted, {"protocol": "relational-execution-lanes-v1", "source_q_budget": 128,
                     "llm_q_budget": 64, "total_execution_budget": 192,
                     "source_q_count": len(offered), "llm_q_count": len(emitted) - len(offered),
                     "same_model_request_budget_as_v4": True, "same_execution_budget_as_v4": False,
                     "grouping": "execution_lane_then_source_file", "model_lane_errors": model_errors,
                     "candidates": ledger}
