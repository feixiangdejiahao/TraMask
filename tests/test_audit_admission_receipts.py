"""Independent audits must preserve denominators and detect content tampering."""
import json

import pytest

from scripts import audit_admission_receipts as audit


def request():
    return dict(id="frozen", system="Judge source", prompt=json.dumps({"modified_test": "assert value == 2"}),
                max_tokens=1024, check_ids=["P", "Q0"], coverage={"core_complete": True})


def test_actual_request_identity_includes_every_variable_dispatch_option():
    base = request()
    identity = audit.request_identity(base)
    for change in ({"thinking": "enabled"}, {"reasoning_effort": "low"}, {"max_tokens": 2048},
                   {"system": "Other instructions"}, {"prompt": "Other source"}):
        assert audit.request_identity({**base, **change}) != identity
    assert audit.request_identity({**base, "candidate_id": "local metadata"}) == identity


def test_all_model_support_does_not_admit_incomplete_source_obligations():
    req = request()
    req["coverage"]["core_complete"] = False
    response = '{"P":"supported","Q0":"supported"}'
    assert audit.parsed_verdict(req, response, "stop", "guarded") == ("unknown", False)
    assert audit.parsed_verdict(req, response, "length", "guarded") == ("unknown", False)
    assert audit.parsed_verdict(req, '{"P":"supported"}', "stop", "guarded") == ("unknown", False)


@pytest.mark.parametrize("payload", [
    {"checks": {"nested": {"native_evidence": []}}},
    {"issue": "invalid_oracle_or_setup"},
    {"issue": "This full independent review reason must never reach provider prompts."},
    {"source": "Runtime native message with concrete output sufficiently long to be identifiable."},
])
def test_prompt_audit_checks_content_instead_of_exclusion_flags(payload):
    req = {**request(), "prompt": json.dumps(payload), "no_evaluation_labels": True}
    truth = [dict(candidate_id="n", classification="invalid_oracle_or_setup",
                  reason="This full independent review reason must never reach provider prompts.")]
    record = dict(native_evidence=[dict(tests=[dict(id="test", message=
        "Runtime native message with concrete output sufficiently long to be identifiable.")])])
    with pytest.raises(ValueError, match="Prompt exclusion violation"):
        audit.prompt_exclusions(req, truth, record)


def test_frontier_selection_loss_unknown_and_false_alarm_denominators_are_separate():
    baseline = dict(counts={"trials": 3}, positive_witnesses=[
        dict(case="A", candidate_id="p1", classification="valid_complete_issue_witness", occurrence_keys=["p1"]),
        dict(case="B", candidate_id="p2", classification="valid_complete_issue_witness", occurrence_keys=["p2"])],
        development_reviews=[dict(case="A", candidate_id="mixed", occurrence_keys=["mixed"],
            classification="invalid_oracle_or_setup",
            initial_failure_classification="mixed_valid_early_signal_invalid_complete_oracle")])
    heldout = dict(reviews=[dict(key="C:0:n", classification="invalid_oracle_or_setup",
                                initial_failure_classification="confirmed_false_initial_alarm")])
    decisions = [dict(key=key, decision=dict(status=status, alarm_eligible=status == "semantic_supported"))
                 for key, status in [("p1", "semantic_supported"), ("mixed", "semantic_rejected"),
                                     ("C:0:n", "unknown"), ("unlabeled", "semantic_supported")]]
    result = audit.summarize_truth(baseline, heldout, decisions)
    assert result["positive"]["outcomes"] == {"admitted": 1, "not_selected": 1}
    assert result["recall"]["selection_coverage"] == 0.5
    assert result["recall"]["gate_recall_conditional_on_selection"] == 1
    assert result["recall"]["independently_confirmed_admitted_task_coverage"]["numerator"] == 1
    assert result["recall"]["independently_confirmed_admitted_task_coverage"]["denominator"] == 3
    assert result["heldout"]["labels"]["initial_failure_classification"]["confirmed_false_initial_alarm"] == {"unknown": 1}
    assert result["frontier"]["admitted_without_existing_truth"] == 1
    assert result["frontier"]["population_false_positive_total"] is None


def test_verifier_detects_artifact_mutation(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text("{}")
    sealed = audit.frozen(path)
    audit.verify(sealed)
    path.write_text('{"changed":true}')
    with pytest.raises(ValueError, match="Changed artifact"):
        audit.verify(sealed)
