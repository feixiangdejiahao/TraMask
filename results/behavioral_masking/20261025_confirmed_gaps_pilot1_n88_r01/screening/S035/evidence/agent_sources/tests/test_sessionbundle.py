# encoding: utf-8
"""Tests for IPython.core.sessionbundle."""

# Copyright (c) IPython Development Team.
# Distributed under the terms of the Modified BSD License.

import zipfile
from pathlib import Path

import pytest

from IPython import get_ipython
from IPython.core import sessionbundle as sb


@pytest.fixture
def shell():
    return get_ipython()


def test_status_defaults_to_not_recording(shell):
    assert shell.session_bundle_status() == {"recording": False, "path": None}
    assert shell.run_line_magic("session_bundle", "status") == {
        "recording": False,
        "path": None,
    }


def test_start_stop_roundtrip(shell, tmp_path):
    target = tmp_path / "session"
    path = shell.start_session_bundle(target)
    assert path == str(tmp_path / "session.ipybundle")
    assert Path(path).exists()
    assert shell.session_bundle_status() == {"recording": True, "path": path}

    shell.run_cell("print('hello')", store_history=True)
    shell.run_cell("1 + 2", store_history=True)
    shell.run_cell("1/0", store_history=True)

    stopped = shell.stop_session_bundle()
    assert stopped == path
    assert shell.session_bundle_status() == {"recording": False, "path": None}

    metadata, events = sb.load_session_bundle(path)
    assert metadata["format"] == "ipython-session-bundle"
    assert metadata["format_version"] >= 1
    assert metadata["created_at"]
    assert metadata["ipython_version"]
    assert metadata["python_version"]
    assert metadata["platform"]
    assert metadata["redactions"] == []
    assert metadata["event_count"] == 3

    assert [e["code"] for e in events] == [
        "print('hello')",
        "1 + 2",
        "1/0",
    ]
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert events[0]["stdout"] == "hello\n"
    assert events[0]["success"] is True
    assert events[1]["execute_result"] == {"text/plain": "3"}
    assert events[2]["success"] is False
    assert "error" in events[2]
    assert events[2]["error"]["ename"] == "ZeroDivisionError"
    assert events[2]["error"]["traceback"]

    assert sb.validate_session_bundle(path, strict=False) == []


def test_start_raises_when_recording_active(shell, tmp_path):
    shell.start_session_bundle(tmp_path / "a")
    with pytest.raises(RuntimeError):
        shell.start_session_bundle(tmp_path / "b")
    shell.stop_session_bundle()


def test_start_raises_file_exists_without_overwrite(shell, tmp_path):
    path = tmp_path / "bundle.ipybundle"
    shell.start_session_bundle(path)
    shell.run_cell("x = 1", store_history=True)
    shell.stop_session_bundle()

    with pytest.raises(FileExistsError):
        shell.start_session_bundle(path)

    new_path = shell.start_session_bundle(path, overwrite=True)
    shell.run_cell("x = 2", store_history=True)
    shell.stop_session_bundle()
    _, events = sb.load_session_bundle(new_path)
    assert [e["code"] for e in events] == ["x = 2"]


def test_redaction(shell, tmp_path):
    path = tmp_path / "redacted.ipybundle"
    shell.start_session_bundle(path, redact=["SECRET", "pw"])
    shell.run_cell("print('SECRET pw')", store_history=True)
    shell.run_cell("'SECRET'", store_history=True)
    shell.stop_session_bundle()

    _, events = sb.load_session_bundle(path)
    assert events[0]["code"] == "print('<redacted> <redacted>')"
    assert events[0]["stdout"] == "<redacted> <redacted>\n"
    assert events[1]["execute_result"] == {"text/plain": "'<redacted>'"}

    with zipfile.ZipFile(path) as zf:
        raw = zf.read("events.jsonl").decode()
    assert "SECRET" not in raw
    assert "pw" not in raw


def test_magic_roundtrip(shell, tmp_path):
    target = tmp_path / "magic"
    ret = shell.run_line_magic("session_bundle", f"start {target}")
    assert ret == str(tmp_path / "magic.ipybundle")
    assert shell.run_line_magic("session_bundle", "status") == {
        "recording": True,
        "path": ret,
    }
    shell.run_cell("42", store_history=True)
    ret2 = shell.run_line_magic("session_bundle", "stop")
    assert ret2 == ret
    _, events = sb.load_session_bundle(ret2)
    assert [e["code"] for e in events] == ["42"]


def test_magic_start_stop_not_recorded(shell, tmp_path):
    target = tmp_path / "magic2.ipybundle"
    shell.run_cell(f"%session_bundle start {target}", store_history=True)
    shell.run_cell("1 + 1", store_history=True)
    shell.run_cell("%session_bundle stop", store_history=True)
    _, events = sb.load_session_bundle(target)
    assert [e["code"] for e in events] == ["1 + 1"]


