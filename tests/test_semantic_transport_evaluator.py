"""Synthetic evaluation evidence only: no target repositories or provider calls."""
from pathlib import Path

import pytest

from scripts import evaluate_semantic_transport as evaluator


def put(path, data):
    evaluator.write_new(path, data)


def run(tests, **extra):
    return {"status": "fail" if any(row["status"] == "fail" for row in tests) else "pass",
            "errors": [], "counts": {}, "tests": tests,
            "process": {"returncode": int(any(row["status"] == "fail" for row in tests))},
            "transport": {"returncode": 0}, **extra}


def test_suite_error_with_empty_errors_never_yields_an_alarm_or_pass():
    result = run([{"id": "setup", "status": "error"}, {"id": "ctrl", "status": "pass"},
                  {"id": "generated", "status": "fail"}], status="error", counts={"error": 1})
    state = evaluator.obligation_state("generated", ["ctrl"], result)
    assert state["raw_failure"]
    assert not state["alarm"]
    assert not state["controls"]["passed"]
    result["tests"][2]["status"] = "pass"
    assert not evaluator.obligation_state("generated", ["ctrl"], result)["passed"]


@pytest.mark.parametrize("bad", ["fail", "skip", "error"])
def test_every_parameterized_source_control_leaf_must_pass(bad):
    result = run([{"id": "pkg::ctrl[a]", "status": "pass"},
                  {"id": "pkg::ctrl[b]", "status": bad},
                  {"id": "pkg::generated[x]", "status": "fail"}])
    assert not evaluator.obligation_state("generated", ["ctrl"], result)["alarm"]


def test_missing_and_undeclared_controls_are_not_vacuously_true():
    result = run([{"id": "pkg::generated", "status": "fail"}])
    assert not evaluator.obligation_state("generated", [], result)["alarm"]
    assert not evaluator.obligation_state("generated", ["absent"], result)["alarm"]


def test_parent_prefix_does_not_match_an_unrelated_test():
    result = run([{"id": "pkg::ctrl_extra", "status": "pass"},
                  {"id": "pkg::generated_extra", "status": "fail"}])
    state = evaluator.obligation_state("generated", ["ctrl"], result)
    assert not state["observed"]
    assert state["controls"]["missing"] == ["ctrl"]


def cell_fixture(root, case, round_id):
    base = root / case
    if not (base / "transport_prepare.json").exists():
        put(base / "transport_prepare.json", {"case_id": case, "declared_completion_rounds": ["r1", "r2"],
            "files_sha256": {}, "algorithm_sha256": {}, "transport_algorithm_sha256": {}})
    directory = base / "rounds" / round_id
    put(directory / "completion_round.json", {"status": "complete", "model_request_attempts": 1})
    put(directory / "completion/manifest.json", {"status": "complete", "valid": True, "files_sha256": {},
        "accepted": [{}], "rejected": [], "model_request_attempts": 1, "external_model_calls": 1,
        "usage": {"total_tokens": 20}})
    put(directory / "prepare.json", {"files_sha256": {},
        "transport_prepare_sha256": evaluator.digest(base / "transport_prepare.json")})
    manifest = directory / "frozen/direct/manifest.json"
    put(manifest, {"case_id": case, "files": [], "metadata": {"completion_round": round_id,
        "controls": ["ctrl"], "obligations": [{"id": "ctrl", "is_control": True},
            {"id": "generated", "controls": ["ctrl"]}]}})
    put(directory / "freezes/direct.json", {"artifact_sha256": evaluator.digest(manifest)})
    result = run([{"id": "ctrl", "status": "pass"}, {"id": "generated", "status": "fail"}],
                 case_id=case, program="candidate", artifact_sha256=evaluator.digest(manifest))
    put(directory / "execution/direct/candidate/result.json", result)
    return directory


def test_inventory_never_reads_reference_json_without_explicit_mode(tmp_path, monkeypatch):
    directory = cell_fixture(tmp_path, "P1", "r1")
    put(directory / "execution/direct/reference/result.json", {"not": "a real reference result"})
    original = evaluator.read
    def guarded(path):
        assert "reference" not in Path(path).parts
        return original(path)
    monkeypatch.setattr(evaluator, "read", guarded)
    cells = evaluator.inspect_matrix(tmp_path)
    assert len(cells) == 14
    assert cells[0]["frozen"]
    assert not cells[0]["reference_read"]
    assert cells[1]["status"] == "not_frozen"


