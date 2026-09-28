"""Evaluation must not promote retrieval, invalid runs, or stale evidence."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.evaluate_relational_gap import digest, evaluate, inventory, parent_hit, matches_runtime


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def experiment(tmp_path):
    batch = tmp_path / "batch"
    folder = batch / "P1"
    folder.mkdir(parents=True)
    source = "tests/test_input.py:10:test_anchor"
    census = tmp_path / "census.json"
    dump(census, {"cases": [{"case": "P1", "source_tests": [{"id": source, "role": "primary", "name": "test_anchor", "path_aliases": ["tests/test_input.py"]}]}]})
    dump(folder / "candidates.json", {"candidates": [{"id": "candidate", "base_test_id": source}]})
    dump(folder / "selection.json", {"selected_test_ids": [source], "files": {}})
    dump(folder / "prepare.json", {"case": "P1", "status": "prepared", "files_sha256": {name: digest(folder / name) for name in ("candidates.json", "selection.json")}})
    generated = tmp_path / "generated/result.json"
    control = tmp_path / "control/result.json"
    dump(generated, {"returncode": 1, "tests": [{"id": "test_generated", "status": "fail"}]})
    dump(control, {"returncode": 0, "tests": [{"id": "test_original", "status": "pass"}]})
    runs = tmp_path / "runs.json"
    dump(runs, [{"case": "P1", "candidate_id": "candidate", "role": "generated", "result": str(generated), "test_ids": ["test_generated"]},
                {"case": "P1", "candidate_id": "candidate", "role": "control", "result": str(control), "test_ids": ["test_original"]}])
    return SimpleNamespace(batch_root=batch, census=census, runs=runs, reviews=tmp_path / "reviews.json", generated=generated, control=control)


def fill_reviews(experiment, *, semantic=True):
    document = inventory(experiment)
    if semantic:
        evidence = {"path": str(experiment.census), "sha256": digest(experiment.census)}
        for row in document["candidates"]:
            for field in row["review"].values():
                field.update(verdict="yes", reason="Independent fixture judgment", evidence=[evidence])
    dump(experiment.reviews, document)


def test_retrieval_and_runtime_failure_do_not_prove_semantics(experiment):
    fill_reviews(experiment, semantic=False)
    report = evaluate(experiment)
    assert report["counts"]["test_hit"] == 1
    assert report["candidates"][0]["generated_test_failure"]
    assert report["candidates"][0]["control_pass"]
    assert report["counts"]["target_gap_detected"] == 0
    assert not report["all_17_targets_proven"]


def test_all_independent_dimensions_can_support_one_target(experiment):
    fill_reviews(experiment)
    report = evaluate(experiment)
    assert report["counts"]["all_dimensions_proven"] == 1
    assert not report["all_17_targets_proven"]  # one fixture is not seventeen


def test_exit_failure_without_named_test_result_is_not_target_detection(experiment):
    dump(experiment.generated, {"returncode": 1})
    fill_reviews(experiment)
    report = evaluate(experiment)
    assert not report["candidates"][0]["generated_test_failure"]
    assert report["counts"]["target_gap_detected"] == 0


def test_failed_control_blocks_otherwise_reviewed_failure(experiment):
    dump(experiment.control, {"returncode": 1, "tests": [{"id": "test_original", "status": "fail"}]})
    fill_reviews(experiment)
    assert evaluate(experiment)["counts"]["target_gap_detected"] == 0


def test_unobserved_declared_control_is_not_pass(experiment):
    dump(experiment.control, {"returncode": 0, "tests": [{"id": "different_test", "status": "pass"}]})
    fill_reviews(experiment)
    assert evaluate(experiment)["counts"]["target_gap_detected"] == 0


def test_stale_generated_artifact_is_rejected(experiment):
    fill_reviews(experiment)
    file = experiment.batch_root / "P1/candidates.json"
    file.write_text(file.read_text() + " ")
    with pytest.raises(ValueError, match="Frozen evidence changed"):
        evaluate(experiment)


def test_editing_runtime_index_in_review_is_rejected(experiment):
    fill_reviews(experiment)
    document = json.loads(experiment.reviews.read_text())
    document["runs"][0]["test_ids"] = ["unrelated"]
    dump(experiment.reviews, document)
    with pytest.raises(ValueError, match="execution index"):
        evaluate(experiment)


def test_parent_match_requires_source_identity():
    target = {"source_tests": [{"role": "primary", "id": "one.py:3:test_x", "name": "test_x", "path_aliases": ["one.py", "/tmp/test_x.py"]}]}
    assert not parent_hit("other.py:3:test_x", target, {})
    assert parent_hit("one.py:20:test_x", target, {})
    assert parent_hit("relocated.py:2:test_x", target, {"files": {"relocated.py": {"original_written_path": "/tmp/test_x.py"}}})


def test_package_qualified_subtests_match_declared_parent():
    assert matches_runtime("example.org/project::TestGenerated/case_a", "TestGenerated")
    assert matches_runtime("tests.module::test_generated[value]", "test_generated")
    assert not matches_runtime("example.org/project::TestGeneratedOther/case_a", "TestGenerated")
