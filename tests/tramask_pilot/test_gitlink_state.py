"""Read-only qualification against real local Git submodule fixtures."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tramask_pilot.gitlink_state import COLLECT_GITLINKS, compare_gitlink
from tramask_pilot.submission_state import _COLLECT, compare_tracked_tree


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)


def initialize(root):
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")


def collect(root):
    process = subprocess.run([sys.executable, "-I", "-c", COLLECT_GITLINKS],
        input=json.dumps({"root": str(root), "paths": ["vendor/module"]}).encode(),
        capture_output=True, check=True)
    return json.loads(process.stdout)


def identity(root):
    result = {}
    for directory, _, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            result[str(path.relative_to(root))] = (path.lstat().st_mode,
                os.readlink(path) if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest())
    return result


@pytest.fixture
def module_repository(tmp_path):
    source, root = tmp_path / "source", tmp_path / "parent"
    initialize(source)
    (source / "tracked.txt").write_text("original\n")
    (source / ".gitignore").write_text("ignored/\n")
    git(source, "add", ".")
    git(source, "commit", "-m", "module base")
    oid = git(source, "rev-parse", "HEAD").decode().strip()
    initialize(root)
    git(root, "-c", "protocol.file.allow=always", "submodule", "add", str(source), "vendor/module")
    git(root, "commit", "-am", "parent base")
    nested = root / "vendor/module"
    git(nested, "config", "user.name", "Fixture")
    git(nested, "config", "user.email", "fixture@example.invalid")
    (nested / "ignored").mkdir()
    (nested / "ignored/cache").write_bytes(b"original ignored state")
    return root, nested, {"mode": "160000", "oid": oid}, collect(root)


def test_unchanged_initialized_module_passes_without_any_git_metadata_write(module_repository):
    root, _, expected, baseline = module_repository
    before = identity(root)
    actual = collect(root)
    result = compare_gitlink(expected, baseline["gitlinks"]["vendor/module"], actual["gitlinks"]["vendor/module"])
    assert result["matched"], result
    assert actual["gitlinks"]["vendor/module"]["index_entries"] == actual["gitlinks"]["vendor/module"]["head_entries"]
    assert identity(root) == before


@pytest.mark.parametrize("change,reason", [
    ("dirty", "checkpoint_nested_worktree_not_clean"),
    ("index", "checkpoint_nested_index_differs_from_head"),
    ("head", "checkpoint_nested_head_differs_from_gitlink"),
    ("missing", "checkpoint_gitlink_missing_or_not_initialized"),
    ("ignored", "literal_submodule_tree_differs_from_original_image"),
])
def test_real_module_mismatches_cannot_qualify(module_repository, change, reason):
    root, nested, expected, baseline = module_repository
    if change in {"dirty", "index", "head"}:
        (nested / "tracked.txt").write_text("changed\n")
        if change in {"index", "head"}:
            git(nested, "add", "tracked.txt")
        if change == "head":
            git(nested, "commit", "-m", "different nested head")
    elif change == "missing":
        shutil.rmtree(nested)
    else:
        (nested / "ignored/cache").write_bytes(b"different ignored state")
        assert git(nested, "status", "--porcelain") == b""
    before = identity(root)
    actual = collect(root)
    result = compare_gitlink(expected, baseline["gitlinks"]["vendor/module"], actual["gitlinks"]["vendor/module"])
    assert result["status"] == "mismatch", result
    assert reason in result["reasons"]
    assert identity(root) == before


def test_submission_report_uses_bound_gitlink_evidence_and_still_detects_dirt(module_repository, tmp_path):
    root, nested, _, baseline = module_repository
    base = git(root, "rev-parse", "HEAD").decode().strip()
    patch = tmp_path / "empty.patch"
    patch.write_bytes(b"")
    request = {"root": str(root), "base_commit": base, "patch": str(patch),
               "scratch_parent": str(tmp_path), "baseline_untracked": []}
    observation = json.loads(subprocess.run([sys.executable, "-c", _COLLECT],
        input=json.dumps(request).encode(), capture_output=True, check=True).stdout)
    assert compare_tracked_tree(observation)["submission_state_status"] == "unverified"
    observation["gitlink_evidence"] = {"base_commit": base, "original": baseline, "checkpoint": collect(root)}
    report = compare_tracked_tree(observation)
    assert report["submission_state_status"] == "matched", report
    assert len(report["qualified_gitlinks"]) == 1
    unbound = copy.deepcopy(observation)
    unbound["gitlink_evidence"]["original"]["parent_head"] = "0" * 40
    assert compare_tracked_tree(unbound)["submission_state_status"] == "unverified"
    (nested / "tracked.txt").write_text("dirty\n")
    observation["gitlink_evidence"]["checkpoint"] = collect(root)
    assert compare_tracked_tree(observation)["submission_state_status"] == "mismatch"


def test_absent_original_or_nested_gitlinks_remain_unverified(module_repository):
    root, _, expected, baseline = module_repository
    actual = collect(root)["gitlinks"]["vendor/module"]
    assert compare_gitlink(expected, None, actual)["status"] == "unverified"
    original = baseline["gitlinks"]["vendor/module"]
    actual["nested_gitlinks"] = ["another/module"]
    assert compare_gitlink(expected, original, actual)["status"] == "unverified"
