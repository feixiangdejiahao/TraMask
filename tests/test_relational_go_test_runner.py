from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from combination_testing.test_reports import parse_report
from scripts import relational_go_test_runner as runner


GO = shutil.which("go")
requires_go = pytest.mark.skipif(GO is None, reason="Local Go toolchain unavailable")


def package(tmp_path: Path, code: str, *, subdirectory: str = "pkg") -> Path:
    (tmp_path / "go.mod").write_text("module example.test/isolation\n\ngo 1.18\n")
    directory = tmp_path / subdirectory
    directory.mkdir()
    (directory / "isolation_test.go").write_text(code)
    return directory


@requires_go
def test_hang_cannot_block_failure_or_pass_and_reports_remain_truthful(tmp_path, monkeypatch):
    monkeypatch.setenv("GOPROXY", "off")
    monkeypatch.setenv("GOTOOLCHAIN", "local")
    directory = package(tmp_path, '''package isolation
import ("os"; "testing"; "time")
var state int
func TestHang(t *testing.T) {
    state = 42
    t.Run("PartialFailure", func(t *testing.T) { t.Error("partial result before timeout") })
    os.WriteFile("started", []byte("yes"), 0600)
    for { time.Sleep(time.Second) }
}
func TestFail(t *testing.T) { t.Fatal("deliberate assertion failure") }
func TestPass(t *testing.T) {
    if state != 0 { t.Fatalf("process state leaked: %d", state) }
    if _, err := os.ReadFile("fixture.txt"); err != nil { t.Fatal(err) }
}
func TestPassExtra(t *testing.T) { t.Fatal("prefix must not select this test") }
''')
    (directory / "fixture.txt").write_text("package relative fixture")
    # Warm the system's standard-library compiler cache outside the small
    # measured test-process budget. The runner still compiles the package once
    # itself, and charges that compilation to its own deadline.
    subprocess.run([GO, "test", "-c", "-o", str(tmp_path / "warm.test"), "./pkg"],
                   cwd=tmp_path, check=True, capture_output=True, timeout=120)
    report = tmp_path / "logs" / "go.jsonl"
    started = time.monotonic()
    result = runner.run(["./pkg"], ["TestHang", "TestFail", "TestPass"], timeout=8,
                        report=report, repository=tmp_path, go=GO)
    elapsed = time.monotonic() - started
    assert elapsed < 9
    assert result["status"] == "error" and result["exit_code"] == 2
    assert [(row["test"], row["status"]) for row in result["tests"]] == [
        ("TestHang", "timeout"), ("TestFail", "fail"), ("TestPass", "pass")]
    assert (directory / "started").is_file()
    assert result["packages"][0]["compilation"]["returncode"] == 0
    events = [json.loads(line) for line in report.read_text().splitlines()]
    assert any(event.get("Test") == "TestHang" and event["Action"] == "run" for event in events)
    assert not any(event.get("Test", "").startswith("TestHang") and event["Action"] in runner.TERMINAL
                   for event in events)
    raw_hang = Path(result["tests"][0]["process"]["stdout"]).read_text()
    assert "partial result before timeout" in raw_hang
    assert not any(event.get("Test") == "TestPassExtra" for event in events)
    parsed = parse_report(report.parent, {"format": "go-json", "path": report.name},
                          {"returncode": result["exit_code"], "error": "isolated_test_timeout"})
    assert parsed["counts"] == {"pass": 1, "fail": 1, "error": 0, "skip": 0}
    assert parsed["status"] == "error"
    assert [row["id"].split("::")[-1] for row in parsed["tests"]] == ["TestFail", "TestPass"]
    for index, row in enumerate(result["tests"]):
        assert row["process"]["allowance_seconds"] <= 8 / (3 - index)
    assert json.loads((report.parent / "go.runner.json").read_text())["counts"]["timeout"] == 1


