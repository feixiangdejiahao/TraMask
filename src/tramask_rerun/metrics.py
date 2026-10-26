"""Pure statistics over explicit registrations and new atomic observations.

Nothing here reads files, prior verdicts, providers, or subject environments.
Registrations are authoritative: missing/invalid/no_proposal observations retain
their slots and count as unsuccessful. Unresolved is also unsuccessful for the
intention-to-treat success endpoint, but is never called a confirmed negative.
Wilson intervals describe registered binary observations; cluster bootstrap
intervals resample whole issues and are the uncertainty estimate for repeats.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import comb, isfinite, sqrt
from random import Random
from statistics import NormalDist, mean


DEFAULT_SEED = 20261023
STATUSES = frozenset({"success", "failure", "failed", "invalid", "no_proposal",
                      "unresolved", "timeout", "error", "missing", "not_run",
                      "budget_limited", "generation_failed", "execution_failed"})


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    return value


def _identifier(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _confidence(value):
    if not 0 < _number(value, "confidence") < 1:
        raise ValueError("confidence must be between zero and one")
    return value


def wilson95(successes, n):
    """Wilson score interval, with an explicit null estimate/interval at n=0."""
    _integer(successes, "successes")
    _integer(n, "n")
    if successes > n:
        raise ValueError("successes exceeds n")
    if not n:
        return {"successes": 0, "n": 0, "rate": None, "ci95": None}
    z = NormalDist().inv_cdf(0.975)
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return {"successes": successes, "n": n, "rate": p,
            "ci95": [max(0.0, center - half), min(1.0, center + half)]}


def reviewer_agreement(rows, *, left_key="reviewer_a", right_key="reviewer_b"):
    """Nominal agreement/kappa; missing reviews remain explicit in the audit.

    A literal 'unresolved' rating is a category, not a missing review. Kappa is
    undefined when expected agreement is one, even with perfect raw agreement.
    """
    rows = list(rows)
    paired = [(r[left_key], r[right_key]) for r in rows
              if r.get(left_key) is not None and r.get(right_key) is not None]
    for a, b in paired:
        _identifier(a, left_key)
        _identifier(b, right_key)
    n = len(paired)
    ca, cb = Counter(a for a, _ in paired), Counter(b for _, b in paired)
    agreements = sum(a == b for a, b in paired)
    expected_numerator = sum(ca[k] * cb[k] for k in ca.keys() | cb.keys())
    expected = expected_numerator / (n * n) if n else None
    raw = agreements / n if n else None
    kappa = ((agreements * n - expected_numerator) / (n * n - expected_numerator)
             if n and expected_numerator != n * n else None)
    return {"n_registered": len(rows), "n_paired": n, "n_missing_reviews": len(rows) - n,
            "agreements": agreements, "raw_agreement": raw, "expected_agreement": expected,
            "cohen_kappa": kappa, "left_counts": dict(ca), "right_counts": dict(cb),
            "undefined_reason": "no_paired_reviews" if not n else
            "constant_identical_ratings" if kappa is None else None}


def _quantile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[min(lower + 1, len(ordered) - 1)] * fraction


def cluster_bootstrap_ci(rows, *, value_key="value", issue_key="issue_id",
                         statistic=None, n_resamples=10000, seed=DEFAULT_SEED,
                         confidence=0.95):
    """Percentile CI, sampling issue IDs with replacement and retaining all rows.

    The default estimand is the observation-weighted mean. A custom statistic
    accepts a list of dicts and returns a finite number or None. Undefined
    resamples are reported and make the interval null; they are not discarded.
    One issue cannot supply between-issue uncertainty, regardless of repeats.
    """
    rows = list(rows)
    _integer(n_resamples, "n_resamples", 1)
    _integer(seed, "seed")
    _confidence(confidence)
    clusters = defaultdict(list)
    for row in rows:
        clusters[_identifier(row.get(issue_key), issue_key)].append(row)
    if statistic is None:
        for row in rows:
            _number(row.get(value_key), value_key)
        statistic = lambda sample: mean(r[value_key] for r in sample) if sample else None
    estimate = statistic(rows) if rows else None
    if estimate is not None:
        _number(estimate, "statistic")
    result = {"estimate": estimate, "ci": None, "confidence": confidence,
              "n_observations": len(rows), "n_issues": len(clusters),
              "n_resamples": n_resamples, "seed": seed, "undefined_resamples": 0,
              "method": "issue_cluster_percentile_bootstrap",
              "undefined_reason": None}
    if len(clusters) < 2 or estimate is None:
        result["undefined_reason"] = ("no_observations" if not rows else
                                      "undefined_statistic" if estimate is None else
                                      "fewer_than_two_issues")
        return result
    ordered = [clusters[k] for k in sorted(clusters)]
    rng, values = Random(seed), []
    for _ in range(n_resamples):
        sample = [row for _ in ordered for row in ordered[rng.randrange(len(ordered))]]
        value = statistic(sample)
        if value is None:
            result["undefined_resamples"] += 1
        else:
            values.append(_number(value, "resampled statistic"))
    if result["undefined_resamples"]:
        result["undefined_reason"] = "undefined_bootstrap_resamples"
    else:
        alpha = (1 - confidence) / 2
        result["ci"] = [_quantile(values, alpha), _quantile(values, 1 - alpha)]
    return result


def _registered(registrations, observations):
    registrations, observations = list(registrations), list(observations)
    registry, observed = {}, {}
    for row in registrations:
        key = _identifier(row.get("id"), "registered id")
        _identifier(row.get("issue_id"), "issue_id")
        if key in registry:
            raise ValueError("duplicate registered id: " + key)
        registry[key] = row
    for row in observations:
        key = _identifier(row.get("id"), "observation id")
        if key not in registry:
            raise ValueError("unregistered observation: " + key)
        if key in observed:
            raise ValueError("duplicate observation: " + key)
        if "issue_id" in row and row["issue_id"] != registry[key]["issue_id"]:
            raise ValueError("observation issue mismatch: " + key)
        observed[key] = row
    return [(r, observed.get(r["id"])) for r in registrations]


def _outcomes(registrations, observations):
    rows = []
    for reg, obs in _registered(registrations, observations):
        status = "missing" if obs is None else obs.get("status")
        if status not in STATUSES:
            raise ValueError("unknown observation status: " + str(status))
        rows.append({"id": reg["id"], "issue_id": reg["issue_id"], "status": status,
                     "success": status == "success", "value": int(status == "success")})
    return rows


def binary_outcomes(registrations, observations, *, n_resamples=10000, seed=DEFAULT_SEED):
    """Success rate over EVERY registered run or candidate (choose one unit).

    Inputs: registrations [{id, issue_id}], observations [{id, status}].
    Do not mix candidate registrations and gold registrations in one call.
    """
    rows = _outcomes(registrations, observations)
    counts = Counter(r["status"] for r in rows)
    result = wilson95(counts["success"], len(rows))
    result.update(n_registered=len(rows), n_unsuccessful=len(rows) - counts["success"],
                  n_unresolved=counts["unresolved"], status_counts=dict(counts), rows=rows,
                  issue_bootstrap=cluster_bootstrap_ci(rows, n_resamples=n_resamples, seed=seed),
                  endpoint="confirmed_success_per_registered_unit; unresolved remains separate")
    return result


def mcnemar_exact(a_only, b_only):
    """Exact two-sided Binomial(discordant, .5) tail; no asymptotic cutoff."""
    _integer(a_only, "a_only")
    _integer(b_only, "b_only")
    n = a_only + b_only
    tail = sum(comb(n, k) for k in range(min(a_only, b_only) + 1))
    return {"a_only": a_only, "b_only": b_only, "discordant_pairs": n,
            "p_two_sided": min(1.0, 2 * tail / (2 ** n)),
            "note": "Exact, discrete test; few discordances have low power. Requires independent pairs."}


def paired_binary_comparison(registrations, a, b, *, n_resamples=10000, seed=DEFAULT_SEED):
    """A minus B, left-joined on all preregistered pair IDs, including repeats."""
    registrations = list(registrations)
    left, right = _outcomes(registrations, a), _outcomes(registrations, b)
    cells = Counter((x["success"], y["success"]) for x, y in zip(left, right))
    differences = [{"issue_id": x["issue_id"], "value": x["value"] - y["value"]}
                   for x, y in zip(left, right)]
    n = len(left)
    issues = len({r["issue_id"] for r in left})
    test = mcnemar_exact(cells[True, False], cells[False, True])
    if not n:
        test["p_two_sided"] = None
    test.update(independent_issue_pairs=issues == n and n > 0,
                interpretation="independent_issue_pairs" if issues == n and n else
                "descriptive_only_repeated_issues" if n else "no_pairs")
    return {"n_registered_pairs": n, "n_issues": issues,
            "both_success": cells[True, True], "neither_success": cells[False, False],
            "a_only": cells[True, False], "b_only": cells[False, True],
            "a_status_counts": dict(Counter(x["status"] for x in left)),
            "b_status_counts": dict(Counter(x["status"] for x in right)),
            "difference_a_minus_b": cluster_bootstrap_ci(differences, n_resamples=n_resamples, seed=seed),
            "mcnemar": test}


def paired_cost_comparison(registrations, a, b, *, cost_key="cost", unit="tokens",
                           n_resamples=10000, seed=DEFAULT_SEED):
    """Measured cost A-B, including failed runs that incurred measured costs.

    Missing costs are never imputed as zero. An available-pairs CI is explicitly
    secondary when any registered pair has missing costs; the all-pairs estimate
    and CI are then null. Observation status does not filter measured costs.
    """
    registrations = list(registrations)
    left = _registered(registrations, a)
    right = _registered(registrations, b)
    differences, incomplete = [], []
    for (reg, x), (_, y) in zip(left, right):
        av, bv = x.get(cost_key) if x else None, y.get(cost_key) if y else None
        for value in (av, bv):
            if value is not None and _number(value, cost_key) < 0:
                raise ValueError("cost must be nonnegative")
        if av is None or bv is None:
            incomplete.append({"id": reg["id"], "issue_id": reg["issue_id"],
                               "a_cost_missing": av is None, "b_cost_missing": bv is None})
        else:
            differences.append({"id": reg["id"], "issue_id": reg["issue_id"], "value": av - bv})
    estimate = cluster_bootstrap_ci(differences, n_resamples=n_resamples, seed=seed)
    return {"n_registered_pairs": len(registrations), "n_complete_cost_pairs": len(differences),
            "n_missing_cost_pairs": len(incomplete), "incomplete_pairs": incomplete, "unit": unit,
            "all_registered_mean_difference": None if incomplete else estimate["estimate"],
            "all_registered_ci": None if incomplete else estimate["ci"],
            "available_pairs_difference_a_minus_b": estimate,
            "available_pairs_are_secondary": bool(incomplete)}


def ranking_metrics(runs, candidates, gold, *, ks=(1, 3, 5), n_resamples=10000, seed=DEFAULT_SEED):
    """Separate registered candidate-slot precision from gold Recall@k and MRR.

    runs: {id, issue_id, candidate_slots}; candidates: {run_id, rank, status,
    gold_ids: [id, ...]}; gold: {id, issue_id, status: positive|negative|unresolved}.
    Candidate success means independently confirmed; gold_ids are explicit
    matching links. Precision counts successful slots (duplicates retain slots),
    recall counts distinct matched positive gold IDs per run. Missing ranks stay
    in place. MRR averages over every registered run, with no hit scored zero.
    Recall is micro over positive gold opportunities across all registered runs;
    runs with no positive gold have undefined individual recall, reported below.
    """
    runs, candidates, gold = list(runs), list(candidates), list(gold)
    ks = tuple(sorted(set(ks)))
    for k in ks:
        _integer(k, "k", 1)
    _registered(runs, [])
    run_map = {r["id"]: r for r in runs}
    slots = []
    for r in runs:
        for rank in range(1, _integer(r.get("candidate_slots"), "candidate_slots") + 1):
            slots.append({"id": (r["id"], rank), "issue_id": r["issue_id"]})
    gold_map, positives, unresolved = {}, defaultdict(set), defaultdict(set)
    for g in gold:
        key = _identifier(g.get("id"), "gold id")
        issue = _identifier(g.get("issue_id"), "gold issue_id")
        if key in gold_map:
            raise ValueError("duplicate gold id: " + key)
        if g.get("status") not in {"positive", "negative", "unresolved"}:
            raise ValueError("unknown gold status")
        gold_map[key] = g
        if g["status"] == "positive":
            positives[issue].add(key)
        elif g["status"] == "unresolved":
            unresolved[issue].add(key)
    observed = {}
    for c in candidates:
        rid = c.get("run_id")
        rank = _integer(c.get("rank"), "rank", 1)
        if rid not in run_map or rank > run_map[rid]["candidate_slots"]:
            raise ValueError("unregistered candidate slot")
        if (rid, rank) in observed:
            raise ValueError("duplicate candidate slot")
        if c.get("status") not in STATUSES:
            raise ValueError("unknown candidate status")
        links = c.get("gold_ids", [])
        if not isinstance(links, list) or any(not isinstance(g, str) for g in links):
            raise ValueError("gold_ids must be a list of strings")
        for gid in links:
            if gid not in gold_map or gold_map[gid]["issue_id"] != run_map[rid]["issue_id"]:
                raise ValueError("unknown or cross-issue gold link")
        observed[rid, rank] = c
    counts = Counter(observed.get(s["id"], {}).get("status", "missing") for s in slots)
    per_run = []
    for r in runs:
        issue, rid = r["issue_id"], r["id"]
        seen, hits, first, confirmed = set(), {}, 0, 0
        for rank in range(1, max((r["candidate_slots"], *ks)) + 1):
            c = observed.get((rid, rank), {})
            if c.get("status") == "success":
                confirmed += 1
                matches = set(c.get("gold_ids", [])) & positives[issue]
                if matches and not first:
                    first = rank
                seen.update(matches)
            if rank in ks:
                hits[str(rank)] = len(seen)
        per_run.append({"id": rid, "issue_id": issue, "candidate_slots": r["candidate_slots"],
                        "confirmed_candidates": confirmed, "positive_gold": len(positives[issue]),
                        "unresolved_gold": len(unresolved[issue]), "hits_at_k": hits,
                        "reciprocal_rank": 1 / first if first else 0})
    def ratio(sample, numerator, denominator):
        denom = sum(denominator(r) for r in sample)
        return sum(numerator(r) for r in sample) / denom if denom else None
    recall = {}
    opportunities = sum(r["positive_gold"] for r in per_run)
    unresolved_opportunities = sum(r["unresolved_gold"] for r in per_run)
    for k in ks:
        recovered = sum(r["hits_at_k"][str(k)] for r in per_run)
        recall[str(k)] = {"recovered_positive_gold_opportunities": recovered,
                          "positive_gold_opportunities": opportunities,
                          "rate": recovered / opportunities if opportunities else None,
                          "issue_bootstrap": cluster_bootstrap_ci(
                              per_run, statistic=lambda sample, k=k: ratio(
                                  sample, lambda r: r["hits_at_k"][str(k)], lambda r: r["positive_gold"]),
                              n_resamples=n_resamples, seed=seed)}
    precision = wilson95(counts["success"], len(slots))
    precision.update(status_counts=dict(counts), n_unresolved=counts["unresolved"],
                     issue_bootstrap=cluster_bootstrap_ci(
                         per_run, statistic=lambda sample: ratio(
                             sample, lambda r: r["confirmed_candidates"], lambda r: r["candidate_slots"]),
                         n_resamples=n_resamples, seed=seed))
    return {"n_registered_runs": len(runs), "n_registered_candidate_slots": len(slots),
            "n_observed_candidates": len(candidates), "n_issues": len({r["issue_id"] for r in runs}),
            "candidate_precision": precision,
            "gold": {"n_registered": len(gold), "status_counts": dict(Counter(g["status"] for g in gold)),
                     "positive_opportunities": opportunities, "unresolved_opportunities": unresolved_opportunities,
                     "runs_without_positive_gold": [r["id"] for r in per_run if not r["positive_gold"]]},
            "recall_at_k": recall,
            "mrr": cluster_bootstrap_ci(per_run, value_key="reciprocal_rank", n_resamples=n_resamples, seed=seed),
            "per_run": per_run,
            "interpretation": "Gold recall is conditional on confirmed positive gold; unresolved gold is separate. Candidate precision includes every preregistered slot; MRR includes every preregistered run."}