def test_save_load_validate(shell, tmp_path):
    meta = {
        "format": "ipython-session-bundle",
        "format_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "ipython_version": "9",
        "python_version": "3.12",
        "platform": "test",
        "redactions": [],
    }
    events = [
        {
            "type": "cell",
            "seq": 1,
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "execution_count": 1,
            "code": "print('hi')",
            "success": True,
            "stdout": "hi\n",
            "stderr": "",
            "execute_result": {},
        }
    ]
    path = sb.save_session_bundle(tmp_path / "saved", meta, events)
    assert path == tmp_path / "saved.ipybundle"
    assert path.exists()
    assert sb.validate_session_bundle(path, strict=False) == []
    loaded_meta, loaded_events = sb.load_session_bundle(path)
    assert loaded_meta["event_count"] == 1
    assert loaded_events == events

    with pytest.raises(FileExistsError):
        sb.save_session_bundle(tmp_path / "saved", meta, events)


def test_validate_strict_raises_with_attributes(shell, tmp_path):
    meta = {
        "format": "ipython-session-bundle",
        "format_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "ipython_version": "9",
        "python_version": "3.12",
        "platform": "test",
        "redactions": [],
    }
    path = sb.save_session_bundle(tmp_path / "bad", meta, [])
    # corrupt it
    target = tmp_path / "bad.ipybundle"
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("metadata.json", "not json")
        zf.writestr("events.jsonl", "")

    errors = sb.validate_session_bundle(target, strict=False)
    assert errors
    with pytest.raises(sb.SessionBundleValidationError) as excinfo:
        sb.validate_session_bundle(target, strict=True)
    assert excinfo.value.bundle_path == target
    assert excinfo.value.errors == errors


def test_replay_history_and_errors(shell, tmp_path):
    path = tmp_path / "replay.ipybundle"
    shell.start_session_bundle(path)
    shell.run_cell("x = 5", store_history=True)
    shell.run_cell("x + 1", store_history=True)
    shell.stop_session_bundle()

    replay_shell = get_ipython()
    before = replay_shell.execution_count
    sb.replay_session_bundle(replay_shell, path, store_history=True)
    assert replay_shell.execution_count == before + 2
    assert replay_shell.user_ns["x"] == 5

    replay_shell2 = get_ipython()
    before = replay_shell2.execution_count
    sb.replay_session_bundle(replay_shell2, path, store_history=False)
    assert replay_shell2.execution_count == before
    assert replay_shell2.user_ns["x"] == 5


def test_replay_stop_on_error(shell, tmp_path):
    path = tmp_path / "err.ipybundle"
    shell.start_session_bundle(path)
    shell.run_cell("a = 1", store_history=True)
    shell.run_cell("1/0", store_history=True)
    shell.run_cell("a = 2", store_history=True)
    shell.stop_session_bundle()

    replay = get_ipython()
    with pytest.raises(ZeroDivisionError):
        sb.replay_session_bundle(replay, path, stop_on_error=True)
    assert replay.user_ns.get("a") == 1

    replay2 = get_ipython()
    sb.replay_session_bundle(replay2, path, stop_on_error=False)
    assert replay2.user_ns.get("a") == 2


def test_session_bundle_recorder_context_manager(shell, tmp_path):
    path = tmp_path / "ctx.ipybundle"
    with sb.session_bundle_recorder(shell, path) as yielded:
        assert yielded == str(path)
        assert shell.session_bundle_status()["recording"] is True
        shell.run_cell("v = 3", store_history=True)
    assert shell.session_bundle_status()["recording"] is False
    _, events = sb.load_session_bundle(path)
    assert [e["code"] for e in events] == ["v = 3"]


def test_semicolon_suppresses_execute_result(shell, tmp_path):
    path = tmp_path / "semi.ipybundle"
    shell.start_session_bundle(path)
    shell.run_cell("1 + 2;", store_history=True)
    shell.run_cell("3 + 4", store_history=True)
    shell.stop_session_bundle()
    _, events = sb.load_session_bundle(path)
    assert events[0]["execute_result"] == {}
    assert events[1]["execute_result"] == {"text/plain": "7"}


def test_records_store_history_false_cells(shell, tmp_path):
    path = tmp_path / "nohist.ipybundle"
    shell.start_session_bundle(path)
    before = shell.execution_count
    shell.run_cell("1 + 2", store_history=False)
    assert shell.execution_count == before
    shell.stop_session_bundle()
    _, events = sb.load_session_bundle(path)
    assert len(events) == 1
    assert events[0]["execute_result"] == {"text/plain": "3"}


def test_save_preserves_explicit_event_count_for_validation(shell, tmp_path):
    meta = {
        "format": "ipython-session-bundle",
        "format_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "ipython_version": "9",
        "python_version": "3.12",
        "platform": "test",
        "redactions": [],
        "event_count": 99,
    }
    events = [
        {
            "type": "cell",
            "seq": 1,
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "execution_count": 1,
            "code": "1",
            "success": True,
            "stdout": "",
            "stderr": "",
            "execute_result": {"text/plain": "1"},
        }
    ]
    path = sb.save_session_bundle(tmp_path / "mismatch", meta, events)
    assert sb.load_session_bundle(path)[0]["event_count"] == 99
    errors = sb.validate_session_bundle(path, strict=False)
    assert any("event_count" in error for error in errors)


def test_validate_flags_null_metadata(shell, tmp_path):
    target = tmp_path / "nullmeta.ipybundle"
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("metadata.json", "null")
        zf.writestr("events.jsonl", "")
    errors = sb.validate_session_bundle(target, strict=False)
    assert any("JSON object" in error for error in errors)
