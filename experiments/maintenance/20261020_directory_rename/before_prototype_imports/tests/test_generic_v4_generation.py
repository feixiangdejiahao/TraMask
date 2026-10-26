"""Balanced literals use the same generator, input ports and oracle transport."""
from collections import Counter
import json

import pytest

from anchor_retrieval.syntax import Source
from experimental.generic_v3.generate import generate as flat_generate
from experimental.generic_v4.generate import Budget, balanced_refine, gate_evidence, generate, refine_literals
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from generic_composition.terms import from_source, render, subterms


PYTHON = '''def test_A():
    assert run("task(a)") == "result(x)"
def test_B():
    assert run("wrap(task(a))") == "box(result(x))"
def test_C():
    assert run("task(a,b)") == "result(x,y)"
'''


def corpus(tmp_path, code=PYTHON, language='python'):
    name = {'python': 'test_invented.py', 'go': 'invented_test.go', 'typescript': 'invented.test.ts'}[language]
    (tmp_path / name).write_text(code)
    return build_corpus(tmp_path, language)


def test_refinement_preserves_body_bytes_and_propagates_existing_source_roles():
    source = Source('invented.py', 'assert run("task(雪)") == "result(x)"\n', 'python')
    original = from_source(source)
    roots = {path: ('known_source_port', i) for i, (path, node) in enumerate(subterms(original.term))
             if node.kind == 'string_content'}
    record = {'tree': original, 'literal_roles': roots, 'bindings': {}}
    refined = balanced_refine(record, 1500)
    assert render(refined['tree'].term) == source.code
    groups = [(path, node) for path, node in subterms(refined['tree'].term)
              if node.kind.startswith('balanced_group_')]
    assert groups
    for path, node in groups:
        assert refined['literal_roles'][path][0] == 'known_source_port'
        span = refined['tree'].spans[path]
        assert source.data[span.start_byte:span.end_byte].decode() == render(node)
    assert record['tree'] is original


def test_input_and_expected_are_jointly_transported_by_the_unchanged_v3_core(tmp_path):
    data = corpus(tmp_path)
    expected = 'assert run("wrap(task(a,b))") == "box(result(x,y))"'
    assert expected not in [p['edits'][0]['after'] for p in flat_generate(data)['candidates']]
    generated = generate(data)
    matches = [p for p in generated['candidates'] if p['edits'][0]['after'] == expected]
    assert matches
    candidate = matches[0]
    assert candidate['base_test_id'].endswith(':test_C')
    assert candidate['oracle']['source_test_id'].endswith(':test_B')
    assert all(candidate['provenance']['checks'].values())
    assert candidate['provenance']['kernel'] == 'test_edit_analogy_v2_1_allow_erasing_rhs'
    assert generated['representation']['counts']['balanced_groups'] > 0
    assert emit(data, [candidate])['unsupported'] == []
    evidence, candidates = gate_evidence(data, generated, 'Invented recursive data syntax')
    assert candidates == generated['candidates']
    assert 'does not establish' in evidence['literal_representation_policy']
    json.dumps(generated)


@pytest.mark.parametrize('language,code', [
    ('typescript', '''test('A',()=>{expect(run("task(a)")).toBe("result(x)");});
test('B',()=>{expect(run("wrap(task(a))")).toBe("box(result(x))");});
test('C',()=>{expect(run("task(a,b)")).toBe("result(x,y)");});
'''),
    ('go', '''package invented
import "testing"
import "github.com/stretchr/testify/require"
func TestA(t *testing.T){require.Equal(t,"result(x)",run("task(a)"))}
func TestB(t *testing.T){require.Equal(t,"box(result(x))",run("wrap(task(a))"))}
func TestC(t *testing.T){require.Equal(t,"result(x,y)",run("task(a,b)"))}
'''),
])
def test_representation_swap_is_shared_by_other_host_languages(tmp_path, language, code):
    data = corpus(tmp_path, code, language)
    generated = generate(data)
    matches = [p for p in generated['candidates']
               if '"wrap(task(a,b))"' in p['edits'][0]['after'] and '"box(result(x,y))"' in p['edits'][0]['after']]
    assert matches
    assert emit(data, [matches[0]])['unsupported'] == []


def test_unsupported_leaf_falls_back_without_modifying_or_dropping_the_body():
    source = Source('invented.py', 'assert run("unfinished(") == "value"\n', 'python')
    statistics = Counter()
    refined = refine_literals(from_source(source), max_nodes=1500, statistics=statistics)
    assert render(refined.term) == source.code
    assert statistics['flat_fallback_literal_leaves'] == 1
    assert any(n.kind == 'literal_token_word' for _, n in subterms(refined.term))


def test_host_escape_structure_is_preserved_without_claiming_it_was_decoded():
    code = 'assert run("task(\\\"雪\\\")") == "value"\n'
    source = Source('invented.py', code, 'python')
    refined = refine_literals(from_source(source), max_nodes=1500)
    assert render(refined.term) == code
    for path, node in subterms(refined.term):
        span = refined.spans[path]
        assert source.data[span.start_byte:span.end_byte].decode() == render(node)


def test_search_budgets_remain_fixed_deterministic_and_corpus_unchanged(tmp_path):
    data = corpus(tmp_path)
    original = json.dumps(data, sort_keys=True)
    budget = Budget(max_candidates=1, max_attempts=2)
    first = generate(data, budget)
    assert first == generate(data, budget)
    assert first['counts']['attempted_triples'] <= 2
    assert first['counts']['attempted_orders'] <= 4
    assert first['counts']['candidates'] <= 1
    assert json.dumps(data, sort_keys=True) == original
