"""Synthetic full-text files only; no containers, provider, or historical labels."""
import hashlib

import pytest

from tramask_rerun import variants


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def data():
    files = {"app/code.py": "def value():\n    return 1\n", "tmp/test.py": "setup = 0\nresult = value()\nassert result == 1\n"}
    h = {"status": "proposed", "reason": "synthetic", "original_command": "python /tmp/test.py",
         "target": {"source_path": "app/code.py", "behavior": "value", "anchor": "return", "logical_effect": "value", "public_observation": "result"},
         "alternative": {"kind": "targeted_mutation", "rationale": "synthetic", "action_ids": [],
                         "edits": [{"path": "app/code.py", "old": "return 1", "new": "return 2"}]},
         "instrumentation": {"command": "python /tmp/test.py", "noninterference": "pending", "shared_anchors": [
             {"id": "effect", "channel": "effect", "p_location": "return", "q_location": "return", "meaning": "same"},
             {"id": "observation", "channel": "observation", "p_location": "assert", "q_location": "assert", "meaning": "same"}],
             "common_edits": [{"path": "tmp/test.py", "old": "assert result == 1\n", "new": "print('PROBE', result)\nassert result == 1\n"}],
             "p_edits": [{"path": "app/code.py", "old": "    return 1\n", "new": "    print('EFFECT', 1)\n    return 1\n"}],
             "q_edits": [{"path": "app/code.py", "old": "    return 2\n", "new": "    print('EFFECT', 2)\n    return 2\n"}],
             "helper_files": [{"path": "tmp/helper.py", "content": "# measurement helper\n"}]}}
    return files, h


def candidate(rank=1):
    return {"rank": rank, "status": "proposed", "factor": "setup", "location": "tmp/test.py",
            "current_state": "zero", "proposed_state": "one", "evidence_refs": ["issue"],
            "contract_justification": "public contract", "semantic_factor_count": 1, "change_scope": "context_only",
            **{flag: True for flag in variants.FLAGS},
            "edits": [{"path": "tmp/test.py", "old": "setup = 0", "new": "setup = 1"}],
            "operation_groups": [{"factor": "setup", "operations": [{"id": "op1", "description": "initialize", "edit_indices": [0]}]}]}


def context(files=None):
    value = {"original_command": "python /tmp/test.py", "editable_paths": ["/tmp/test.py"],
             "available_evidence_refs": ["issue"], "edit_policy": "context_only", "candidate_slots": 5,
             "max_semantic_factors": 2, "max_atomic_setup_operations": 8}
    if files is not None:
        value["source_files"] = files
    return value


def response(first=None):
    return {"original_command": "python /tmp/test.py", "candidates": [first or candidate()] + [
        {"rank": i, "status": "no_proposal", "reason": "not enough evidence"} for i in range(2, 6)]}


def test_four_variants_use_original_checkpoint_hashes_and_explicit_helper(data, tmp_path):
    files, h = data
    result = variants.stage_hypothesis(files, h, tmp_path / "stage", test_paths=["tmp/test.py"])
    maps = result["variants"]
    assert maps["p_original"]["files"] == {}
    assert maps["q_original"]["files"]["/app/code.py"] == {"content": files["app/code.py"].replace("return 1", "return 2"), "before_sha256": sha(files["app/code.py"])}
    assert maps["q_instrumented"]["files"]["/app/code.py"]["before_sha256"] == sha(files["app/code.py"])
    assert maps["q_instrumented"]["files"]["/tmp/test.py"]["before_sha256"] == sha(files["tmp/test.py"])
    assert maps["p_instrumented"]["files"]["/tmp/helper.py"]["new_file"] is True
    assert "return 2" in maps["q_instrumented"]["full_text"]["app/code.py"]
    assert result["E7"] is None and not result["executed"]
    assert files == data[0] and "PROBE" not in files["tmp/test.py"]


