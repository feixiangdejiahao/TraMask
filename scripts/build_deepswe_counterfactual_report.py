"""Assemble current manually authored judgments and render the portable bilingual reader.

No model calls, subject execution, semantic classification, or inferred labels.
The batch files and explicit adjudications are the sole source of decisions.
"""
from collections import Counter, defaultdict
from html import escape
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import quote

from result_paths import canonical_path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "research/deepswe_failure_manual_20261006"
STUDY = ROOT / "research/deepswe_counterfactual_review_20261021"
RUN = ROOT / "results/failure_analysis/20261021_counterfactual_gap_n211_r01"
DEST = ROOT / "docs/20261022_deepswe_failure_analysis_n211.html"
POSITIVE = {"supported", "plausible"}
OLD_POSITIVE = {"confirmed_combination_gap", "mixed_gap_and_selection"}
LABELS = {
    "supported": "存在组合缺口 · 直接支持",
    "plausible": "存在组合缺口 · 有条件支持",
    "unrelated": "未关联当前失败",
    "already_exposed": "正确失败反馈已暴露",
    "non_combination": "未建立组合联系 · 单项/接口问题",
    "insufficient": "证据不足 / 契约待定",
}
OLD_LABELS = {
    "confirmed_combination_gap": "旧：确认验证覆盖缺口",
    "mixed_gap_and_selection": "旧：覆盖缺口并有执行问题",
    "no_confirmed_combination_gap": "旧：未确认覆盖缺口",
    "selection_problem": "旧：测试执行问题",
}


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def receipt(path):
    path = Path(path)
    return {"path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size}


def verify_receipts(rows):
    errors = []
    for row in rows:
        path = ROOT / row["path"]
        if not path.is_file() or receipt(path)["sha256"] != row["sha256"]:
            errors.append(row["path"])
    assert not errors, f"Evidence changed or missing: {errors}"
    return len(rows)


def assemble():
    protocol = read(STUDY / "protocol.json")
    cohort = {r["trial_name"]: r for r in read(OLD / "cohort_audit.json")["trials"]}
    paths = sorted((OLD / "trials").glob("*.json"))
    batches = sorted(STUDY.glob("batch_*.json"))
    drafts = [dict(r, manual_batch=p.relative_to(ROOT).as_posix())
              for p in batches for r in read(p)]
    assert len(drafts) == len(paths) == len(cohort) == 211
    assert {r["n"] for r in drafts} == set(range(1, 212))
    assert len({r["n"] for r in drafts}) == 211
    changes = read(STUDY / "adjudications.json")
    assert len({r["n"] for r in changes}) == len(changes)
    changes = {r["n"]: r for r in changes}
    rows = []
    for draft in sorted(drafts, key=lambda r: r["n"]):
        row = dict(draft)
        if row["n"] in changes:
            row["initial_review_decision"] = row["decision"]
            row.update(changes[row["n"]])
        assert row["decision"] in LABELS
        for key in ("old_gaps", "evaluation", "validation", "counterfactual", "source_windows"):
            assert row.get(key), (row["n"], key)
        positive = row["decision"] in POSITIVE
        assert bool(row["combination"]) == positive, row["n"]
        assert (row["metric"] in ("F2P", "P2P", "F2P/P2P")) == positive, row["n"]
        if positive:
            assert "×" in row["combination"], row["n"]
        path = paths[row["n"] - 1]
        old = read(path)
        trial = path.stem
        assert old["trial"] == trial and trial in cohort
        raw = canonical_path(f"results/deepswe_failure_manual_20261006/trials/{trial}")
        ev = RUN / "evaluation" / trial
        metadata, reward = read(raw / "metadata.json"), read(ev / "reward.json")
        metrics = {k: reward[k] for k in ("f2p_passed", "f2p_total", "p2p_passed", "p2p_total")}
        assert metrics == {k: metadata[k] for k in metrics}, trial
        tests = read(ev / "ctrf.json")["results"]["tests"]
        failures = [t for t in tests if t["status"] not in ("passed", "skipped")]
        task = old["task"]
        assert task == cohort[trial]["task_name"]
        evidence = [path, raw / "instruction.md", raw / "model.patch", raw / "trajectory.json",
                    raw / "metadata.json", ev / "ctrf.json", ev / "reward.json", ev / "test-stdout.txt",
                    RUN / "evaluation_tests" / task / "test.patch",
                    RUN / "evaluation_tests" / task / "config.json"]
        row.update({
            "schema_version": "deepswe-counterfactual-review.v1",
            "review_date": protocol["date"], "trial": trial, "task": task,
            "repository": cohort[trial]["task_metadata"]["repository"],
            "language": old.get("observed_implementation_language", old["language"]),
            "old_verdict": old["verdict"], "old_verdict_reason": old["verdict_reason"],
            "old_positive_coverage_only": old["verdict"] in OLD_POSITIVE,
            "positive_under_current_definition": positive,
            "original_metrics": metrics,
            "actual_f2p_delta": None, "actual_p2p_delta": None,
            "repair_rerun": False, "reviewer": "primary AI assistant; manual per-trial review",
            "review_scope": protocol["reading_scope"],
            "evaluation_failed_tests": [{"name": t["name"], "status": t["status"],
                                          "missing_from_report": "missing from report" in t.get("message", "")}
                                         for t in failures],
            "source_receipts": [receipt(p) for p in evidence],
            "raw_evidence_directory": raw.relative_to(ROOT).as_posix(),
        })
        rows.append(row)
    assert len({r["trial"] for r in rows}) == 211
    assert len({r["task"] for r in rows}) == 90
    assert len({r["repository"] for r in rows}) == 75
    counts = Counter(r["decision"] for r in rows)
    transitions = Counter((r["old_verdict"], r["decision"]) for r in rows)
    task_rows = []
    for task in sorted({r["task"] for r in rows}):
        group = [r for r in rows if r["task"] == task]
        task_rows.append({"task": task, "trial_count": len(group),
                          "decisions": dict(Counter(r["decision"] for r in group)),
                          "trials": [r["trial"] for r in group]})
    summary = {
        "schema_version": "deepswe-counterfactual-summary.v1", "date": protocol["date"],
        "trials": len(rows), "tasks": len(task_rows), "repositories": 75,
        "reviewed": len(rows), "pending": 0, "decisions": dict(counts),
        "directly_supported": counts["supported"], "conditionally_supported": counts["plausible"],
        "positive_including_conditional": sum(counts[k] for k in POSITIVE),
        "old_coverage_positive": sum(r["old_positive_coverage_only"] for r in rows),
        "old_positive_to_current_positive": sum(r["old_positive_coverage_only"] and r["positive_under_current_definition"] for r in rows),
        "old_nonpositive_to_current_positive": sum(not r["old_positive_coverage_only"] and r["positive_under_current_definition"] for r in rows),
        "positive_incorrect_oracle": sum(r.get("gap_mode") == "incorrect_oracle" and r["positive_under_current_definition"] for r in rows),
        "decision_transitions": [{"old": old, "new": new, "trials": n} for (old, new), n in sorted(transitions.items())],
        "new_coding_agent_runs": 0, "new_subject_test_runs": 0,
        "actual_f2p_delta": None, "actual_p2p_delta": None,
        "causal_intervention_measured": False, "independent_second_review": False,
        "unit": "trial; parent/child CTRF rows are not independent defects",
        "tasks_detail": task_rows,
    }
    acquisition = read(RUN / "acquisition.json")
    assert acquisition["trials"] == 211 and len(acquisition["files"]) == 633 and not acquisition["errors"]
    acquired = verify_receipts(acquisition["files"])
    test_files = verify_receipts(read(RUN / "evaluation_tests/manifest.json")["records"])
    assert test_files == 180
    frozen = verify_receipts(read(RUN / "inputs/frozen_baseline.json")["files"])
    for row in rows:
        write(STUDY / "trials" / f'{row["trial"]}.json', row)
    (STUDY / "reviews.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    write(STUDY / "summary.json", summary)
    audit = {
        "status": "passed", "scope": "artifact integrity and cross-file consistency, not independent semantic validation",
        "unique_manual_trials": 211, "unique_tasks": 90, "unique_repositories": 75,
        "all_metrics_match_original_metadata": True,
        "evaluation_file_hashes_verified": acquired, "evaluation_test_file_hashes_verified": test_files,
        "frozen_historical_files_unchanged": frozen,
        "complete_counterfactual_fields": True, "actual_deltas_remain_unknown": True,
        "manual_input_receipts": [receipt(p) for p in batches + [STUDY / "adjudications.json", STUDY / "protocol.json"]],
        "output_receipts": [receipt(STUDY / "reviews.jsonl"), receipt(STUDY / "summary.json")],
    }
    write(STUDY / "audit.json", audit)
    return rows, summary, protocol


def render(rows, summary, protocol):
    from build_deepswe_standalone_report import render as render_portable
    return render_portable(rows, summary, protocol)


def run():
    rows, summary, protocol = assemble()
    render(rows, summary, protocol)
    print(json.dumps({"report": DEST.relative_to(ROOT).as_posix(), "reviewed": len(rows),
                      "decisions": summary["decisions"], "actual_score_gain": None}, ensure_ascii=False))


if __name__ == "__main__":
    run()
