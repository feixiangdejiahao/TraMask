"""Compile and execute source-only materialization on independent toy packages."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.go_materialization import materialize_go_files


pytestmark = pytest.mark.skipif(shutil.which("go") is None, reason="Go compiler required")


def materialize(files, generated, controls=(), historical=(), repository=None):
    tests, obligations, originals = {}, [], []
    for role, rows in ((obligations, generated), (originals, controls)):
        for path, name in rows:
            key = path + ":1:" + name
            tests[key] = {"name": name}
            role.append({"path": path, "test_name": name, "base_test_id": key})
    selection = {"files": {path: {"kind": "historical_validation"} for path in historical}}
    return materialize_go_files(files, obligations, originals, {"tests": tests}, selection, repository=repository)


def test_module_local_package_name_comes_from_declaration(tmp_path):
    (tmp_path/'go.mod').write_text('module example.invalid/toy\n\ngo 1.18\n')
    (tmp_path/'odd_path').mkdir()
    (tmp_path/'odd_path/side.go').write_text('package actualname\nimport "os"\nfunc init(){os.Setenv("GO_MODULE_INIT", "yes")}\nfunc Value() int{return 7}\n')
    source = '''package toy
import "testing"
import "os"
import "example.invalid/toy/odd_path"
func TestGenerated(t *testing.T) { if os.Getenv("GO_MODULE_INIT") != "yes" { t.Fatal("init missing") } }
func TestUnselected(t *testing.T) { _ = actualname.Value() }
'''
    files, records = materialize({'history_test.go': source}, [('history_test.go', 'TestGenerated')],
                                historical=['history_test.go'], repository=tmp_path)
    assert 'import _ "example.invalid/toy/odd_path"' in files['history_test.go']
    (tmp_path/'history_test.go').write_text(files['history_test.go'])
    result = subprocess.run(['go', 'test', './...'], cwd=tmp_path,
                            env=dict(os.environ, GO111MODULE='on', GOPROXY='off'), capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def run_go(tmp_path, files):
    for path, code in files.items():
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(code)
    return subprocess.run(["go", "test", "-count=1", "-run", "TestGenerated|TestControl", "./..."],
                          cwd=tmp_path, env=dict(os.environ, GO111MODULE="off", GOCACHE=str(tmp_path / "cache")),
                          capture_output=True, text=True, timeout=120)


def test_unread_binding_preserves_setup_once_and_lexical_shadowing(tmp_path):
    control = 'func TestControl(t *testing.T) { x := setup(9); if x != 9 { t.Fatal(x) } }'
    source = '''package toy
import "testing"
var calls []int
type record struct { x int }
func setup(n int) int { calls = append(calls,n); return n }
func TestGenerated(t *testing.T) {
 calls = nil
 x := setup(1)
 kept := setup(2)
 { x := setup(3); if x != 3 { t.Fatal(x) } }
 var written = setup(4)
 written = 8
 _ = record{x:9}
 if kept != 2 || len(calls)!=4 { t.Fatal(calls) }
 for i,n := range calls { if n != i+1 { t.Fatal(calls) } }
}
''' + control + "\n"
    files, records = materialize({"toy_test.go": source}, [("toy_test.go", "TestGenerated")], [("toy_test.go", "TestControl")])
    assert control in files["toy_test.go"]
    edits = records[0]["edits"]
    assert sorted(edit["name"] for edit in edits) == ["written", "x"]
    assert len([edit for edit in edits if edit["name"] == "x"]) == 1
    result = run_go(tmp_path, files)
    assert result.returncode == 0, result.stdout + result.stderr


def test_closure_reads_and_multibindings_are_resolved_by_identity(tmp_path):
    source = '''package toy
import "testing"
func TestGenerated(t *testing.T) {
 x, y := 1, 2
 closure := func() int { return x }
 if closure()!=1 { t.Fatal("wrong") }
}
'''
    files, records = materialize({"toy_test.go": source}, [("toy_test.go", "TestGenerated")])
    assert [row["name"] for row in records[0]["edits"]] == ["y"]
    result = run_go(tmp_path, files)
    assert result.returncode == 0, result.stdout + result.stderr


def test_initializer_and_range_scopes_stay_explicitly_unsupported():
    source = '''package toy
import "testing"
func TestGenerated(t *testing.T) {
 if x := 1; true { t.Log("a") }
 for index, value := range []int{1} { t.Log("b") }
}
'''
    files, records = materialize({"toy_test.go": source}, [("toy_test.go", "TestGenerated")])
    assert files["toy_test.go"] == source
    assert any("initializer_scope:x" in row for row in records[0]["unsupported"])
    assert any("range_scope:index,value" in row for row in records[0]["unsupported"])


def test_historical_pruning_keeps_cross_file_test_dependencies_and_import_init(tmp_path):
    sources = {
        "one_test.go": '''package toy
import "testing"
func TestGenerated(t *testing.T) { TestDependency(t) }
func TestControl(t *testing.T) { TestDependency(t) }
func TestBroken(t *testing.T) { undefinedHistoricalAPI() }
''',
        "two_test.go": '''package toy
import ("testing"; "bytes"; named "strings")
func TestDependency(t *testing.T) { if helper()!=2 { t.Fatal("wrong") } }
func helper() int { return 2 }
func TestOtherBroken(t *testing.T) { _ = bytes.Buffer{}; _ = named.Builder{}; anotherMissingAPI() }
''',
    }
    files, records = materialize(sources, [("one_test.go", "TestGenerated")], [("one_test.go", "TestControl")], historical=sources)
    assert "func TestDependency" in files["two_test.go"]
    assert "func helper" in files["two_test.go"]
    assert "undefinedHistoricalAPI" not in files["one_test.go"]
    assert "anotherMissingAPI" not in files["two_test.go"]
    assert '_ "bytes"' in files["two_test.go"] and '_ "strings"' in files["two_test.go"]
    result = run_go(tmp_path, files)
    assert result.returncode == 0, result.stdout + result.stderr


def test_current_repository_source_tests_are_never_pruned():
    source = 'package toy\nimport "testing"\nfunc TestGenerated(t *testing.T) {}\nfunc TestOther(t *testing.T) {}\n'
    files, records = materialize({"toy_test.go": source}, [("toy_test.go", "TestGenerated")])
    assert files["toy_test.go"] == source
    assert records[0]["edits"] == []


def test_pruned_import_still_executes_package_init(tmp_path):
    source = '''package toy
import ("testing"; "os"; named "./side")
func TestGenerated(t *testing.T) {
 if os.Getenv("MATERIALIZER_TOY_INIT") != "ran" { t.Fatal("package init lost") }
}
func TestObsolete(t *testing.T) { _ = named.Marker; noLongerAvailable() }
'''
    files, _ = materialize({"toy_test.go": source}, [("toy_test.go", "TestGenerated")], historical=["toy_test.go"])
    files["side/side.go"] = '''package side
import "os"
const Marker = 1
func init() { os.Setenv("MATERIALIZER_TOY_INIT", "ran") }
'''
    assert '_ "./side"' in files["toy_test.go"]
    result = run_go(tmp_path, files)
    assert result.returncode == 0, result.stdout + result.stderr
