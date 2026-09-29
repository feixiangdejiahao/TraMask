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
