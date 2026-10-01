"""Evaluation accounting must not turn unknown candidates into valid alarms."""
import hashlib
from types import SimpleNamespace

import pytest

from scripts import evaluate_test_validity as audit


def test_imported_helper_seal_detects_changes_not_just_entry_modules(tmp_path, monkeypatch):
    path = tmp_path / "helper.py"
    path.write_text("value = 1\n")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setitem(audit.sys.modules, "validity_evaluation_fixture", SimpleNamespace(__file__=str(path)))
    sources = audit.loaded_local_sources()
    assert sources["validity_evaluation_fixture"] == audit.frozen(path)
    audit.verify_seal(sources)
    path.write_text("value = 2\n")
    with pytest.raises(ValueError, match="imported source changed"):
        audit.verify_seal(sources)


def test_named_failure_requires_every_selected_name_and_only_native_outcomes(tmp_path, monkeypatch):
    report, manifest = tmp_path / "report.json", tmp_path / "manifest.json"
    report.write_text("{}")
    manifest.write_text("{}")
    row = dict(result=str(report), manifest=str(manifest), test_ids=["one", "two"])
    monkeypatch.setattr(audit, "native", lambda _: ([dict(id="one", status="fail")], [], {}))
    assert audit.named_failure([row]) is None
    monkeypatch.setattr(audit, "native", lambda _: ([dict(id="one", status="fail"), dict(id="two", status="skip")], [], {}))
    assert audit.named_failure([row]) is None
    monkeypatch.setattr(audit, "native", lambda _: ([dict(id="one", status="fail"), dict(id="two", status="pass")], [], {}))
    assert len(audit.named_failure([row])) == 1
    monkeypatch.setattr(audit, "native", lambda _: ([dict(id="one", status="fail"), dict(id="two", status="pass")], ["parser error"], {}))
    assert audit.named_failure([row]) is None


def test_heldout_selection_is_order_invariant_deduplicates_and_excludes_truth():
    rows = [dict(key=f"A:0:{n}", case="A", round=0, candidate_id=str(n)) for n in range(8)]
    duplicate = {**rows[0], "key": "A:1:0", "round": 1}
    exclusions = {("A", "1"), ("A", "2")}
    one = audit.heldout_sample(rows + [duplicate], exclusions, 2)
    two = audit.heldout_sample(list(reversed(rows)) + [duplicate], exclusions, 2)
    assert one == two
    assert len(one["selected_keys"]) == 2
    assert not any(key.endswith(":1") or key.endswith(":2") for key in one["selected_keys"])
    expected = sorted([n for n in range(8) if n not in {1, 2}], key=lambda n: hashlib.sha256(
        ("validity-candidate-holdout-v1\0A\0" + str(n)).encode()).hexdigest())[:2]
    assert one["selected_keys"] == [f"A:0:{n}" for n in expected]


@pytest.mark.parametrize("statuses,result", [(["unknown", "unknown"], "unknown"),
    (["review", "unknown"], "review"), (["unknown", "invalid"], "invalid")])
def test_conservative_combination_never_certifies_valid(statuses, result):
    assert audit.combine([dict(status=value) for value in statuses]) == result


def test_success_sounding_status_is_rejected():
    with pytest.raises(ValueError, match="absence of errors is not validity"):
        audit.combine([dict(status="valid")])


def baseline():
    return dict(positive_witnesses=[dict(case="A", candidate_id="p", occurrence_keys=["p"])],
                development_reviews=[dict(case="A", candidate_id="n", occurrence_keys=["n"],
                    classification="invalid_oracle_or_setup",
                    initial_failure_classification="mixed_valid_early_signal_invalid_complete_oracle")])


def prediction(key, status):
    return dict(key=key, status=status, analyses={"m": dict(status=status, findings=[])})


def test_unknown_retains_known_positive_without_certifying_it_and_mixed_not_strict_fp():
    report = audit.summarize(baseline(), [prediction("p", "unknown"), prediction("n", "invalid")])
    assert report["independent_positive_retention"] == {"retained_unknown_or_review": 1}
    assert report["development_review_filtering"] == {"invalid_oracle_or_setup": {"rejected": 1}}
    assert report["review_details"][0]["initial_failure_classification"].startswith("mixed")
    assert report["strict_false_positive_total"] is None


def test_missing_analysis_is_not_counted_retained():
    report = audit.summarize(baseline(), [prediction("n", "unknown")])
    assert report["independent_positive_retention"] == {"not_analyzed": 1}


def test_incorrect_rejection_of_positive_is_reported():
    report = audit.summarize(baseline(), [prediction("p", "invalid")])
    assert report["independent_positive_retention"] == {"rejected": 1}


def test_heldout_initial_alarm_and_complete_oracle_are_reported_separately():
    value = baseline()
    value["additional_candidate_holdout"] = dict(selected_keys=["h"], scope="candidate holdout")
    reviews = dict(review_protocol="full test", reviews=[dict(key="h",
        classification="invalid_oracle_or_setup",
        initial_failure_classification="mixed_valid_early_signal_invalid_complete_oracle")])
    report = audit.summarize(value, [prediction("h", "review")], reviews)
    assert report["heldout_complete_test_filtering"]["invalid_oracle_or_setup"] == {"retained_unknown_or_review": 1}
    assert report["heldout_initial_alarm_filtering"]["mixed_valid_early_signal_invalid_complete_oracle"] == {"retained_unknown_or_review": 1}
    assert report["strict_false_positive_total"] is None


