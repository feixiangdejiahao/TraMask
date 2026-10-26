"""Synthetic metadata/raw files and mocked downloads; never use real held-out data."""
import hashlib
import json
from pathlib import Path

import pytest

from tramask_rerun import sampling


def receipt(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def fixture_metadata(tmp_path):
    prompt = tmp_path / "prompts.py"
    prompt.write_text("frozen synthetic prompts\n")
    protocol = {"freeze_status": sampling.FROZEN_STATUS,
                "sampling": {"reserved": {"failed": 15, "successful": 5, "seed": "new-seed", "replacements": False}},
                "implementation_receipts": [receipt(prompt)]}
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol))
    candidates, rows = {"failed_order": [], "successful_order": []}, []
    for cohort, count in [("failed", 18), ("successful", 8)]:
        for i in range(count):
            task = f"{cohort}-{i}"
            old_trial = task + "__oldseed"
            candidates[cohort + "_order"].append({
                "id": f"{cohort}-{i}", "task": task, "trial": old_trial,
                "task_directory": str(tmp_path / "NEVER_READ_TASKS" / task),
                "old_source_path": str(tmp_path / "NEVER_READ_RAW" / old_trial) if cohort == "failed" else None,
                "prior_registered_method_pilots": ["older-method"] if i == 0 else [],
                "eligible_under_recommended_extra_pilot_exclusion": i != 0})
            for trial in [old_trial, task + "__a", task + "__b"]:
                rows.append({"trial_name": trial, "task_name": task, "source": "deep-swe",
                             "model": "deepseek-v4-flash", "outcome": "fail" if cohort == "failed" else "pass",
                             "has_trajectory": True, "has_model_patch": True})
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"rows": rows}))
    audit = {"source_index": {"path": str(index)}, "sources": [receipt(index)],
             "candidate_metadata_order": candidates,
             "corrected_submission_checkpoints": {"cases": [{"task": "failed-1"}, {"task": "successful-1"}]},
             "calibration": {"cases": []}, "exposure": {}, "excluded_metadata": []}
    return audit, protocol_path


def test_selection_uses_new_seed_and_full_index_without_reading_raw_files(tmp_path, monkeypatch):
    audit, protocol = fixture_metadata(tmp_path)
    original = Path.read_bytes
    def guarded(path):
        assert "NEVER_READ" not in str(path)
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    result = sampling.choose_reserved(audit, protocol)
    assert result["counts"] == {"failed": 15, "successful": 5, "distinct_issues": 20}
    assert [r["id"] for r in result["cases"]] == [f"HF{i:03}" for i in range(1, 16)] + [f"HS{i:03}" for i in range(1, 6)]
    assert not {r["task"] for r in result["cases"]} & {"failed-0", "failed-1", "successful-0", "successful-1"}
    order = lambda x: (hashlib.sha256(("new-seed:" + x).encode()).hexdigest(), x)
    changed_trial = False
    for row in result["cases"]:
        choices = [row["task"] + suffix for suffix in ["__oldseed", "__a", "__b"]]
        assert row["trial"] == min(choices, key=order)
        changed_trial |= row["trial"] != row["metadata_template_trial"]
        if row["source"]:
            assert Path(row["source"]).name == row["trial"]
    assert changed_trial and result["subject_content_read"] is False
    assert result == sampling.choose_reserved(audit, protocol)


def test_unfrozen_changed_prompts_and_index_fail_closed(tmp_path):
    audit, protocol_path = fixture_metadata(tmp_path)
    protocol = json.loads(protocol_path.read_text())
    protocol["freeze_status"] = "draft"
    protocol_path.write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="not_frozen"):
        sampling.choose_reserved(audit, protocol_path)
    protocol["freeze_status"] = sampling.FROZEN_STATUS
    protocol_path.write_text(json.dumps(protocol))
    prompt = Path(protocol["implementation_receipts"][0]["path"])
    prompt.write_text("changed")
    with pytest.raises(ValueError, match="receipt_mismatch"):
        sampling.choose_reserved(audit, protocol_path)
    prompt.write_text("frozen synthetic prompts\n")
    Path(audit["source_index"]["path"]).write_text('{"rows": []}')
    with pytest.raises(ValueError, match="index_receipt"):
        sampling.choose_reserved(audit, protocol_path)


def test_insufficient_pool_does_not_relax_exclusions_or_replace(tmp_path):
    audit, protocol = fixture_metadata(tmp_path)
    audit["candidate_metadata_order"]["failed_order"][2]["prior_registered_method_pilots"] = ["prior"]
    audit["candidate_metadata_order"]["failed_order"][3]["prior_registered_method_pilots"] = ["prior"]
    with pytest.raises(ValueError, match="insufficient_independent_failed"):
        sampling.choose_reserved(audit, protocol)