@requires_go
def test_compile_failure_keeps_build_output_without_fake_outcomes(tmp_path, monkeypatch):
    monkeypatch.setenv("GOPROXY", "off")
    package(tmp_path, '''package isolation
import "testing"
func TestBroken(t *testing.T) { noSuchFunction() }
''')
    report = tmp_path / "go.jsonl"
    result = runner.run(["./pkg"], ["TestBroken"], timeout=30,
                        report=report, repository=tmp_path, go=GO)
    assert result["exit_code"] == 2
    assert result["packages"][0]["status"] == "compile_error"
    assert "noSuchFunction" in Path(result["packages"][0]["build_output"]).read_text()
    assert result["tests"] == [{"package": "./pkg", "test": "TestBroken", "status": "not_run",
                                "reason": "compile_error"}]
    assert report.read_text() == ""
    assert parse_report(tmp_path, {"format": "go-json", "path": report.name},
                        {"returncode": 2})["status"] == "error"


@requires_go
def test_exact_subtest_selection_and_missing_name_are_not_fake_passes(tmp_path):
    directory = package(tmp_path, '''package isolation
import ("os"; "testing")
func TestCases(t *testing.T) {
    t.Run("literal[0]+", func(t *testing.T) {})
    t.Run("other", func(t *testing.T) { os.WriteFile("wrong-subtest", []byte("bad"), 0600) })
}
''')
    result = runner.run(["./pkg"], ["TestCases/literal[0]+", "TestMissing"], timeout=30,
                        report=tmp_path / "go.jsonl", repository=tmp_path, go=GO)
    assert [(row["test"], row["status"]) for row in result["tests"]] == [
        ("TestCases/literal[0]+", "pass"), ("TestMissing", "missing_outcome")]
    assert not (directory / "wrong-subtest").exists()
    assert result["exit_code"] == 2


def test_compilation_is_charged_to_the_shared_deadline(tmp_path):
    fake_go = tmp_path / "fake-go"
    fake_go.write_text(f'''#!{sys.executable}
import json, sys, time
if sys.argv[1] == "list":
    print(json.dumps({{"Dir": {str(tmp_path)!r}, "ImportPath": "toy"}}))
else:
    time.sleep(10)
''')
    fake_go.chmod(0o755)
    started = time.monotonic()
    result = runner.run(["./pkg"], ["TestLater"], timeout=0.4,
                        report=tmp_path / "go.jsonl", repository=tmp_path, go=str(fake_go))
    assert time.monotonic() - started < 1.2
    assert result["packages"][0]["status"] == "compile_timeout"
    assert result["tests"][0]["status"] == "not_run"
    assert result["exit_code"] == 2


@requires_go
def test_cli_json_file_multiple_packages_and_package_working_directories(tmp_path):
    directory = package(tmp_path, '''package isolation
import ("os"; "testing")
func TestFirst(t *testing.T) {
    if _, err := os.ReadFile("first.txt"); err != nil { t.Fatal(err) }
}
''')
    (directory / "first.txt").write_text("one")
    second = tmp_path / "second"
    second.mkdir()
    (second / "second.txt").write_text("two")
    (second / "second_test.go").write_text('''package second
import ("os"; "testing")
func TestSecond(t *testing.T) {
    if _, err := os.ReadFile("second.txt"); err != nil { t.Fatal(err) }
}
''')
    selection = tmp_path / "selected.json"
    selection.write_text(json.dumps({"./pkg": ["TestFirst"], "./second": ["TestSecond"]}))
    completed = subprocess.run([
        sys.executable, str(Path(runner.__file__).resolve()), "--package", "./pkg", "--package", "./second",
        "--tests", "@" + str(selection), "--timeout", "30", "--report", str(tmp_path / "go.jsonl"),
        "--repository", str(tmp_path), "--go", GO,
    ], capture_output=True, text=True, timeout=40)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads((tmp_path / "go.runner.json").read_text())
    assert result["counts"] == {"pass": 2}
    assert len(result["packages"]) == 2
    assert all(row["compilation"]["command"][1:3] == ["test", "-c"] for row in result["packages"])


@pytest.mark.parametrize("packages, tests", [
    (["./..."], ["TestA"]), (["./pkg"], []), (["./pkg"], {"./other": ["TestA"]}),
    (["./pkg"], ["TestA//x"]), (["./pkg"], ["TestA\nTestB"]),
])
def test_invalid_selection_rejected(packages, tests, tmp_path):
    with pytest.raises(ValueError):
        runner.run(packages, tests, timeout=1, report=tmp_path / "go.jsonl")
