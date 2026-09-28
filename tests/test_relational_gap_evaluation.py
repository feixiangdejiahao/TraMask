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


def test_separate_source_phase_contexts_survive_later_timeout(experiment):
    rows = json.loads(experiment.runs.read_text())
    for row in rows:
        context = experiment.runs.parent / (row['role'] + '_context.json')
        dump(context, {'phase': row['role'], 'source_hash': row['role']})
        row['execution_context'] = {'phase': row['role'], 'context_file': str(context),
                                    'control_context': 'separate_unedited_source_snapshot'}
    dump(experiment.runs, rows)
    dump(experiment.generated, {'error': 'phase_timeout', 'timed_out': True, 'tests': []})
    fill_reviews(experiment)
    candidate = evaluate(experiment)['candidates'][0]
    assert candidate['control_pass']
    assert not candidate['generated_test_failure']
    assert not candidate['target_gap_detected']
    assert {row['phase'] for row in candidate['execution_contexts']} == {'control', 'generated'}
    context.write_text('changed context')
    with pytest.raises(ValueError, match='Frozen evidence changed'):
        evaluate(experiment)


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
    assert matches_runtime(" requiredIf gc_123", "requiredIf gc_123")
    assert not matches_runtime(" requiredIf gc_123_other", "requiredIf gc_123")


def test_parent_match_uses_explicit_go_relocation_provenance():
    target = {"source_tests": [{"role": "primary", "id": "old_test.go:3:TestOld", "name": "TestOld", "path_aliases": ["old_test.go"]}]}
    identifier = "relocated_test.go:8:TestOld_rh_123456789abc"
    metadata = {"kind": "historical_validation", "original_target_path": "old_test.go",
                "relocated_globals": ["TestOld"], "sha256": "123456789abc" + "0" * 52}
    assert parent_hit(identifier, target, {"files": {"relocated_test.go": metadata}})
    assert not parent_hit(identifier, target, {"files": {"relocated_test.go": {"original_target_path": "old_test.go"}}})
    assert not parent_hit(identifier, target, {"files": {"relocated_test.go": {**metadata, "sha256": "f" * 64}}})


def test_parent_match_uses_explicit_script_wrapper_provenance():
    target = {"source_tests": [{"role": "primary", "id": "trajectory/step-1.py:1:<script>", "name": "<script>", "path_aliases": ["trajectory/step-1.py"]}]}
    identifier = "test_relocated.py:5:test_relational_script_a"
    selection = {"files": {"test_relocated.py": {"trajectory_source": "trajectory/step-1.py"}},
                 "script_wrappers": [{"source_path": "test_relocated.py", "wrapper_name": "test_relational_script_a", "status": "wrapped"}]}
    assert parent_hit(identifier, target, selection)
    assert not parent_hit(identifier, target, {**selection, "script_wrappers": []})
    assert not parent_hit("other.py:5:test_relational_script_a", target, selection)


def test_atomic_candidate_requires_frozen_parent_and_unchanged_sources(experiment):
    experiment.emitted_root = experiment.batch_root.parent / "emitted"
    accepted = experiment.emitted_root / "P1/accepted.json"
    child = {"id": "q_atomic", "parent_candidate_id": "candidate",
             "base_test_id": "tests/test_input.py:10:test_anchor"}
    dump(accepted, [child])
    runs = json.loads(experiment.runs.read_text())
    for row in runs:
        row["candidate_id"] = "q_atomic"
    dump(experiment.runs, runs)
    fill_reviews(experiment)
    report = evaluate(experiment)
    assert report["counts"]["all_dimensions_proven"] == 1
    assert len(report["candidates"]) == 2
    dump(accepted, [{**child, "base_test_id": "other.py:1:test_other"}])
    with pytest.raises(ValueError, match="changed source-parent provenance"):
        inventory(experiment)


def test_shared_control_binding_stays_within_execution_manifest(experiment):
    first, second = experiment.batch_root.parent / "a.json", experiment.batch_root.parent / "b.json"
    dump(first, {})
    dump(second, {})
    bad_control = experiment.batch_root.parent / "bad_control.json"
    dump(bad_control, {"tests": [{"id": "test_original", "status": "fail"}]})
    dump(experiment.runs, [
        {"case": "P1", "candidate_id": "candidate", "role": "generated", "manifest": str(first),
         "result": str(experiment.generated), "test_ids": ["test_generated"], "control_ids": ["test_original"]},
        {"case": "P1", "candidate_id": None, "role": "control", "manifest": str(first),
         "result": str(experiment.control), "test_ids": ["test_original"]},
        {"case": "P1", "candidate_id": None, "role": "control", "manifest": str(second),
         "result": str(bad_control), "test_ids": ["test_original"]},
    ])
    fill_reviews(experiment)
    report = evaluate(experiment)
    assert report["counts"]["all_dimensions_proven"] == 1
    assert report["candidates"][0]["control_runs"] == 1


def test_atomic_candidate_already_frozen_uses_exact_identity(experiment):
    experiment.emitted_root = experiment.batch_root.parent / "emitted"
    dump(experiment.emitted_root / "P1/accepted.json", [{"id": "candidate",
         "parent_candidate_id": "pre_atomic_internal_id", "base_test_id": "tests/test_input.py:10:test_anchor"}])
    fill_reviews(experiment)
    report = evaluate(experiment)
    assert len(report["candidates"]) == 1
    assert report["stage_counts"]["admitted_candidates"] == 1
    assert report["counts"]["all_dimensions_proven"] == 1
