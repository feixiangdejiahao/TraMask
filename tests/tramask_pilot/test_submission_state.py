"""Literal terminal-state validation against synthetic Git repositories."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tramask_pilot.submission_state import _COLLECT, compare_tracked_tree


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)
    git("init")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (root / "unchanged.txt").write_bytes(b"unchanged original\n")
    (root / "edited.bin").write_bytes(b"original\x00binary\n")
    (root / "deleted.txt").write_bytes(b"must disappear\n")
    (root / "script.sh").write_bytes(b"#!/bin/sh\nexit 0\n")
    (root / "link").symlink_to("unchanged.txt")
    (root / ".gitignore").write_text("ignored/\n")
    (root / "directory").mkdir()
    (root / "directory/child.txt").write_text("child content\n")
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD").decode().strip()
    (root / "edited.bin").write_bytes(b"new\x00binary\xff\n")
    (root / "deleted.txt").unlink()
    (root / "script.sh").chmod(0o755)
    (root / "link").unlink()
    (root / "link").symlink_to("edited.bin")
    (root / "new.txt").write_text("new submitted file\n")
    git("add", "-A")
    patch = tmp_path / "submitted.patch"
    patch.write_bytes(git("diff", "--cached", "--binary", base))
    git("reset", "--hard", base)
    git("apply", "--binary", str(patch))
    return root, git, base, patch


def collect(repository, tmp_path):
    root, _, base, patch = repository
    request = {"root": str(root), "base_commit": base, "patch": str(patch),
               "scratch_parent": str(tmp_path), "baseline_untracked": []}
    result = subprocess.run([sys.executable, "-c", _COLLECT], input=json.dumps(request).encode(),
                            capture_output=True, check=True)
    observation = json.loads(result.stdout)
    assert "construction_error" not in observation, observation.get("construction_error")
    return observation, compare_tracked_tree(observation)


def tree_identity(root):
    """Includes Git metadata, making accidental real-index/object writes visible."""
    result = {}
    for directory, _, names in os.walk(root):
        for name in names:
            path = Path(directory) / name
            result[str(path.relative_to(root))] = (
                path.lstat().st_mode,
                ("link", os.readlink(path)) if path.is_symlink()
                else ("bytes", hashlib.sha256(path.read_bytes()).hexdigest()),
            )
    return result


def test_full_expected_tree_matches_without_touching_subject_or_git_metadata(repository, tmp_path):
    root, _, _, _ = repository
    (root / "agent_test.py").write_text("independent untracked test\n")
    (root / "ignored").mkdir()
    (root / "ignored/cache").write_bytes(b"dependency cache")
    before = tree_identity(root)
    observation, report = collect(repository, tmp_path)
    assert report["tracked_tree_matches"]
    assert report["verified_absent_paths"] == 1
    assert report["expected_tracked_files"] == 7
    assert observation["expected"]["script.sh"]["mode"] == "100755"
    assert observation["actual"]["link"]["target"] == "edited.bin"
    assert [entry["path"] for entry in observation["untracked"]] == ["agent_test.py"]
    assert observation["ignored_entries"] == ["ignored/"]
    # new.txt is unstaged but part of the submitted tree, not an auxiliary file.
    assert "new.txt" not in observation["current_index"]
    assert tree_identity(root) == before
    assert not list(tmp_path.glob("expected-tree-*"))


def test_unchanged_files_deletions_and_unexpected_tracked_paths_are_checked(repository, tmp_path):
    root, git, _, _ = repository
    (root / "unchanged.txt").write_text("unintended alteration\n")
    (root / "deleted.txt").write_text("residual deleted file\n")
    (root / "unexpected.txt").write_text("an extra tracked source\n")
    git("add", "unexpected.txt")
    # Git normally hides this path from diff; raw comparison must still see it.
    git("update-index", "--assume-unchanged", "unchanged.txt")
    _, report = collect(repository, tmp_path)
    assert not report["tracked_tree_matches"]
    mismatches = {entry["path"]: entry for entry in report["mismatches"]}
    assert set(mismatches) == {"unchanged.txt", "deleted.txt", "unexpected.txt"}
    assert mismatches["unchanged.txt"]["reasons"] == ["literal_bytes_differ"]
    assert mismatches["deleted.txt"]["expected"] is None
    assert mismatches["unexpected.txt"]["expected"] is None


def test_modes_links_and_parent_symlinks_are_not_normalized_away(repository, tmp_path):
    root, _, _, _ = repository
    (root / "script.sh").chmod(0o644)
    (root / "link").unlink()
    (root / "link").symlink_to("unchanged.txt")
    (root / "directory/child.txt").unlink()
    (root / "directory").rmdir()
    external = tmp_path / "outside"
    external.mkdir()
    (external / "child.txt").write_text("child content\n")
    (root / "directory").symlink_to(external)
    observation, report = collect(repository, tmp_path)
    mismatches = {entry["path"]: entry for entry in report["mismatches"]}
    assert mismatches["script.sh"]["reasons"] == ["git_mode_differs"]
    assert mismatches["link"]["reasons"] == ["literal_bytes_differ"]
    # Even equal outside bytes cannot count as the original regular-file tree.
    assert observation["actual"]["directory/child.txt"] == {
        "kind": "blocked_ancestor", "ancestor": "directory", "ancestor_kind": "symlink"}
    assert "directory/child.txt" in mismatches


def test_raw_bytes_are_checked_even_when_git_clean_filters_hide_the_difference(repository, tmp_path):
    root, git, _, _ = repository
    (root / ".git/info/attributes").write_text("unchanged.txt text\n")
    (root / "unchanged.txt").write_bytes(b"unchanged original\r\n")
    assert git("diff", "--", "unchanged.txt") == b""
    _, report = collect(repository, tmp_path)
    assert [entry["path"] for entry in report["mismatches"]] == ["unchanged.txt"]
    assert report["mismatches"][0]["reasons"] == ["literal_bytes_differ"]


def test_unverified_reads_or_submodules_never_count_as_a_match():
    observation = {
        "base": {"module": {}}, "current_index": {"module": {}},
        "expected": {"module": {"mode": "160000", "oid": "a" * 40}},
        "actual": {"module": {"kind": "directory"}},
        "real_index_unchanged": True, "head_unchanged": True,
    }
    report = compare_tracked_tree(observation)
    assert report["status"] == "unverified" and not report["tracked_tree_matches"]
    observation["expected"]["module"]["mode"] = "100644"
    observation["actual"]["module"] = {"kind": "file", "unstable_during_read": True}
    report = compare_tracked_tree(observation)
    assert report["status"] == "unverified" and not report["tracked_tree_matches"]


def test_git_file_directory_transitions_do_not_reject_implicit_directories(repository, tmp_path):
    root, git, base, patch = repository
    git("reset", "--hard", base)
    # The earlier patch's new file is untracked after reset; remove it before
    # constructing this independent submitted patch.
    (root / "new.txt").unlink()
    (root / "deleted.txt").unlink()
    (root / "deleted.txt").mkdir()
    (root / "deleted.txt/new_child").write_text("new descendant\n")
    (root / "directory/child.txt").unlink()
    (root / "directory").rmdir()
    (root / "directory").symlink_to("deleted.txt")
    git("add", "-A")
    patch.write_bytes(git("diff", "--cached", "--binary", base))
    observation, report = collect(repository, tmp_path)
    assert report["tracked_tree_matches"], report
    assert observation["actual"]["deleted.txt"]["kind"] == "directory"
    assert observation["actual"]["directory/child.txt"]["kind"] == "blocked_ancestor"


def test_working_tree_match_does_not_hide_a_failed_commit(repository, tmp_path):
    """The submission hook exports HEAD, so unstaged or uncommitted fixes fail."""
    root, git, base, _ = repository
    git("add", "-A")
    # Simulate git add succeeding but the subsequent commit failing: the index
    # and working tree contain the right bytes while HEAD still points to base.
    before = tree_identity(root)
    observation, report = collect(repository, tmp_path)
    assert observation["head_before"] == base
    assert observation["expected_tree"] != observation["head_tree"]
    assert report["working_tree_matches_submitted_commit"]
    assert report["tracked_tree_matches"]
    assert report["index_tree_matches_submitted_commit"]
    assert report["submitted_commit_tree_matches"] is False
    assert report["submission_state_status"] == "mismatch"
    assert {row["path"] for row in report["committed_tree_mismatches"]} == {
        "deleted.txt", "edited.bin", "link", "new.txt", "script.sh"}
    assert tree_identity(root) == before


def test_committed_tree_match_does_not_hide_post_commit_working_tree_edits(repository, tmp_path):
    root, git, _, _ = repository
    git("add", "-A")
    git("commit", "-m", "submitted solution")
    (root / "unchanged.txt").write_text("unintended trailing mutation\n")
    before = tree_identity(root)
    observation, report = collect(repository, tmp_path)
    assert observation["expected_tree"] == observation["head_tree"]
    assert report["submitted_commit_tree_matches"]
    assert report["index_tree_matches_submitted_commit"]
    assert report["working_tree_matches_submitted_commit"] is False
    assert report["tracked_tree_matches"] is False
    assert report["submission_state_status"] == "mismatch"
    assert report["committed_tree_mismatches"] == []
    assert [row["path"] for row in report["mismatches"]] == ["unchanged.txt"]
    assert tree_identity(root) == before


def test_matching_committed_and_working_trees_are_distinct_verified_gates(repository, tmp_path):
    root, git, _, _ = repository
    git("add", "-A")
    git("commit", "-m", "submitted solution")
    before = tree_identity(root)
    _, report = collect(repository, tmp_path)
    assert report["submitted_commit_tree_matches"]
    assert report["working_tree_matches_submitted_commit"]
    assert report["index_tree_matches_submitted_commit"]
    assert report["submission_state_status"] == "matched"
    assert tree_identity(root) == before


@pytest.mark.parametrize("eol,should_match", [("crlf", True), ("lf", False)])
def test_expected_attributes_define_checkout_eol_without_normalizing_actual_bytes(
        repository, tmp_path, eol, should_match):
    root, git, base, patch = repository
    (root / ".gitattributes").write_text(f"unchanged.txt text eol={eol}\n")
    git("add", "-A")
    git("commit", "-m", "submitted solution and checkout attributes")
    patch.write_bytes(git("diff", "--binary", base, "HEAD"))
    (root / "unchanged.txt").write_bytes(b"unchanged original\r\n")
    # Git's clean conversion hides this difference even under eol=lf. The
    # validator must use independently materialized expected bytes instead.
    assert git("diff", "--", "unchanged.txt") == b""
    before = tree_identity(root)
    observation, report = collect(repository, tmp_path)
    assert report["submitted_commit_tree_matches"]
    assert report["working_tree_matches_submitted_commit"] is should_match
    assert observation["expected_attributes"]["unchanged.txt"]["eol"] == eol
    if should_match:
        assert observation["expected_checkout"]["unchanged.txt"]["sha256"] == hashlib.sha256(
            b"unchanged original\r\n").hexdigest()
        assert (observation["expected_checkout"]["unchanged.txt"]["oid"]
                != observation["expected"]["unchanged.txt"]["oid"])
    else:
        assert [row["path"] for row in report["mismatches"]] == ["unchanged.txt"]
    assert tree_identity(root) == before


def test_actual_attributes_cannot_override_the_expected_tree_checkout(repository, tmp_path):
    root, git, base, patch = repository
    (root / ".gitattributes").write_text("unchanged.txt text eol=lf\n")
    git("add", "-A")
    git("commit", "-m", "submitted LF tree")
    patch.write_bytes(git("diff", "--binary", base, "HEAD"))
    # Both the actual working .gitattributes and highest-priority info file
    # ask for CRLF, but neither may alter the independent expected LF checkout.
    (root / ".gitattributes").write_text("unchanged.txt text eol=crlf\n")
    (root / ".git/info/attributes").write_text("unchanged.txt text eol=crlf\n")
    (root / "unchanged.txt").write_bytes(b"unchanged original\r\n")
    observation, report = collect(repository, tmp_path)
    assert observation["expected_attributes"]["unchanged.txt"]["eol"] == "lf"
    assert report["submitted_commit_tree_matches"]
    assert {row["path"] for row in report["mismatches"]} == {".gitattributes", "unchanged.txt"}


def test_external_clean_smudge_filters_cannot_execute_or_forge_a_match(repository, tmp_path):
    root, git, base, patch = repository
    git("add", "-A")
    (root / ".gitattributes").write_text("unchanged.txt filter=forged\n")
    git("add", ".gitattributes")
    git("commit", "-m", "submitted tree requesting external filter")
    patch.write_bytes(git("diff", "--binary", base, "HEAD"))
    marker = tmp_path / "filter_executed"
    # Avoid shell interpolation of any path: the synthetic command receives
    # the marker as a literal, safely single-quoted argument.
    marker_argument = "'" + str(marker).replace("'", "'\\''") + "'"
    command = "touch " + marker_argument + "; printf 'unchanged original\\n'"
    git("config", "filter.forged.clean", command)
    git("config", "filter.forged.smudge", command)
    git("config", "filter.forged.required", "true")
    (root / "unchanged.txt").write_text("actual bytes are wrong\n")
    before = tree_identity(root)
    observation, report = collect(repository, tmp_path)
    assert not marker.exists(), "Validator must never execute repository filter commands"
    assert report["submitted_commit_tree_matches"]
    assert report["working_tree_matches_submitted_commit"] is False
    assert report["working_tree_status"] == "unverified"
    assert observation["expected_checkout_unverified"]["unchanged.txt"] == {
        "reason": "external_content_filter_refused", "filter": "forged"}
    assert tree_identity(root) == before


def test_actual_only_clean_filter_cannot_hide_changed_bytes(repository, tmp_path):
    root, git, _, _ = repository
    (root / ".git/info/attributes").write_text("unchanged.txt filter=forged\n")
    marker = tmp_path / "actual_filter_executed"
    marker_argument = "'" + str(marker).replace("'", "'\\''") + "'"
    command = "touch " + marker_argument + "; printf 'unchanged original\\n'"
    git("config", "filter.forged.clean", command)
    git("config", "filter.forged.smudge", command)
    (root / "unchanged.txt").write_text("actual bytes are wrong\n")
    observation, report = collect(repository, tmp_path)
    assert not marker.exists()
    assert observation["expected_attributes"]["unchanged.txt"]["filter"] == "unspecified"
    assert report["working_tree_matches_submitted_commit"] is False
    assert [row["path"] for row in report["mismatches"]] == ["unchanged.txt"]