def test_success_issue_overlap_and_unqualified_index_trials_do_not_enter_sample(tmp_path):
    audit, protocol = fixture_metadata(tmp_path)
    first = sampling.choose_reserved(audit, protocol)
    chosen_failure = first["cases"][0]
    source_template = next(r for r in audit["candidate_metadata_order"]["failed_order"]
                           if r["task"] == chosen_failure["task"])
    audit["candidate_metadata_order"]["successful_order"].append({
        **source_template, "old_source_path": None})
    index = Path(audit["source_index"]["path"])
    rows = json.loads(index.read_text())["rows"]
    valid = next(r for r in rows if r["trial_name"] == chosen_failure["trial"])
    rows.append({**valid, "trial_name": valid["task_name"] + "__successful", "outcome": "pass"})
    rows.extend([{**valid, "trial_name": "wrong-model", "model": "different-model"},
                 {**valid, "trial_name": "missing-trajectory", "has_trajectory": False},
                 {**valid, "trial_name": "missing-patch", "has_model_patch": False}])
    index.write_text(json.dumps({"rows": rows}))
    audit["sources"] = [receipt(index)]
    result = sampling.choose_reserved(audit, protocol)
    assert len({r["task"] for r in result["cases"]}) == 20
    assert not {r["trial"] for r in result["cases"]} & {"wrong-model", "missing-trajectory", "missing-patch"}
    assert any(e["task"] == chosen_failure["task"] and e["reasons"] == ["selected_failed_issue"]
               for e in result["exclusions"])


def raw_case(tmp_path, remote=False):
    source, tasks = tmp_path / "raw" / "trial__1", tmp_path / "tasks" / "task"
    source.mkdir(parents=True)
    tasks.mkdir(parents=True)
    for name in sampling.INPUT_NAMES:
        (source / name).write_bytes(b"synthetic raw \xff " + name.encode())
        if name in {"instruction.md", "task.toml"}:
            (tasks / name).write_bytes((source / name).read_bytes())
    return {"id": "HF001", "task": "task", "trial": "trial__1", "task_directory": str(tasks),
            "rawfailmetadata_source": None if remote else {"path": str(source / "metadata.json")},
            "api_key": "SHOULD_NOT_BE_WRITTEN", "provider_url": "https://user:secret@example.test"}


def test_raw_metadata_path_copy_receipts_and_idempotence(tmp_path, monkeypatch):
    case = raw_case(tmp_path)
    monkeypatch.setattr(sampling, "_download_public", lambda url: pytest.fail("unexpected network"))
    destination = tmp_path / "inputs"
    result = sampling.acquire_case(case, destination)
    assert result == sampling.acquire_case(case, destination)
    assert [Path(r["receipt"]["path"]).name for r in result["files"]] == list(sampling.INPUT_NAMES)
    for row in result["files"]:
        assert row["source_receipt"]["sha256"] == row["receipt"]["sha256"]
    assert not (Path(case["rawfailmetadata_source"]["path"])).exists()
    artifact = (destination / "provenance.json").read_text()
    assert "SHOULD_NOT_BE_WRITTEN" not in artifact and "user:secret" not in artifact
    (destination / "trajectory.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="receipt_mismatch"):
        sampling.acquire_case(case, destination)


def test_public_files_fetched_once_each_and_existing_unreceipted_file_refused(tmp_path, monkeypatch):
    case = raw_case(tmp_path, remote=True)
    urls = []
    def download(url):
        urls.append(url)
        return b"public fake " + url.rsplit("/", 1)[-1].encode()
    monkeypatch.setattr(sampling, "_download_public", download)
    dest = tmp_path / "inputs"
    sampling.acquire_case(case, dest)
    sampling.acquire_case(case, dest)
    assert len(urls) == len(set(urls)) == 2
    assert all(u.startswith(sampling.PUBLIC_ROOT) for u in urls)
    other = tmp_path / "unknown"
    other.mkdir()
    (other / "model.patch").write_text("unknown existing bytes")
    with pytest.raises(ValueError, match="unreceipted_existing"):
        sampling.acquire_case(case, other)
    assert len(urls) == 2


def test_failed_fetch_never_retries_or_records_sensitive_error_message(tmp_path, monkeypatch):
    case = raw_case(tmp_path, remote=True)
    attempts = []
    def fail(url):
        attempts.append(url)
        raise RuntimeError("https://user:password@private.test?token=SECRET")
    monkeypatch.setattr(sampling, "_download_public", fail)
    dest = tmp_path / "inputs"
    with pytest.raises(RuntimeError, match="public_artifact_fetch_failed"):
        sampling.acquire_case(case, dest)
    with pytest.raises(RuntimeError, match="previous_fetch_failed"):
        sampling.acquire_case(case, dest)
    assert len(attempts) == 1
    artifact = (dest / "acquisition.json").read_text()
    assert "SECRET" not in artifact and "password" not in artifact and "private.test" not in artifact


def test_source_change_url_trial_and_symlink_target_rejected(tmp_path, monkeypatch):
    case = raw_case(tmp_path)
    monkeypatch.setattr(sampling, "_download_public", lambda url: pytest.fail("unexpected network"))
    dest = tmp_path / "inputs"
    sampling.acquire_case(case, dest)
    (Path(case["rawfailmetadata_source"]["path"]).parent / "instruction.md").write_text("changed source")
    with pytest.raises(ValueError, match="source_changed"):
        sampling.acquire_case(case, dest)
    with pytest.raises(ValueError, match="invalid_trial"):
        sampling.acquire_case({**case, "trial": "https://user:pw@example.test"}, tmp_path / "bad")
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "instruction.md").symlink_to(dest / "instruction.md")
    with pytest.raises(ValueError, match="symlink_input_artifact"):
        sampling.acquire_case(case, linked)