@pytest.mark.parametrize("keys", [["different"], ["h", "h"], []])
def test_posthoc_labels_cannot_change_or_duplicate_frozen_holdout(keys):
    value = baseline()
    value["additional_candidate_holdout"] = dict(selected_keys=["h"], scope="candidate holdout")
    reviews = dict(review_protocol="full test", reviews=[dict(key=key) for key in keys])
    with pytest.raises(ValueError, match="exactly the previously frozen"):
        audit.summarize(value, [], reviews)


def test_model_support_is_hypothesis_and_unknown_suppression_is_separate():
    value = baseline()
    value["controlled_failures"] = [dict(key="p"), dict(key="n")]
    prepared = dict(scope="all", items=[dict(key="p"), dict(key="n")])
    completed = dict(provider_calls=2, accounted_tokens=100, usage_missing=0, decisions=[
        dict(key="p", decision=dict(status="semantic_supported", alarm_eligible=True)),
        dict(key="n", decision=dict(status="unknown", alarm_eligible=False))])
    report = audit.summarize_admission(value, completed, prepared)
    assert report["independent_positive_admission"] == {"admitted_model_hypothesis": 1}
    assert report["development_complete_test_admission"] == {"invalid_oracle_or_setup": {"not_admitted_unknown": 1}}
    assert "model hypothesis" in report["interpretation"]


def test_semantic_report_rejects_unprepared_decisions_and_invalid_alarm_flags():
    value = baseline()
    value["controlled_failures"] = [dict(key="p")]
    prepared = dict(scope="all", items=[dict(key="p")])
    completed = dict(provider_calls=0, accounted_tokens=0, usage_missing=0, decisions=[
        dict(key="p", decision=dict(status="static_invalid", alarm_eligible=True))])
    with pytest.raises(ValueError, match="Only a semantic-supported"):
        audit.summarize_admission(value, completed, prepared)
    completed["decisions"][0]["key"] = "unprepared"
    with pytest.raises(ValueError, match="frozen prepared"):
        audit.summarize_admission(value, completed, prepared)


def test_scoped_analysis_never_expands_holdout_from_predictions():
    value = baseline()
    value["controlled_failures"] = [dict(key="p"), dict(key="n"), dict(key="h")]
    value["additional_candidate_holdout"] = {"selected_keys": ["h"]}
    assert audit.selected_records(value, "positive") == [dict(key="p")]
    assert audit.selected_records(value, "development") == [dict(key="n")]
    assert audit.selected_records(value, "holdout") == [dict(key="h")]
    assert audit.selected_records(value, "audited") == value["controlled_failures"]
    with pytest.raises(ValueError, match="Unknown evaluation scope"):
        audit.selected_records(value, "easiest")


def test_inventory_enforces_source_controls_and_links_positive(tmp_path, monkeypatch):
    campaign, evaluation = tmp_path / "campaign", tmp_path / "evaluation"
    round_dir = campaign / "A/round_000"
    for name in ("prepared", "emitted", "executed"):
        (round_dir / name).mkdir(parents=True)
    def save(path, value):
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    save(campaign / "configuration.json", {})
    save(evaluation / "uniform_fresh_impact_v3/checkpoint_14.json", {"cases": [
        dict(case="A", fixed_configuration_correct=True, fixed_configuration_automatic_ids=["p"])]})
    for name in ("corpus", "frontend"):
        save(round_dir / "prepared" / (name + ".json"), {})
    save(round_dir / "emitted/accepted.json", [dict(id=cid, base_test_id="test") for cid in ("p", "n")])
    save(round_dir / "executed/runs.json", [dict(role="generated", candidate_id=cid) for cid in ("p", "n")])
    monkeypatch.setattr(audit, "named_failure", lambda rows: [{"candidate_id": rows[0]["candidate_id"]}])
    monkeypatch.setattr(audit, "inspect_controls", lambda rows, runs:
        dict(status="all_source_controls_passed" if rows[0]["candidate_id"] == "p" else "source_control_failed_or_errored", controls=[]))
    result = audit.inventory(campaign, evaluation)
    assert result["counts"]["generated_occurrences"] == 2
    assert result["counts"]["controlled_failure_occurrences"] == 1
    assert result["controlled_failures"][0]["candidate_id"] == "p"
    assert result["positive_witnesses"][0]["occurrence_keys"] == ["A:0:p"]
    assert result["additional_candidate_holdout"]["selected_keys"] == []


def test_uncontrolled_positive_cannot_silently_join_the_census(tmp_path, monkeypatch):
    # Exercise the same frozen-shape fixture without considering labels during
    # eligibility: the final accounting must reject a missing positive proof.
    campaign, evaluation = tmp_path / "campaign", tmp_path / "evaluation"
    (campaign / "A/round_000/executed").mkdir(parents=True)
    (campaign / "A/round_000/emitted").mkdir()
    (campaign / "A/round_000/prepared").mkdir()
    import json
    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    save(campaign / "configuration.json", {})
    save(evaluation / "uniform_fresh_impact_v3/checkpoint_14.json", {"cases": [
        dict(case="A", fixed_configuration_correct=True, fixed_configuration_automatic_ids=["p"])]})
    for name in ("corpus", "frontend"):
        save(campaign / f"A/round_000/prepared/{name}.json", {})
    save(campaign / "A/round_000/emitted/accepted.json", [dict(id="p", base_test_id="test")])
    save(campaign / "A/round_000/executed/runs.json", [dict(role="generated", candidate_id="p")])
    monkeypatch.setattr(audit, "named_failure", lambda rows: None)
    with pytest.raises(ValueError, match="no independently controlled failing occurrence"):
        audit.inventory(campaign, evaluation)
