"""Join scoped runtime evidence to independent semantic reviews, preserving gaps."""
from collections import Counter
from pathlib import Path
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_rerun.evidence import adjudicate_semantic_reviews, derive_classification
from tramask_rerun.metrics import reviewer_agreement, wilson95
from tramask_rerun.study import RUN, now, write_new


def group(directory):
    records, initial, added = [], [], []
    for row in read(directory / "index.json")["pairs"]:
        pid = row["pair_id"]
        reviews = []
        for label in ("A", "B"):
            path = directory / ("reviewer_" + label) / (pid + ".json")
            reviews.append({**read(path), "receipt": receipt(path)})
        path = directory / "reviewer_C" / (pid + ".json")
        arbitration = {**read(path), "receipt": receipt(path)} if path.exists() else None
        record = adjudicate_semantic_reviews(pid, row["packet"], reviews, arbitration=arbitration)
        record["initial_reviews"] = [r["receipt"] for r in reviews]
        if arbitration:
            record["third_review"] = arbitration["receipt"]
        initial.append({"pair_id": pid, "topics": {key: {
            "reviewer_a": reviews[0]["judgments"][key]["status"],
            "reviewer_b": reviews[1]["judgments"][key]["status"]}
            for key in record["judgments"]}})
        if "added_component_status" in reviews[0]["judgments"]["oracle_validity"]:
            values = [r["judgments"]["oracle_validity"]["added_component_status"] for r in reviews]
            extra = {"pair_id": pid, "reviewer_a": values[0], "reviewer_b": values[1]}
            record["added_component"] = {"initial_statuses": values,
                "status": values[0] if values[0] == values[1] else "unresolved",
                "resolution": "two_reviewer_agreement" if values[0] == values[1] else "awaiting_third_adjudication"}
            if values[0] != values[1] and arbitration:
                record["added_component"].update(
                    status=arbitration["judgments"]["oracle_validity"]["added_component_status"],
                    resolution="third_reviewer_adjudication")
            record["new_P_defect_independently_established"] = False
            added.append(extra)
        records.append(record)
    stats = {key: reviewer_agreement([r["topics"][key] for r in initial]) for key in records[0]["judgments"]}
    return {"index": receipt(directory / "index.json"), "pairs": records,
        "initial_matrix": initial, "agreement": stats,
        "added_component_agreement": reviewer_agreement(added) if added else None,
        "all_unresolved_E7_agreement_is_not_evidence_of_context_validity": True}


