"""Statistical boundary cases; synthetic dicts only, no provider or Docker."""
import math

import pytest

from tramask_rerun import metrics


def registrations(*issues):
    return [{"id": str(i), "issue_id": issue} for i, issue in enumerate(issues)]


def test_wilson_zero_and_small_sample_known_values():
    assert metrics.wilson95(0, 0) == {"successes": 0, "n": 0, "rate": None, "ci95": None}
    assert metrics.wilson95(0, 1)["ci95"] == pytest.approx([0, 0.7934506856227626])
    assert metrics.wilson95(5, 10)["ci95"] == pytest.approx([0.236593090512564, 0.763406909487436])
    with pytest.raises(ValueError):
        metrics.wilson95(2, 1)


def test_perfect_constant_agreement_has_undefined_kappa_and_missing_stays_counted():
    result = metrics.reviewer_agreement([
        {"reviewer_a": "positive", "reviewer_b": "positive"},
        {"reviewer_a": "positive", "reviewer_b": "positive"},
        {"reviewer_a": "positive"}])
    assert result["raw_agreement"] == 1
    assert result["cohen_kappa"] is None
    assert result["n_registered"] == 3 and result["n_missing_reviews"] == 1
    assert metrics.reviewer_agreement([])["raw_agreement"] is None
    assert metrics.reviewer_agreement([])["cohen_kappa"] is None


def test_nominal_kappa_handles_unresolved_as_category():
    rows = [{"reviewer_a": a, "reviewer_b": b} for a, b in
            [("yes", "yes"), ("yes", "no"), ("no", "no"), ("unresolved", "unresolved")]]
    result = metrics.reviewer_agreement(rows)
    assert result["raw_agreement"] == 0.75
    assert result["cohen_kappa"] == pytest.approx(7 / 11)
    assert result["left_counts"]["unresolved"] == 1


def test_issue_bootstrap_does_not_create_independent_samples_from_repeats():
    rows = [{"issue_id": "one", "value": v} for v in [0, 1] * 50]
    one = metrics.cluster_bootstrap_ci(rows, n_resamples=200)
    assert one["estimate"] == 0.5 and one["n_observations"] == 100
    assert one["n_issues"] == 1 and one["ci"] is None
    original = [{"issue_id": "a", "value": 0}, {"issue_id": "b", "value": 1}]
    duplicated = [row for row in original for _ in range(50)]
    a = metrics.cluster_bootstrap_ci(original, n_resamples=400, seed=17)
    b = metrics.cluster_bootstrap_ci(duplicated, n_resamples=400, seed=17)
    assert a["ci"] == b["ci"] == [0, 1]
    assert a["n_issues"] == b["n_issues"] == 2
    assert a == metrics.cluster_bootstrap_ci(list(reversed(original)), n_resamples=400, seed=17)


def test_bootstrap_empty_missing_value_and_undefined_resamples():
    assert metrics.cluster_bootstrap_ci([])["ci"] is None
    with pytest.raises(ValueError):
        metrics.cluster_bootstrap_ci([{"issue_id": "a"}])
    rows = [{"issue_id": "a", "value": 0}, {"issue_id": "b", "value": 1}]
    result = metrics.cluster_bootstrap_ci(rows, statistic=lambda s: 1 if any(r["value"] for r in s) else None,
                                          n_resamples=100, seed=1)
    assert result["undefined_resamples"] > 0
    assert result["ci"] is None and result["undefined_reason"] == "undefined_bootstrap_resamples"


def test_every_registered_run_remains_in_success_denominator():
    regs = registrations("a", "b", "c", "d", "e")
    observed = [{"id": "0", "status": "success"}, {"id": "1", "status": "invalid"},
                {"id": "2", "status": "no_proposal"}, {"id": "3", "status": "unresolved"}]
    result = metrics.binary_outcomes(regs, observed, n_resamples=200)
    assert result["n_registered"] == 5 and result["rate"] == 0.2
    assert result["n_unsuccessful"] == 4 and result["n_unresolved"] == 1
    assert result["status_counts"]["missing"] == 1
    with pytest.raises(ValueError, match="unregistered"):
        metrics.binary_outcomes(regs, [{"id": "6", "status": "success"}])
    with pytest.raises(ValueError, match="duplicate"):
        metrics.binary_outcomes(regs, observed + [observed[0]])
    with pytest.raises(ValueError, match="issue mismatch"):
        metrics.binary_outcomes(regs, [{"id": "0", "issue_id": "wrong", "status": "success"}])


def test_exact_mcnemar_small_discordance_and_empty_registered_pairs():
    assert metrics.mcnemar_exact(5, 0)["p_two_sided"] == 0.0625
    assert metrics.mcnemar_exact(0, 5)["p_two_sided"] == 0.0625
    assert metrics.mcnemar_exact(0, 0)["p_two_sided"] == 1
    assert metrics.paired_binary_comparison([], [], [])["mcnemar"]["p_two_sided"] is None


