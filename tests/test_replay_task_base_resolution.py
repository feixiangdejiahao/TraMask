from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tramask_rerun.replay_v02 import Container, resolve_task_base_commit


CASE = {"base_commit": "7cef35bfdebd22148a4c62a10bf01f1fde36e722", "image": "original-task:image"}


def test_full_revision_does_not_need_a_container(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("No resolution needed for a full object ID")
    monkeypatch.setattr(Container, "_docker", unexpected)
    assert resolve_task_base_commit(CASE["base_commit"], CASE)["resolution"] == "already_full"


def test_short_revision_requires_unique_git_resolution(monkeypatch):
    calls = []
    def git(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=(CASE["base_commit"] + "\n").encode(), stderr=b"")
    monkeypatch.setattr(Container, "_docker", git)
    result = resolve_task_base_commit("7cef35b", CASE)
    assert result["resolved"] == CASE["base_commit"]
    assert calls[0][-2:] == ["rev-parse", "7cef35b^{commit}"]
    assert "--network" in calls[0] and "none" in calls[0]


@pytest.mark.parametrize("stdout,returncode", [(b"", 128), (b"7cef35b000000000000000000000000000000000000\n", 0)])
def test_ambiguous_or_wrong_object_is_rejected(monkeypatch, stdout, returncode):
    monkeypatch.setattr(Container, "_docker", lambda *args, **kwargs:
                        SimpleNamespace(returncode=returncode, stdout=stdout, stderr=b"ambiguous"))
    with pytest.raises(ValueError, match="does_not_resolve"):
        resolve_task_base_commit("7cef35b", CASE)