if __name__ == "__main__":
    out = RUN / "evidence_aggregation_v01"
    if out.exists():
        raise FileExistsError(out)
    groups = {name: group(RUN / directory) for name, directory in [
        ("original40", "neutral_reference_review_v01"),
        ("reserved20", "neutral_reserved_review_v01"),
        ("candidates8", "neutral_candidate_review_v01")]}
    combined = groups["original40"]["initial_matrix"] + groups["reserved20"]["initial_matrix"]
    combined_stats = {topic: reviewer_agreement([r["topics"][topic] for r in combined])
        for topic in ("counterfactual_relevance", "context_legality", "oracle_validity")}
    write_new(out / "semantic_reviews.json", {"created_at": now(), "groups": groups,
        "all60_initial_agreement": combined_stats,
        "review_type": "Separate independent Codex threads, not human researchers; no model override requested.",
        "review_policy": "No reviewer votes on masking; only E3/E7/E9 semantic judgments. Initial answers retained."})
    semantic = {}
    for name, mapping in [("original40", "neutral_reference_review_mapping_v01.json"),
                          ("reserved20", "neutral_reserved_review_mapping_v01.json")]:
        ids = {row["pair_id"]: row["case_id"] for row in read(RUN / mapping)}
        for row in groups[name]["pairs"]:
            semantic[ids[row["pair_id"]]] = row
    source = RUN / "scoped_technical_evidence_components_v02.json"
    components = read(source)
    cases = {row["id"]: row for row in read(RUN / "cases.json")["cases"]}
    results = []
    for row in components["cases"]:
        cid = row["case_id"]
        checks = {**row["suggested_checks"], **semantic[cid]["gate_checks"],
            "E8": {"status": "unresolved", "evidence": [],
                   "reason": "No qualified context-only witness has been executed for this fixed reference pair."}}
        observations = row.get("suggested_nonmask_findings", row.get("nonmask_findings", {}))
        # A rejected/unknown Q cannot establish a valid nonmask comparison.
        if checks["E3"]["status"] == "fail":
            findings = {"invalid_counterfactual": {"status": "pass", "evidence": checks["E3"]["evidence"],
                "reason": "Independent E3 review rejects relevant executable isolated comparison. Runtime diagnostics are retained separately."}}
        elif checks["E3"]["status"] == "unresolved":
            findings = {"incomplete_evidence": {"status": "pass", "evidence": [receipt(source), *checks["E3"]["evidence"]],
                "reason": "Relevant executable Q remains unestablished; observed failures are not accepted as target discrimination."}}
        else:
            findings = observations
        derived = derive_classification(checks, nonmask_findings=findings)
        results.append({"case_id": cid, "task": cases[cid]["task"], "cohort": cases[cid]["cohort"],
            "partition": cases[cid]["partition"], "fixed_scope": row["fixed_scope"],
            "technical_components": receipt(source), "semantic_pair": semantic[cid]["pair_id"],
            "semantic_aggregation": receipt(out / "semantic_reviews.json"),
            "separate_runtime_diagnostics": observations, "evidence": derived,
            "technical_candidate_denominator": derived["check_conjunctions"]["candidate"],
            "usable_original_Q_comparison": checks["E1"]["status"] == checks["E3"]["status"] == "pass"})
    assert len(results) == 60
    metrics = {}
    for name, subset in [("all60", results), ("failed", [x for x in results if x["cohort"] == "failed"]),
                         ("successful", [x for x in results if x["cohort"] != "failed"]),
                         ("previously_explored", [x for x in results if x["partition"] == "previously_explored"]),
                         ("reserved", [x for x in results if x["partition"] == "reserved"])]:
        usable = [x for x in subset if x["usable_original_Q_comparison"]]
        candidates = [x for x in usable if x["technical_candidate_denominator"]]
        confirmed = [x for x in usable if x["evidence"]["confirmed"]]
        metrics[name] = {"registered": len(subset), "usable_comparison_ids": [x["case_id"] for x in usable],
            "E1_replay": wilson95(sum(x["evidence"]["checks"]["E1"]["status"] == "pass" for x in subset), len(subset)),
            "technical_E1_E6_candidate_ids": [x["case_id"] for x in candidates],
            "technical_candidate_rate": wilson95(len(candidates), len(usable)),
            "strict_taxonomy_candidate_ids": [x["case_id"] for x in usable if x["evidence"]["candidate"]],
            "confirmed_ids": [x["case_id"] for x in confirmed],
            "confirmed_rate_conservative_lower_bound": wilson95(len(confirmed), len(usable)),
            "confirmed_registered_lower_bound": wilson95(len(confirmed), len(subset)),
            "unresolved_witness_per_technical_candidate": wilson95(sum(x["evidence"]["witness_status"] != "established" for x in candidates), len(candidates)),
            "classifications": dict(Counter(x["evidence"]["classification"] for x in subset))}
    write_new(out / "pilot1_checklists.json", {"created_at": now(), "cases": results,
        "analysis_unit": "One prospectively selected fixed target/test/Q comparison per trial, one trial per issue; not every possible validation target.",
        "analyzable_denominator": "E1 pass and independently E3 pass; incomplete E2/E4/E5 remains explicit rather than selecting only conclusive cases.",
        "scope_caution": "Technical E1-E6 conjunction is reported even when a competing nonmask diagnosis blocks the strict taxonomy label. Such cases remain in the registered candidate-level downstream denominator.",
        "no_prevalence_extrapolation": True, "metrics": metrics})
    out.mkdir(exist_ok=True)
    with (out / "pilot1_cases.csv").open("x", newline="") as handle:
        columns = ["case_id", "task", "cohort", "partition", *[f"E{i}" for i in range(1,10)],
            "classification", "technical_E1_E6", "strict_candidate", "confirmed", "usable_comparison"]
        writer = csv.DictWriter(handle, fieldnames=columns); writer.writeheader()
        for row in results:
            e = row["evidence"]
            writer.writerow({**{k: row[k] for k in columns[:4]}, **{k: v["status"] for k,v in e["checks"].items()},
                "classification": e["classification"], "technical_E1_E6": row["technical_candidate_denominator"],
                "strict_candidate": e["candidate"], "confirmed": e["confirmed"], "usable_comparison": row["usable_original_Q_comparison"]})
    print(json.dumps({"cases": 60, "metrics": metrics["all60"], "agreement": combined_stats}))
