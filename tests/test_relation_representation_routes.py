import ast

from anchor_retrieval.syntax import Source, units
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.representations import generate
from generic_composition.emitter import emit


def test_path_and_command_are_changed_together_without_touching_observation():
    source = '''from pathlib import Path
def test_roundtrip(tmp_path):
    archive = tmp_path / "session.log"
    command = "open %s" % archive
    assert str(archive) in command
'''
    corpus = to_emitter_corpus(extract_frontend([Source('test_example.py', source, 'python')]))
    rows = generate(corpus)
    assert len(rows) == 2
    assert all(len(row['edits']) == 2 for row in rows)
    result = emit(corpus, rows)
    assert len(result['obligations']) == 2
    code = result['files']['test_example.py']
    ast.parse(code)
    assert 'assert str(archive) in command' in code
    assert 'session space.log' in code
    assert '__import__("shlex").quote(str(archive))' in code


def test_rebound_name_does_not_reuse_old_resource_definition():
    source = '''def test_bound(tmp_path):
    target = tmp_path / "file.dat"
    target = 12
    command = "open %s" % target
    assert command
'''
    corpus = to_emitter_corpus(extract_frontend([Source('test_other.py', source, 'python')]))
    assert generate(corpus) == []


def test_all_consumers_of_changed_binding_receive_encoding(tmp_path):
    source = '''import shlex
def interpret(command):
    return shlex.split(command)[1]
def test_commands(tmp_path):
    path = tmp_path / "sample.dat"
    first = "read %s" % path
    second = "write %s" % path
    assert interpret(first) == str(path)
    assert interpret(second) == str(path)
'''
    corpus = to_emitter_corpus(extract_frontend([Source('test_commands.py', source, 'python')]))
    rows = generate(corpus)
    assert len(rows) == 2
    assert all(len(row['edits']) == 3 for row in rows)
    emitted = emit(corpus, rows)
    namespace = {}
    exec(emitted['files']['test_commands.py'], namespace)
    for item in emitted['obligations']:
        namespace[item['test_name']](tmp_path)


def test_same_name_after_rebinding_is_separate_resource():
    source = '''def test_commands(tmp_path):
    path = tmp_path / "one.dat"
    first = "read %s" % path
    path = tmp_path / "two.dat"
    second = "read %s" % path
    assert first != second
'''
    corpus = to_emitter_corpus(extract_frontend([Source('test_commands.py', source, 'python')]))
    rows = generate(corpus)
    assert len(rows) == 4
    assert all(len(row['edits']) == 2 for row in rows)
    assert all(len(row['relation']['consumers']) == 1 for row in rows)