def test_reference_agreement_cannot_confirm_unknown_oracle(tmp_path):
    directory = cell_fixture(tmp_path, "P1", "r1")
    manifest = directory / "frozen/direct/manifest.json"
    put(directory / "execution/direct/reference/result.json", run(
        [{"id": "ctrl", "status": "pass"}, {"id": "generated", "status": "pass"}],
        case_id="P1", program="reference", artifact_sha256=evaluator.digest(manifest)))
    cells = evaluator.inspect_matrix(tmp_path, include_reference=True)
    evaluator.apply_reviews(cells, {}, {})
    item = cells[0]["obligations"][0]
    assert item["differential_candidate"]
    assert item["unknown_oracle_alarm"]
    assert not item["confirmed_defect"]
    assert not evaluator.summarize(cells)["strict_two_round_success"]


def test_full_matrix_requires_independent_target_adjudication(tmp_path):
    for case in evaluator.CASES:
        for round_id in evaluator.ROUNDS:
            cell_fixture(tmp_path, case, round_id)
    cells = evaluator.inspect_matrix(tmp_path)
    template = evaluator.review_template(cells)
    reviews = {evaluator.review_key(row): dict(row, verdict="valid_oracle") for row in template}
    evaluator.apply_reviews(cells, reviews, {})
    assert evaluator.summarize(cells)["by_round"]["r1"]["unresolved_valid_alarm"] == 7
    decisions = {evaluator.review_key(row): {"confirmed_defect": True, "known_target": True,
                                           "root_cause_id": "same-root"} for row in template}
    evaluator.apply_reviews(cells, reviews, decisions)
    assert evaluator.summarize(cells)["strict_two_round_success"]
    # A single missing or skipped control prevents an apparently perfect run.
    cells[0]["obligations"][0]["candidate"]["controls"]["passed"] = False
    assert not evaluator.summarize(cells)["strict_two_round_success"]


def test_seal_covers_all_outputs_and_rejects_later_artifact_change(tmp_path):
    for case in evaluator.CASES:
        for round_id in evaluator.ROUNDS:
            cell_fixture(tmp_path, case, round_id)
    cells = evaluator.inspect_matrix(tmp_path)
    review = tmp_path / "review.json"
    template = evaluator.review_template(cells)
    put(review, {"reviews": [dict(row, reviewer="independent", reason="Unresolved contract") for row in template]})
    seal = evaluator.seal_reviews(tmp_path, review)
    sealed_path = tmp_path / "sealed.json"
    put(sealed_path, seal)
    assert len(evaluator.load_seal(sealed_path, cells)) == 14
    cells[0]["artifact_sha256"] = "changed"
    with pytest.raises(ValueError, match="Generation changed"):
        evaluator.load_seal(sealed_path, cells)


def test_seal_rejects_reference_access_before_label_freeze(tmp_path):
    for case in evaluator.CASES:
        for round_id in evaluator.ROUNDS:
            cell_fixture(tmp_path, case, round_id)
    (tmp_path / "P1/rounds/r1/execution/direct/reference").mkdir()
    with pytest.raises(ValueError, match="already exists"):
        evaluator.seal_reviews(tmp_path, tmp_path / "unused_reviews.json")


def test_freeze_failure_is_terminal_but_not_a_model_failure_or_success(tmp_path):
    directory = cell_fixture(tmp_path, "P1", "r1")
    (directory / "frozen/direct/manifest.json").unlink()
    log = tmp_path / "logs/freeze_P1_r1.log"
    log.parent.mkdir()
    log.write_text("ValueError: frozen cache comparison failed\n")
    put(tmp_path / "freeze_ledger.json", [{"case": "P1", "round": "r1", "stage": "freeze",
                                          "returncode": 1, "log": str(log)}])
    cells = evaluator.inspect_matrix(tmp_path)
    assert cells[0]["generation_terminal"]
    assert cells[0]["status"] == "mechanical_freeze_failed"
    assert not cells[0]["frozen"]
    assert not cells[0]["completion"]["protocol_failure"]
    summary = evaluator.summarize(cells)["by_round"]["r1"]
    assert summary["mechanical_freeze_failure_units"] == 1
    assert not summary["strict_success"]
