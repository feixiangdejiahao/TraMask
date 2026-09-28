"""Independent historical Go helper binding/closure examples."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.history import namespace_go_validation
from scripts.go_history_dependencies import recover_go_dependencies


pytestmark = pytest.mark.skipif(shutil.which("go") is None, reason="Go compiler required")


def history(code, path="helpers.go", step=1):
    digest = hashlib.sha256(code.encode()).hexdigest()
    destination = str(Path(path).with_name(Path(path).stem + "_rh_" + digest[:12] + "_test.go"))
    renamed, names = namespace_go_validation(Source(destination, code, "go"), digest[:12])
    return destination, renamed.code, {"kind": "historical_validation", "sha256": digest,
                                      "relocated_globals": names, "original_target_path": path,
                                      "step_id": step}


def recover(tmp_path, source, *donors, step=10, extra=None):
    corpus = {"sources": {p: {"code": c} for p, c, _ in donors}}
    selection = {"files": {p: m for p, _, m in donors}}
    selection["files"]["caller_test.go"] = {"kind": "historical_validation", "step_id": step}
    return recover_go_dependencies({"caller_test.go": source, **(extra or {})}, corpus, selection, tmp_path)


def run_go(tmp_path, files):
    for path, code in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code)
    result = subprocess.run(["go", "test", "-count=1", "./..."], cwd=tmp_path,
                            env=dict(os.environ, GO111MODULE="off"), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_transitive_import_closure_and_shadowed_local_remain_source_exact(tmp_path):
    donor = history('''package toy
import "strings"
func helper(s string) string { return leaf(s) }
func leaf(s string) string { return strings.ToUpper(s) }
''')
    caller = '''package toy
import "testing"
func TestRecovered(t *testing.T) {
 { helper := func(string) string { return "local" }; if helper("x") != "local" { t.Fatal("shadow") } }
 if helper("ok") != "OK" { t.Fatal("dependency") }
}
'''
    files, records = recover(tmp_path, caller, donor)
    assert len(files) == 3
    assert 'helper := func(string)' in files["caller_test.go"]
    assert 'helper("x")' in files["caller_test.go"]
    assert len([r for r in records if r["status"] == "recovered"]) == 1
    assert any('import "strings"' in code for code in files.values())
    run_go(tmp_path, files)


def test_ambiguous_different_original_paths_do_not_copy_or_rewrite(tmp_path):
    first = history("package toy\nfunc helper() int { return 1 }", "one.go", 1)
    second = history("package toy\nfunc helper() int { return 2 }", "two.go", 2)
    caller = "package toy\nfunc use() int { return helper() }\n"
    files, records = recover(tmp_path, caller, first, second)
    assert files == {"caller_test.go": caller}
    assert records[0]["reason"] == "ambiguous_source_definitions"


def test_latest_prior_only_for_proven_same_original_path(tmp_path):
    first = history("package toy\nfunc helper() int { return 1 }", step=1)
    second = history("package toy\nfunc helper() int { return 2 }", step=3)
    third = history("package toy\nfunc helper() int { return 3 }", step=9)
    caller = 'package toy\nimport "testing"\nfunc TestRecovered(t *testing.T) { if helper()!=2 { t.Fatal("version") } }'
    files, records = recover(tmp_path, caller, first, second, third, step=5)
    assert records[0]["declarations"][0]["resolution"] == "latest_prior_source_version"
    run_go(tmp_path, files)


def test_exact_existing_package_binding_wins(tmp_path):
    donor = history("package toy\nfunc helper() int { return 9 }")
    (tmp_path / "existing.go").write_text("package toy\nfunc helper() int { return 4 }\n")
    caller = "package toy\nfunc use() int { return helper() }\n"
    files, records = recover(tmp_path, caller, donor)
    assert files == {"caller_test.go": caller}
    assert records == []


def test_canonical_leaf_duplicates_restore_recorded_names_only(tmp_path):
    first = history("package toy\nfunc helper() string { return `helper_rh_unrelated` }", "one.go")
    second = history("package toy\n\nfunc helper() string { return `helper_rh_unrelated` }", "two.go")
    files, records = recover(tmp_path, "package toy\nfunc use() string { return helper() }", first, second)
    assert len(files) == 2
    assert records[0]["declarations"][0]["resolution"] == "identical_canonical_source_definitions"
    assert "`helper_rh_unrelated`" in "\n".join(files.values())


def test_unrecorded_suffix_is_never_guessed(tmp_path):
    donor = history("package toy\nfunc helper() int { return 1 }")
    donor[2]["relocated_globals"] = ["different"]
    caller = "package toy\nfunc use() int { return helper() }"
    files, records = recover(tmp_path, caller, donor)
    assert files == {"caller_test.go": caller}
    assert records[0]["reason"] == "no_source_definition"


def test_missing_transitive_dependency_rolls_back_whole_recovery(tmp_path):
    donor = history("package toy\nfunc helper() int { return missing() }")
    caller = "package toy\nfunc use() int { return helper() }"
    files, records = recover(tmp_path, caller, donor)
    assert files == {"caller_test.go": caller}
    assert records[0]["dependency"] == "missing"


def test_recursive_function_and_mutable_package_state_closure(tmp_path):
    donor = history('''package toy
var state int
func helper(n int) int { state = n; if n == 0 { return state }; return helper(n-1) + 1 }
''')
    caller = 'package toy\nimport "testing"\nfunc TestRecovered(t *testing.T) { if helper(3)!=3 { t.Fatal("recursion") } }'
    files, records = recover(tmp_path, caller, donor)
    assert all(r["status"] == "recovered" for r in records)
    assert len(files) == 3
    run_go(tmp_path, files)


def test_type_methods_and_struct_field_keys(tmp_path):
    donor = history('''package toy
type box struct { value int }
func (b box) read() int { return b.value }
func helper() int { return (box{value:7}).read() }
''')
    caller = 'package toy\nimport "testing"\nfunc TestRecovered(t *testing.T) { if helper()!=7 { t.Fatal("type closure") } }'
    files, records = recover(tmp_path, caller, donor)
    assert all(r["status"] == "recovered" for r in records)
    run_go(tmp_path, files)


def test_module_import_name_resolved_from_package_source(tmp_path):
    (tmp_path / "go.mod").write_text("module example.invalid/toy\n\ngo 1.18\n")
    (tmp_path / "odd_path").mkdir()
    (tmp_path / "odd_path" / "value.go").write_text("package actualname\nfunc Value() int { return 8 }")
    donor = history('package toy\nimport "example.invalid/toy/odd_path"\nfunc helper() int { return actualname.Value() }')
    caller = "package toy\nfunc use() int { return helper() }"
    files, records = recover(tmp_path, caller, donor)
    assert all(r["status"] == "recovered" for r in records)
    assert any('import "example.invalid/toy/odd_path"' in c for p, c in files.items() if p != "caller_test.go")


def test_generated_snapshot_cannot_supply_new_source_helper(tmp_path):
    donor = history("package toy\nfunc historical() int { return 1 }")
    caller = "package toy\nfunc use() int { return generatedOnly() }"
    # A generated declaration shares a known historical path, but does not
    # become a historical source definition in the recovery index.
    emitted = donor[1] + "\nfunc generatedOnly() int { return inventedDependency() }\n"
    files, records = recover(tmp_path, caller, donor, extra={donor[0]: emitted})
    assert len(files) == 2
    assert any(r["dependency"] == "inventedDependency" for r in records)
    assert not any(p.startswith("zz_rh_dependency") for p in files)


def test_no_temporal_choice_across_unknown_or_future_steps(tmp_path):
    first = history("package toy\nfunc helper() int { return 1 }", step=11)
    second = history("package toy\nfunc helper() int { return 2 }", step=12)
    caller = "package toy\nfunc use() int { return helper() }"
    files, records = recover(tmp_path, caller, first, second, step=10)
    assert files == {"caller_test.go": caller}
    assert records[0]["reason"] == "ambiguous_source_definitions"
