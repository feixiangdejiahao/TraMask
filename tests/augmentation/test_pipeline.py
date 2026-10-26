import json
from pathlib import Path
import subprocess
import sys

import pytest

from augmentation.execution import execute
from augmentation.pipeline import build_request, generate, parse_response, prepare


@pytest.fixture
def prepared(tmp_path):
    repo = tmp_path / "subject"
    repo.mkdir()
    code = "def choose(a, b):\n    if a > 0 and b > 0:\n        return 1\n    return 0\n"
    (repo / "lib.py").write_text(code)
    (repo / "test_lib.py").write_text("from lib import choose\ndef test_original():\n assert choose(1, 0) == 0\n")
    patch = "--- a/lib.py\n+++ b/lib.py\n@@ -1,1 +1,4 @@\n" + "\n".join("+" + l for l in code.splitlines())
    return prepare(repo, patch, "Return 1 exactly when both inputs are positive.")


def response(prepared, code=None):
    return {"candidate_id": prepared["candidates"][0]["id"], "decision": "gap", "reason": "Both-positive case is absent.",
            "distinction": "Separate positive inputs versus jointly positive inputs.",
            "tests": [{"path": "test_augmentation.py", "mode": "new", "code": code or
                "from lib import choose\ndef test_joint():\n    # The public requirement requires both positives.\n    assert choose(1, 1) == 1\n"}],
            "existing_test_ids": []}


def test_request_and_one_step_generation_use_the_same_candidate(prepared, tmp_path):
    calls = []
    def provider(request, output, *, root):
        calls.append(request)
        output.mkdir()
        (output / "completion.txt").write_text(json.dumps(response(prepared)))
        return {"status": "complete", "external_model_calls": 0}
    result = generate(prepared, tmp_path / "generation", provider=provider)
    assert len(calls) == len(prepared["candidates"])
    assert all(row["status"] == "decoded" for row in result)
    assert "formal specification" in calls[0]["system"]
    assert (tmp_path / "generation" / "results.json").is_file()
    assert all((tmp_path / "generation" / r["candidate_id"] / "assessment.json").is_file() for r in result)


@pytest.mark.parametrize("path", ["../lib.py", "/tmp/test_escape.py", "lib.py", ".env", "tests/../lib.py", "tests\\test_bad.py"])
def test_generated_edits_stay_in_test_files(prepared, path):
    row = response(prepared)
    row["tests"][0]["path"] = path
    with pytest.raises(ValueError):
        parse_response(json.dumps(row), prepared, row["candidate_id"])


def test_selection_is_separate_from_generation(prepared):
    row = response(prepared)
    row.update(decision="selection_problem", tests=[], existing_test_ids=list(prepared["tests"]))
    decoded = parse_response(json.dumps(row), prepared, row["candidate_id"])
    assert decoded["decision"] == "selection_problem"
    assert not decoded["tests"]


def test_invalid_model_output_is_recorded_and_not_counted_as_no_gap(prepared, tmp_path):
    def provider(request, output, *, root):
        output.mkdir()
        (output / "completion.txt").write_text("not json")
        return {"status": "complete", "external_model_calls": 0}
    results = generate(prepared, tmp_path / "generation", provider=provider)
    assert all(r["status"] == "invalid_response" for r in results)
    assert all("response" not in r for r in results)


def test_isolated_execution_preserves_subject_and_reports_both_runs(prepared, tmp_path):
    subject = Path(prepared["repository"])
    before = {p.name: p.read_bytes() for p in subject.iterdir()}
    result = execute(prepared, response(prepared), tmp_path / "execution",
                     [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "{test_paths}"])
    assert result["baseline"]["status"] == "command_succeeded"
    assert result["augmented"]["status"] == "command_succeeded"
    assert {p.name: p.read_bytes() for p in subject.iterdir()} == before
    assert (tmp_path / "execution/repository/test_augmentation.py").is_file()


def test_failing_generated_test_is_kept_for_review(prepared, tmp_path):
    row = response(prepared, "def test_failure():\n    assert False\n")
    result = execute(prepared, row, tmp_path / "execution", [sys.executable, "-m", "pytest", "-q", "{test_paths}"])
    assert result["augmented"]["status"] == "command_failed"
    assert "patch defect" in result["interpretation"]
    assert "assert False" in (tmp_path / "execution/repository/test_augmentation.py").read_text()


def test_changed_subject_rejects_stale_preparation(prepared, tmp_path):
    (Path(prepared["repository"]) / "lib.py").write_text("changed")
    with pytest.raises(ValueError, match="prepared_source_changed"):
        execute(prepared, response(prepared), tmp_path / "execution", [sys.executable, "-m", "pytest"])


def test_repository_copy_redirects_internal_link_chains_and_omits_external_links(prepared, tmp_path):
    from augmentation.execution import _copy_repository
    subject = Path(prepared["repository"])
    original = (subject / "lib.py").read_text()
    (subject / "first.py").symlink_to(subject / "lib.py")
    (subject / "second.py").symlink_to(subject / "first.py")
    (subject / "around.py").symlink_to(Path("..") / subject.name / "lib.py")
    external = tmp_path / "outside.py"
    external.write_text("outside")
    (subject / "external.py").symlink_to(external)
    copied = tmp_path / "copied"
    _copy_repository(subject, copied)
    for name in ("first.py", "second.py", "around.py"):
        assert (copied / name).resolve() == copied / "lib.py"
        (copied / name).write_text("changed only in copy")
        assert (subject / "lib.py").read_text() == original
    assert not (copied / "external.py").exists()
    assert external.read_text() == "outside"


def test_append_keeps_original_test_and_executes_the_new_one(prepared, tmp_path):
    row = response(prepared)
    row["tests"][0].update(path="test_lib.py", mode="append")
    original = (Path(prepared["repository"]) / "test_lib.py").read_text()
    result = execute(prepared, row, tmp_path / "execution", [sys.executable, "-m", "pytest", "-q", "{test_paths}"])
    copied = (tmp_path / "execution/repository/test_lib.py").read_text()
    assert copied.startswith(original)
    assert "2 passed" in (tmp_path / "execution/augmented/stdout.txt").read_text()
    assert result["augmented"]["returncode"] == 0


def test_selection_execution_keeps_its_own_outcome(prepared, tmp_path):
    row = response(prepared)
    row.update(decision="selection_problem", tests=[], existing_test_ids=list(prepared["tests"]))
    result = execute(prepared, row, tmp_path / "selection_run", [sys.executable, "-m", "pytest", "-q", "{test_paths}"])
    assert result["decision"] == "selection_problem"
    assert result["execution"]["returncode"] == 0
    assert "augmented" not in result


def test_cli_help_lists_complete_pipeline():
    root = Path(__file__).resolve().parents[2]
    import os
    result = subprocess.run([sys.executable, "-m", "augmentation", "--help"], cwd=root,
                            env={**os.environ, "PYTHONPATH": str(root / "src")}, capture_output=True, text=True)
    assert result.returncode == 0
    assert all(word in result.stdout for word in ["prepare", "request", "generate", "execute"])