def test_repeated_anchor_and_overlap_fail_before_output_creation(data, tmp_path):
    files, h = data
    files["app/code.py"] += "# return 1\n"
    with pytest.raises(ValueError, match="exactly_once"):
        variants.stage_hypothesis(files, h, tmp_path / "repeat")
    assert not (tmp_path / "repeat").exists()
    files["app/code.py"] = "def value():\n    return 1\n"
    h["alternative"]["edits"].append({"path": "app/code.py", "old": "return 1\n", "new": "return 3\n"})
    with pytest.raises(ValueError, match="overlapping"):
        variants.stage_hypothesis(files, h, tmp_path / "overlap")
    assert not (tmp_path / "overlap").exists()


@pytest.mark.parametrize("path", ["app/../secret", "/etc/passwd", "app//file", "app/.git/config", "tmp/../../outside"])
def test_path_escape_is_rejected(data, tmp_path, path):
    files, h = data
    h["alternative"]["edits"][0]["path"] = path
    with pytest.raises(ValueError):
        variants.stage_hypothesis(files, h, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_symlink_output_and_nonregular_origin_rejected(data, tmp_path):
    files, h = data
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        variants.stage_hypothesis(files, h, alias / "escape")
    assert not (real / "escape").exists()
    with pytest.raises(ValueError, match="not_regular"):
        variants.stage_hypothesis(files, h, tmp_path / "out", source_origins={"tmp/test.py": {"kind": "symlink"}})


def test_file_directory_collision_cannot_hide_behind_intervening_filename(data, tmp_path):
    files, h = data
    files.update({"app/a": "file", "app/a-other": "other", "app/a/child": "child"})
    with pytest.raises(ValueError, match="file_directory_collision"):
        variants.stage_hypothesis(files, h, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_candidate_merges_probe_and_keeps_Q_fixed(data, tmp_path):
    files, h = data
    c = candidate()
    # A broad exact anchor may include the probe location; only its actual
    # changed span conflicts. This edit changes setup and preserves the assert.
    c["edits"] = [{"path": "tmp/test.py", "old": files["tmp/test.py"], "new": files["tmp/test.py"].replace("setup = 0", "setup = 1")}]
    result = variants.stage_candidate(files, h, c, tmp_path / "out", ["tmp/test.py"])
    for name in variants.VARIANTS:
        text = result["variants"][name]["full_text"]["tmp/test.py"]
        assert "setup = 1" in text
        assert ("print('PROBE', result)" in text) == name.endswith("_instrumented")
    assert "return 2" in result["variants"]["q_original"]["full_text"]["app/code.py"]
    assert result["variants"]["q_instrumented"]["files"]["/tmp/test.py"]["before_sha256"] == sha(files["tmp/test.py"])
    assert result["fixed_Q_preserved"] and result["E7"] is None


def test_probe_candidate_same_position_insertion_conflict_and_production_forbidden(data, tmp_path):
    files, h = data
    c = candidate()
    c["edits"] = [{"path": "tmp/test.py", "old": "assert result == 1\n", "new": "print('CANDIDATE')\nassert result == 1\n"}]
    with pytest.raises(ValueError, match="merge_conflict"):
        variants.stage_candidate(files, h, c, tmp_path / "conflict", ["tmp/test.py"])
    assert not (tmp_path / "conflict").exists()
    c["edits"] = [{"path": "app/code.py", "old": "return 1", "new": "return 9"}]
    with pytest.raises(ValueError, match="test_allowlist"):
        variants.stage_candidate(files, h, c, tmp_path / "production", ["tmp/test.py"])
    c["edits"] = [{"path": "tmp/test.py", "old": files["tmp/test.py"], "new": ""}]
    with pytest.raises(ValueError, match="merge_conflict"):
        variants.stage_candidate(files, h, c, tmp_path / "delete_probe", ["tmp/test.py"])


def test_missing_capsule_is_never_recovered_and_explicit_origin_is_new_file(data, tmp_path):
    files, h = data
    missing = {k: v for k, v in files.items() if k != "tmp/test.py"}
    with pytest.raises(ValueError):
        variants.stage_hypothesis(missing, h, tmp_path / "missing")
    origin = {"tmp/test.py": {"kind": "historical_test_capsule", "new_file": True, "sha256": sha(files["tmp/test.py"])}}
    staged = variants.stage_hypothesis(files, h, tmp_path / "explicit", source_origins=origin)
    assert staged["variants"]["p_original"]["files"] == {"/tmp/test.py": {"content": files["tmp/test.py"], "new_file": True}}
    assert staged["checkpoint_before_hashes"]["/tmp/test.py"] is None


def test_candidate_response_validity_does_not_certify_preservation(data):
    files, _ = data
    result = variants.validate_candidate_response(response(), context(files))
    assert result["n_registered_slots"] == 5 and result["n_structurally_proposed"] == 1
    assert result["n_no_proposal"] == 4 and result["n_invalid"] == 0
    assert result["slots"][0]["E7"] is None
    assert result["slots"][0]["semantic_review"] == "pending_semantic_review"
    assert result["slots"][0]["anchor_validation"] == "verified"


@pytest.mark.parametrize("raw", ['```json\n{}\n```', '{"original_command":', '{"x":1,"x":2}', 'NaN'])
def test_malformed_response_preserves_five_invalid_slots(raw):
    result = variants.validate_candidate_response(raw, context())
    assert result["n_invalid"] == 5 and result["n_no_proposal"] == 0
    assert len(result["slots"]) == 5 and not result["syntax_repaired"]


def test_bad_rank_partial_slots_extra_slots_and_command_are_not_repaired():
    value = response()
    value["candidates"][1]["rank"] = 1
    result = variants.validate_candidate_response(value, context())
    assert result["n_invalid"] == 1 and result["slots"][1]["submitted_rank"] == 1
    for mutation in (lambda v: v["candidates"].pop(),
                     lambda v: v["candidates"].append({"rank": 6, "status": "no_proposal", "reason": "extra"}),
                     lambda v: v.update(original_command="different command")):
        value = response()
        mutation(value)
        result = variants.validate_candidate_response(value, context())
        assert result["n_invalid"] == 5 and len(result["slots"]) == 5


def test_operation_indices_and_claim_flags_fail_structurally_but_stay_in_denominator():
    c = candidate()
    c["operation_groups"][0]["operations"][0]["edit_indices"] = [0, 0]
    result = variants.validate_candidate_response(response(c), context())
    assert result["n_invalid"] == 1 and "exactly_one_operation" in result["slots"][0]["errors"][0]
    c = candidate()
    c["preserves_original_observation"] = False
    assert variants.validate_candidate_response(response(c), context())["n_invalid"] == 1
    c = candidate()
    c["new_observation"] = "self-certified replacement"
    assert variants.validate_candidate_response(response(c), context())["n_invalid"] == 1


def test_duplicate_candidates_and_missing_actual_anchors_are_invalid(data):
    files, _ = data
    value = response()
    value["candidates"][1] = candidate(rank=2)
    result = variants.validate_candidate_response(value, context(files))
    assert result["n_invalid"] == 1 and result["slots"][1]["errors"] == ["duplicate_candidate_edits"]
    value = response()
    value["candidates"][0]["edits"][0]["old"] = "not present"
    assert variants.validate_candidate_response(value, context(files))["n_invalid"] == 1


def test_context_factor_and_operation_budgets_are_enforced():
    c = candidate()
    c["semantic_factor_count"] = 3
    assert variants.validate_candidate_response(response(c), context())["n_invalid"] == 1
    c = candidate()
    c["edits"] = [{"path": "tmp/test.py", "old": f"old{i}", "new": f"new{i}"} for i in range(9)]
    c["operation_groups"][0]["operations"] = [
        {"id": f"op{i}", "description": "atomic setup", "edit_indices": [i]} for i in range(9)]
    result = variants.validate_candidate_response(response(c), context())
    assert result["n_invalid"] == 1 and result["slots"][0]["errors"] == ["atomic_operation_budget_exceeded"]


def test_reordered_identical_edits_do_not_create_another_candidate():
    value = response()
    first = candidate()
    first["edits"].append({"path": "tmp/test.py", "old": "state = 0", "new": "state = 1"})
    first["operation_groups"][0]["operations"][0]["edit_indices"] = [0, 1]
    second = {**first, "rank": 2, "edits": list(reversed(first["edits"]))}
    value["candidates"][:2] = [first, second]
    result = variants.validate_candidate_response(value, context())
    assert result["n_invalid"] == 1 and result["slots"][1]["errors"] == ["duplicate_candidate_edits"]
