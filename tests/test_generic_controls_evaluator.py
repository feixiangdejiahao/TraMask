import json

import pytest

from combination_testing.runner import freeze_artifact
from scripts.evaluate_generic_controls import audit_cell, load_reviews, sha256, summarize


def make_cell(tmp_path, *, seed="pass", errors=None, negative=False):
    artifact = tmp_path / "X/frozen/r1"
    freeze_artifact(artifact, "X", {}, "true", "jsonl", "stdout.txt", metadata={
        "candidate_count": 1, "accepted_candidate_ids": ["candidate"], "controls": ["seed"],
        "obligations": [{"id": "generated", "candidate_id": "candidate", "controls": ["seed"]}]})
    artifact_hash = sha256(artifact / "manifest.json")
    for program, status in (("candidate", "fail"), ("reference", "pass")):
        output = tmp_path / "X/execution/r1" / program
        output.mkdir(parents=True)
        (output / "result.json").write_text(json.dumps({"artifact_sha256": artifact_hash, "status": status,
            "errors": errors or [] if program == "candidate" else [],
            "tests": [{"id": "seed", "status": seed if program == "candidate" else "pass"},
                      {"id": "generated", "status": status, "kind": "assertion"}]}))
    assets = {"root": tmp_path, "truth": {"X": {"candidate_known_correct": negative, "rows": [{"expected": 1}]}}}
    return assets, artifact_hash


def test_reference_pass_is_unknown_without_independent_review(tmp_path):
    assets, _ = make_cell(tmp_path)
    result = audit_cell(tmp_path, {"id": "X"}, "r1", assets, {})
    assert result["counts"]["differential_candidate"] == 1
    assert result["counts"]["semantic_unknown_alarms"] == 1
    assert result["counts"]["confirmed_defect"] == 0


@pytest.mark.parametrize("seed,errors,disposition", [
    ("fail", [], "source_controls_failed_or_missing"),
    ("skip", [], "source_controls_failed_or_missing"),
    ("pass", ["partial timeout"], "infrastructure"),
])
def test_source_failures_and_partial_reports_do_not_become_defects(tmp_path, seed, errors, disposition):
    assets, artifact_hash = make_cell(tmp_path, seed=seed, errors=errors)
    reviews = {("X", "r1", "generated", artifact_hash): {"verdict": "valid_in_sealed_domain"}}
    result = audit_cell(tmp_path, {"id": "X"}, "r1", assets, reviews)
    assert result["obligations"][0]["disposition"] == disposition
    assert result["counts"]["confirmed_defect"] == result["counts"]["candidate_alarms"] == 0


def test_confirmed_fault_requires_semantics_and_flags_negative_contradiction(tmp_path):
    assets, artifact_hash = make_cell(tmp_path)
    reviews = {("X", "r1", "generated", artifact_hash): {"verdict": "valid_by_contract"}}
    result = audit_cell(tmp_path, {"id": "X"}, "r1", assets, reviews)
    assert result["counts"]["confirmed_defect"] == 1
    assets["truth"]["X"]["candidate_known_correct"] = True
    result = audit_cell(tmp_path, {"id": "X"}, "r1", assets, reviews)
    assert result["counts"]["confirmed_defect"] == 0
    assert result["counts"]["negative_control_semantic_contradiction"] == 1


def test_review_cannot_use_reference_agreement_as_its_basis(tmp_path):
    assets, artifact_hash = make_cell(tmp_path)
    path = tmp_path / "reviews.json"
    path.write_text(json.dumps([{"case_id": "X", "variant": "r1", "id": "generated", "artifact_sha256": artifact_hash,
        "verdict": "valid_by_contract", "reviewer": "auditor", "basis": "reference passed", "basis_kind": "reference_pass"}]))
    with pytest.raises(ValueError, match="not an independent oracle basis"):
        load_reviews(path, assets)


def test_missing_or_zero_output_cases_stay_in_fault_denominator(tmp_path):
    assets = {"truth": {"X": {"candidate_known_correct": False, "rows": []}}}
    cells = [audit_cell(tmp_path, {"id": "X"}, variant, assets, {}) for variant in ("r1", "r2", "direct")]
    result = summarize(cells, assets)
    assert all(row["known_fault_cases"] == 1 and row["known_fault_cases_detected"] == 0 for row in result.values())
    assert result["r1"]["status_counts"] == {"not_frozen": 1}
