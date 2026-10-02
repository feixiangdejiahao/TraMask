"""Independent audits must preserve denominators and detect content tampering."""
import hashlib
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


def test_compact_nested_schema_and_partial_source_rule_are_explicit():
    req = request()
    req["coverage"] = {"source_sites_complete": False, "core_complete": False}
    complete = {"basis": "All reachable predicates follow from the fixed contract.",
                "judgments": {"P": "supported", "Q0": "supported"}}
    assert audit.parsed_verdict(req, json.dumps(complete), "stop", "compact") == ("semantic_supported", True)
    assert audit.parsed_verdict(req, json.dumps(complete), "length", "compact") == ("unknown", False)
    for malformed in ({"judgments": complete["judgments"]}, {**complete, "extra": 1},
                      {**complete, "basis": []}, {**complete, "judgments": {"P": "supported"}},
                      {**complete, "judgments": {"P": "supported", "Q0": "probably"}}):
        assert audit.parsed_verdict(req, json.dumps(malformed), "stop", "compact") == ("unknown", False)
    assert audit.parsed_verdict(req, json.dumps({**complete, "judgments": {"P": "supported", "Q0": "unknown"}}),
                                "stop", "compact") == ("unknown", False)
    assert audit.parsed_verdict(req, json.dumps({**complete, "judgments": {"P": "unknown", "Q0": "unsupported"}}),
                                "stop", "compact") == ("semantic_rejected", False)


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


@pytest.mark.parametrize("deferred", [False, True])
def test_heldout_labels_are_not_opened_before_receipt_validation(monkeypatch, tmp_path, deferred):
    """An audit stopped by a bad receipt must still preserve the unopened holdout."""
    baseline_path = tmp_path / "baseline.json"
    run = tmp_path / "positive"
    opened = []
    documents = {
        baseline_path: dict(additional_candidate_holdout=dict(selected_keys=["H:0:c"]),
                            positive_checkpoint={}, review_files=[]),
        run / "prepared.json": dict(scope="positive"),
        run / "summary.json": dict(stage="not_complete"),
    }

    def read_only_expected(path):
        opened.append(path)
        assert path in documents, "Deferred audit attempted an unapproved label read"
        return documents[path]

    monkeypatch.setattr(audit, "read", read_only_expected)
    monkeypatch.setattr(audit, "verify", lambda _: None)
    with pytest.raises(ValueError, match="Admission run is not complete"):
        audit.audit(baseline_path, None if deferred else tmp_path / "sealed_holdout_labels.json", run)
    assert opened == [baseline_path, run / "prepared.json", run / "summary.json"]


def test_complete_program_pairing_preserves_later_oracle_edits_and_rejects_changed_program(tmp_path):
    original = "def test_value():\n    assert compute(1) == 2\n"
    def edit(before, after, role=None):
        begin = original.index(before)
        return dict(span=dict(path="tests/test_value.py", start_byte=begin, end_byte=begin + len(before)),
                    before=before, after=after, **({"role": role} if role else {}))
    input_edit, oracle_edit = edit("1", "3"), edit("2", "6", "semantic_expected")
    candidate = dict(id="c", base_test_id="test", instrumentation={"status": "instrumented"},
                     program_edits=[input_edit], edits=[{**input_edit, "after": "PROBE()", "instrumented_prefix": True}, oracle_edit])
    corpus = dict(tests={"test": {"span": dict(path="tests/test_value.py", start_byte=0, end_byte=len(original))}},
                  sources={"tests/test_value.py": {"code": original}})
    corpus_path, candidates_path = tmp_path / "corpus.json", tmp_path / "candidates.json"
    corpus_path.write_text(json.dumps(corpus))
    candidates_path.write_text(json.dumps([candidate]))
    program = {**candidate, "edits": [input_edit, oracle_edit]}
    digest = hashlib.sha256(json.dumps(program, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    record = dict(candidate_id="c", inputs={"corpus": {"path": str(corpus_path)}, "candidates": {"path": str(candidates_path)}})
    prompt = {"original_test": original, "modified_test": "def test_value():\n    assert compute(3) == 6\n"}
    req = dict(candidate_sha256=digest, prompt=json.dumps(prompt))
    assert audit.verify_prompt_program(req, record, {})["exact_frozen_test_program"]
    prompt["modified_test"] = original
    with pytest.raises(ValueError, match="modified test differs"):
        audit.verify_prompt_program({**req, "prompt": json.dumps(prompt)}, record, {})


def test_compact_excerpt_uses_character_prefix_and_retains_complete_source():
    code = "变量" * 200
    reference = dict(source="S0", start=0, end=len(code.encode()))
    block = dict(path="tests/test.py", start_byte=0, end_byte=len(code.encode()), code=code)
    site = dict(unit="V0", kind="assert_expression", at=reference, predicate=reference, guards=[])
    document = dict(sources={"S0": block}, obligations={"Q0": site})
    check = dict(unit="V0", kind="assert_expression", at=reference,
                 expression=dict(ref=reference, text=code[:320], omitted_chars=80), guards=[], exception_regions=[])
    payload = dict(checks={"P": {}, "Q0": check}, source_analysis=f"S0 tests/test.py bytes 0:{len(code.encode())}\n```\n{code}\n```")
    request = dict(prompt=json.dumps(payload))
    result = audit.verify_compact_references(request, dict(analysis=document))
    assert result["excerpts_with_omitted_suffix"] == 1
    payload["checks"]["Q0"]["expression"]["omitted_chars"] = 880
    with pytest.raises(ValueError, match="omission count"):
        audit.verify_compact_references(dict(prompt=json.dumps(payload)), dict(analysis=document))
    payload["checks"]["Q0"]["expression"]["omitted_chars"] = 80
    payload["source_analysis"] = code[:320]
    with pytest.raises(ValueError, match="Complete compact source block missing"):
        audit.verify_compact_references(dict(prompt=json.dumps(payload)), dict(analysis=document))
