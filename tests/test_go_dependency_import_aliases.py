import hashlib

from scripts.go_dependency_import_aliases import explicit_dependency_imports


def inventory(name='actual'):
    code = 'package ' + name + '\nfunc Value() int { return 1 }\n'
    return {'example.org/unrelated': [{'path': '/cache/unrelated/value.go', 'code': code,
                                      'sha256': hashlib.sha256(code.encode()).hexdigest()}]}


def test_package_clause_names_implicit_import_without_guessing():
    source = 'package app\nimport "example.org/unrelated"\nvar Value = actual.Value()\n'
    files, records = explicit_dependency_imports({'a.go': source}, inventory())
    assert files['a.go'] == source.replace('import "', 'import actual "')
    assert records[0]['name'] == 'actual'
    assert records[0]['source_sha256'] == hashlib.sha256(source.encode()).hexdigest()


def test_explicit_aliases_blank_imports_and_unknown_packages_are_preserved():
    source = 'package app\nimport (alias "example.org/unrelated"; _ "example.org/unrelated"; "unknown.org/pkg")\n'
    assert explicit_dependency_imports({'a.go': source}, inventory()) == ({'a.go': source}, [])


def test_corrupt_evidence_cannot_establish_an_import_binding():
    data = inventory()
    data['example.org/unrelated'][0]['sha256'] = '0' * 64
    source = 'package app\nimport "example.org/unrelated"\n'
    assert explicit_dependency_imports({'a.go': source}, data) == ({'a.go': source}, [])
