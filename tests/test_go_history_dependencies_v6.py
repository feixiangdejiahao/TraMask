"""Offline source import binding, independent of discovery subjects."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import test_go_history_dependencies as prior_cases

from anchor_retrieval.syntax import Source
from relational_gap.history import namespace_go_validation
from scripts.go_history_dependencies_v6 import _package_sources, recover_go_dependencies


pytestmark = pytest.mark.skipif(shutil.which('go') is None, reason='Go compiler required')


def history(code, path='helpers.go', step=1):
    digest = hashlib.sha256(code.encode()).hexdigest()
    destination = str(Path(path).with_name(Path(path).stem + '_rh_' + digest[:12] + '_test.go'))
    renamed, names = namespace_go_validation(Source(destination, code, 'go'), digest[:12])
    return destination, renamed.code, {'kind': 'historical_validation', 'sha256': digest,
                                      'relocated_globals': names, 'original_target_path': path, 'step_id': step}


def recover(root, caller, donors=(), inventory=None):
    corpus = {'sources': {p: {'code': c} for p, c, _ in donors}}
    selection = {'files': {p: m for p, _, m in donors}}
    selection['files']['caller_test.go'] = {'kind': 'historical_validation', 'step_id': 10}
    return recover_go_dependencies({'caller_test.go': caller}, corpus, selection, root,
                                   import_package_sources=inventory)


def run_go(root, files):
    for path, code in files.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(code)
    result = subprocess.run(['go', 'test', './...'], cwd=root,
                            env=dict(os.environ, GO111MODULE='on', GOPROXY='off', GOSUMDB='off', GOWORK='off'),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def dependency(root):
    (root / 'go.mod').write_text('module example.invalid/toy\n\ngo 1.18\nrequire dependency.invalid/unusual v0.0.0\nreplace dependency.invalid/unusual => ./external\n')
    directory = root / 'external'
    directory.mkdir()
    (directory / 'go.mod').write_text('module dependency.invalid/unusual\n\ngo 1.18\n')
    code = 'package actualname\nfunc Value() int { return 7 }\n'
    path = directory / 'value.go'
    path.write_text(code)
    return {'dependency.invalid/unusual': [{'path': str(path), 'code': code,
                                            'sha256': hashlib.sha256(code.encode()).hexdigest()}]}


def test_external_default_import_uses_actual_dependency_package_clause(tmp_path):
    inventory = dependency(tmp_path)
    donor = history('package toy\nimport "dependency.invalid/unusual"\nfunc helper() int { return actualname.Value() }')
    caller = 'package toy\nimport "testing"\nfunc TestRecovered(t *testing.T) { if helper()!=7 { t.Fatal("value") } }'
    files, records = recover(tmp_path, caller, [donor], inventory)
    assert all(r['status'] == 'recovered' for r in records)
    imported, = records[0]['declarations'][0]['imports']
    assert imported['name'] == 'actualname'
    assert imported['binding_source'] == 'dependency_package_declaration'
    assert imported['source_evidence'][0]['sha256'] == inventory['dependency.invalid/unusual'][0]['sha256']
    run_go(tmp_path, files)


def test_unavailable_package_source_does_not_guess_last_import_segment(tmp_path):
    donor = history('package toy\nimport "dependency.invalid/pretend"\nfunc helper() int { return pretend.Value() }')
    caller = 'package toy\nfunc use() int { return helper() }'
    files, records = recover(tmp_path, caller, [donor])
    assert files == {'caller_test.go': caller}
    assert records[0]['status'] == 'unresolved'


def test_package_inventory_rejects_conflicting_names_and_wrong_hashes():
    one = {'path': '/cache/a.go', 'code': 'package first\n'}
    two = {'path': '/cache/b.go', 'code': 'package second\n'}
    assert not _package_sources({'dependency.invalid/x': [one, two]})
    assert not _package_sources({'dependency.invalid/x': [{**one, 'sha256': 'wrong'}]})
    assert not _package_sources({'dependency.invalid/x': [{**one, 'go_list_name': 'different'}]})
    assert _package_sources({'dependency.invalid/x': [one, {'path': '/cache/x_test.go', 'code': 'package first_test\n'}]})


def test_unique_sibling_explicit_import_is_recovered_at_selector_only(tmp_path):
    (tmp_path / 'go.mod').write_text('module example.invalid/toy\n\ngo 1.18\n')
    (tmp_path / 'sibling.go').write_text('package toy\nimport text "strings"\nfunc existing() string { return text.ToUpper("a") }')
    caller = 'package toy\nimport "testing"\nfunc TestRecovered(t *testing.T) { if text.ToUpper("b")!="B" { t.Fatal("alias") } }'
    files, records = recover(tmp_path, caller)
    assert 'import text "strings"' in files['caller_test.go']
    assert records[0]['kind'] == 'go_history_import'
    assert records[0]['source_import']['source_path'] == 'sibling.go'
    run_go(tmp_path, files)


def test_alias_recovery_leaves_shadowed_local_unchanged(tmp_path):
    (tmp_path / 'go.mod').write_text('module example.invalid/toy\n\ngo 1.18\n')
    (tmp_path / 'sibling.go').write_text('package toy\nimport text "strings"\nfunc existing() string { return text.ToUpper("a") }')
    caller = '''package toy
import "testing"
func TestRecovered(t *testing.T) {
 { text := struct{Value int}{3}; if text.Value!=3 {t.Fatal("local")} }
 if text.ToUpper("b")!="B" {t.Fatal("import")}
}
'''
    files, records = recover(tmp_path, caller)
    assert len(records) == 1
    assert 'text.Value' in files['caller_test.go']
    run_go(tmp_path, files)


def test_conflicting_same_package_import_aliases_stay_unresolved(tmp_path):
    (tmp_path / 'one.go').write_text('package toy\nimport text "strings"\n')
    (tmp_path / 'two.go').write_text('package toy\nimport text "bytes"\n')
    caller = 'package toy\nfunc use() { text.Unknown() }'
    files, records = recover(tmp_path, caller)
    assert files == {'caller_test.go': caller}
    assert records[0]['reason'] == 'ambiguous_source_import_bindings'


def test_different_package_alias_and_bare_name_are_not_import_bindings(tmp_path):
    (tmp_path / 'sibling.go').write_text('package other\nimport text "strings"\n')
    caller = 'package toy\nfunc use() { text.Unknown() }'
    assert recover(tmp_path, caller)[0] == {'caller_test.go': caller}
    (tmp_path / 'sibling.go').write_text('package toy\nimport text "strings"\n')
    caller = 'package toy\nfunc use() { _ = text }'
    assert recover(tmp_path, caller)[0] == {'caller_test.go': caller}


def test_missing_import_inside_transitive_helper_is_source_recovered(tmp_path):
    (tmp_path / 'go.mod').write_text('module example.invalid/toy\n\ngo 1.18\n')
    (tmp_path / 'sibling.go').write_text('package toy\nimport text "strings"\nfunc existing() string { return text.ToUpper("a") }')
    donor = history('package toy\nfunc helper() string { return leaf() }\nfunc leaf() string { return text.ToUpper("b") }')
    caller = 'package toy\nimport "testing"\nfunc TestRecovered(t *testing.T) { if helper()!="B" { t.Fatal("closure") } }'
    files, records = recover(tmp_path, caller, [donor])
    assert all(r['status'] == 'recovered' for r in records)
    assert any('import text "strings"' in code for path, code in files.items() if path != 'caller_test.go')
    run_go(tmp_path, files)


def test_existing_same_module_alias_conflict_does_not_rebind_source_import(tmp_path):
    (tmp_path / 'sibling.go').write_text('package toy\nimport text "strings"\n')
    caller = 'package toy\nimport other "strings"\nfunc use() { _=other.ToUpper("a"); _=text.ToUpper("b") }'
    files, records = recover(tmp_path, caller)
    assert files == {'caller_test.go': caller}
    assert records[0]['reason'] == 'source_import_module_already_bound'


def test_generated_snapshot_cannot_supply_new_import_alias_evidence(tmp_path):
    donor = history('package toy\nfunc helper() int { return 3 }')
    caller = 'package toy\nfunc use() { text.ToUpper("a") }'
    snapshot = donor[1].replace('package toy', 'package toy\nimport text "strings"')
    corpus = {'sources': {donor[0]: {'code': donor[1]}}}
    selection = {'files': {donor[0]: donor[2]}}
    original_files = {'caller_test.go': caller, donor[0]: snapshot}
    files, records = recover_go_dependencies(original_files, corpus, selection, tmp_path)
    assert files == original_files
    assert any(row['path'] == 'caller_test.go' and row['status'] == 'unresolved' for row in records)


def test_source_actual_import_wins_over_emitted_import_replacement(tmp_path):
    donor = history('package toy\nimport text "strings"\nfunc helper() string { return text.ToUpper("b") }')
    caller = 'package toy\nfunc use() { text.ToUpper("a") }'
    snapshot = donor[1].replace('text "strings"', 'text "bytes"')
    corpus = {'sources': {donor[0]: {'code': donor[1]}}}
    selection = {'files': {donor[0]: donor[2]}}
    files, records = recover_go_dependencies({'caller_test.go': caller, donor[0]: snapshot}, corpus, selection, tmp_path)
    assert 'import text "strings"' in files['caller_test.go']
    assert next(row for row in records if row['kind'] == 'go_history_import')['source_import']['module'] == 'strings'


@pytest.mark.parametrize('name', sorted(name for name in vars(prior_cases) if name.startswith('test_')))
def test_previous_source_closure_contracts_apply_to_v6(tmp_path, monkeypatch, name):
    monkeypatch.setattr(prior_cases, 'recover_go_dependencies', recover_go_dependencies)
    getattr(prior_cases, name)(tmp_path)