def test_paired_binary_missing_arms_and_clustered_repeats_are_explicit():
    regs = registrations("a", "a", "b")
    a = [{"id": "0", "status": "success"}, {"id": "1", "status": "success"}]
    b = [{"id": "1", "status": "success"}, {"id": "2", "status": "unresolved"}]
    result = metrics.paired_binary_comparison(regs, a, b, n_resamples=200)
    assert result["n_registered_pairs"] == 3 and result["n_issues"] == 2
    assert result["a_only"] == 1 and result["both_success"] == 1 and result["neither_success"] == 1
    assert result["difference_a_minus_b"]["estimate"] == pytest.approx(1 / 3)
    assert result["a_status_counts"]["missing"] == 1
    assert result["b_status_counts"]["unresolved"] == 1
    assert not result["mcnemar"]["independent_issue_pairs"]
    assert result["mcnemar"]["interpretation"] == "descriptive_only_repeated_issues"


def test_paired_cost_missing_is_not_zero_and_failed_run_cost_is_kept():
    regs = registrations("a", "b", "c")
    a = [{"id": "0", "cost": 10, "status": "failed"}, {"id": "1", "cost": 20}]
    b = [{"id": "0", "cost": 15}, {"id": "1", "cost": 30}, {"id": "2", "cost": 0}]
    result = metrics.paired_cost_comparison(regs, a, b, n_resamples=200)
    assert result["n_registered_pairs"] == 3 and result["n_complete_cost_pairs"] == 2
    assert result["all_registered_mean_difference"] is None and result["all_registered_ci"] is None
    assert result["available_pairs_difference_a_minus_b"]["estimate"] == -7.5
    assert result["available_pairs_difference_a_minus_b"]["ci"] == [-10, -5]
    assert result["incomplete_pairs"] == [{"id": "2", "issue_id": "c", "a_cost_missing": True, "b_cost_missing": False}]
    with pytest.raises(ValueError):
        metrics.paired_cost_comparison(regs, [{"id": "0", "cost": math.nan}], [])


def test_ranking_keeps_missing_slots_invalid_ranks_and_missing_runs():
    runs = [{"id": "r1", "issue_id": "a", "candidate_slots": 5},
            {"id": "r2", "issue_id": "b", "candidate_slots": 5}]
    gold = [{"id": "g1", "issue_id": "a", "status": "positive"},
            {"id": "g2", "issue_id": "a", "status": "positive"},
            {"id": "g3", "issue_id": "b", "status": "positive"},
            {"id": "u1", "issue_id": "a", "status": "unresolved"}]
    candidates = [{"run_id": "r1", "rank": 1, "status": "invalid"},
                  {"run_id": "r1", "rank": 2, "status": "success", "gold_ids": ["g1"]},
                  {"run_id": "r1", "rank": 3, "status": "success", "gold_ids": ["g1"]},
                  {"run_id": "r1", "rank": 4, "status": "unresolved"}]
    result = metrics.ranking_metrics(runs, candidates, gold, n_resamples=200)
    assert result["n_registered_runs"] == 2 and result["n_registered_candidate_slots"] == 10
    assert result["candidate_precision"]["rate"] == 0.2
    assert result["candidate_precision"]["status_counts"]["missing"] == 6
    assert result["candidate_precision"]["n_unresolved"] == 1
    assert result["recall_at_k"]["1"]["rate"] == 0
    assert result["recall_at_k"]["3"]["rate"] == pytest.approx(1 / 3)
    assert result["recall_at_k"]["5"]["rate"] == pytest.approx(1 / 3)
    assert result["gold"]["unresolved_opportunities"] == 1
    assert result["mrr"]["estimate"] == 0.25


def test_ranking_zero_gold_zero_slots_and_unregistered_candidate():
    result = metrics.ranking_metrics([], [], [])
    assert result["candidate_precision"]["rate"] is None
    assert result["recall_at_k"]["1"]["rate"] is None
    assert result["mrr"]["estimate"] is None
    runs = [{"id": "r", "issue_id": "a", "candidate_slots": 0}]
    result = metrics.ranking_metrics(runs, [], [{"id": "u", "issue_id": "a", "status": "unresolved"}])
    assert result["mrr"]["estimate"] == 0 and result["gold"]["runs_without_positive_gold"] == ["r"]
    assert result["recall_at_k"]["5"]["rate"] is None
    with pytest.raises(ValueError, match="unregistered"):
        metrics.ranking_metrics(runs, [{"run_id": "r", "rank": 1, "status": "success"}], [])
