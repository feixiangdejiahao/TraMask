"""Representation ablation on an invented input language, without execution."""
import json

from experimental.assertion_windows.balanced import generate, gate_evidence
from experimental.assertion_windows.generate import generate as flat_generate
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit


def test_balanced_view_combines_nested_input_and_expected_structure(tmp_path):
    code = '''def test_a():
    assert run("task(a)") == "result(x)"
def test_b():
    assert run("wrap(task(a))") == "box(result(x))"
def test_c():
    assert run("task(a,b)") == "result(x,y)"
'''
    (tmp_path / 'test_strings.py').write_text(code)
    corpus = build_corpus(tmp_path, 'python')
    expected = 'assert run("wrap(task(a,b))") == "box(result(x,y))"'
    flat = flat_generate(corpus)
    balanced = generate(corpus)
    assert expected not in [c['edits'][0]['after'] for c in flat['candidates']]
    matches = [c for c in balanced['candidates'] if c['edits'][0]['after'] == expected]
    assert matches
    assert balanced['budget'] == flat['budget']
    assert balanced['representation']['counts']['balanced_groups'] > 0
    assert not emit(corpus, matches)['unsupported']
    evidence, candidates = gate_evidence(corpus, balanced, 'An invented grammar')
    assert candidates == balanced['candidates']
    assert 'does not prove' in evidence['literal_representation_policy']
    json.dumps(evidence)
    json.dumps(balanced)
