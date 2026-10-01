"""Evaluation accounting must not turn unknown candidates into valid alarms."""
import hashlib

import pytest

from scripts import evaluate_test_validity as audit


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


def test_scoped_analysis_never_expands_holdout_from_predictions():
    value = baseline()
    value["controlled_failures"] = [dict(key="p"), dict(key="n"), dict(key="h")]
    value["additional_candidate_holdout"] = {"selected_keys": ["h"]}
    assert audit.selected_records(value, "positive") == [dict(key="p")]
    assert audit.selected_records(value, "development") == [dict(key="n")]
    assert audit.selected_records(value, "holdout") == [dict(key="h")]
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
