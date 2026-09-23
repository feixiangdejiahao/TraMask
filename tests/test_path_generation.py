import ast

import pytest

from combination_testing.paths import generate_paths, lift_path


def function(source):
    return ast.parse(source).body[0]


def test_transport_changes_construction_and_command_but_retains_bound_oracle():
    fn = function('''
def test_anything(client, tmp_path):
    location = tmp_path / "notes.bin"
    client.run_line_magic("arbitrary", "open %s --flag" % location)
    assert client.status() == {"file": str(location)}
''')
    lifted = ast.unparse(lift_path(fn, 'location'))
    assert "cc space notes.bin" in lifted
    assert 'open "%s" --flag' in lifted
    assert "{'file': str(location)}" in lifted
    assert 'cc space' not in ast.unparse(fn)


def test_reject_literal_oracle_and_reassignment():
    for body in ['assert client.path == "notes.bin"', 'location = tmp_path / "other.bin"']:
        fn = function(f'''
def test_anything(client, tmp_path):
    location = tmp_path / "notes.bin"
    client.run_line_magic("whatever", "%s" % location)
    {body}
''')
        with pytest.raises(ValueError):
            lift_path(fn, 'location')


def test_reject_partial_token_and_non_boundary():
    for call in ['client.run_line_magic("x", "prefix%s" % p)', 'client.store("%s" % p)']:
        fn = function(f'''
def test_anything(client, tmp_path):
    p = tmp_path / "a"
    {call}
    assert p.exists()
''')
        with pytest.raises(ValueError):
            lift_path(fn, 'p')


def test_fstring_transport_and_support_selection(tmp_path):
    path = tmp_path / 'test_other.py'
    path.write_text('''
import pytest
from somewhere import read, unrelated_implementation_constant
@pytest.fixture
def client():
    return obtain_client()
def test_renamed(client, tmp_path):
    dest = tmp_path / "data"
    client.run_line_magic("thing", f"start {dest}")
    assert read(dest) == "ok"
''')
    selection = {'selected_tests': [{'path': path.name, 'name': 'test_renamed',
                                    'test_id': 'any', 'rank': 1}]}
    result = generate_paths(tmp_path, selection)
    assert len(result['obligations']) == 2
    source = next(iter(result['files'].values()))
    assert 'unrelated_implementation_constant' not in source
    assert 'def client()' in source
    compile(source, '<generated>', 'exec')
