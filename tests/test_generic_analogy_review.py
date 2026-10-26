"""Independent construction audit, using invented programs and no pilot data."""
import ast

from anchor_retrieval.syntax import Source
from prototypes.test_edit_analogy_v02.analogy import analogy
from prototypes.test_edit_analogy_v02.generate import generate
from generic_composition.corpus import build_corpus
from generic_composition.terms import from_source, render


def term(code):
    return from_source(Source('invented.py', code, 'python')).term


def test_reconstruction_is_not_a_proof_of_transported_oracle():
    # A, B and C are all true for f(x)=x. The generated D is false. This is
    # deliberate evidence that syntactic reconstruction requires a semantic gate,
    # not an expected-failure regression or a request for arithmetic API rules.
    A = 'assert f(3) == 3\n'
    B = 'assert f(3) + 1 == 4\n'
    C = 'assert f(8) == 8\n'
    result = analogy(term(A), term(B), term(C))
    assert result.status == 'hypothesis'
    assert all(result.provenance['checks'].values())
    assert render(result.output) == 'assert f(8) + 1 == 4\n'
    assert 3 == 3 and 3 + 1 == 4 and 8 == 8
    assert 8 + 1 != 4
    assert 'oracle_validity' in result.provenance['unproved']


def test_whole_body_can_transport_an_added_operation_and_its_observation(tmp_path):
    # B applies an existing operation twice; C supplies a distinct input and
    # expected result. No container wrapping or API-specific rule is involved.
    code = '''def normalize(text):
    return text.upper()
def test_once():
    value = normalize("aa")
    assert value == "AA"
def test_twice():
    value = normalize("aa")
    again = normalize(value)
    assert again == "AA"
def test_other_input():
    value = normalize("bb")
    assert value == "BB"
'''
    (tmp_path / 'test_operations.py').write_text(code)
    corpus = build_corpus(tmp_path, 'python')
    generated = generate(corpus)
    expected = 'value = normalize("bb")\n    again = normalize(value)\n    assert again == "BB"'
    matches = [p for p in generated['candidates'] if p['edits'][0]['after'] == expected]
    assert matches
    candidate = matches[0]
    assert all(candidate['provenance']['checks'].values())
    assert candidate['oracle']['mode'] == 'transport_from_source'
    assert candidate['oracle']['source_test_id'].endswith(':test_twice')
    assert candidate['base_test_id'].endswith(':test_other_input')
    assert candidate['provenance']['sources']['B']['text'].count('normalize(') == 2
    assert '"bb"' not in candidate['provenance']['sources']['B']['text']
    # The fixed operation and expected syntax come from B, while BB comes from C.
    assert '"BB"' in candidate['provenance']['sources']['C']['text']
    ast.parse('def generated():\n    ' + expected)


def test_alpha_renaming_does_not_count_as_a_second_behavioral_change(tmp_path):
    code = '''def test_initial():
    x = f(1)
    assert x == 2
def test_renamed():
    y = f(1)
    assert y == 2
def test_other_input():
    x = f(3)
    assert x == 6
'''
    (tmp_path / 'test_renaming.py').write_text(code)
    generated = generate(build_corpus(tmp_path, 'python'))
    assert not generated['candidates']


def test_indirect_parameter_fixture_is_not_replaced_with_raw_literal(tmp_path):
    # Pytest indirect parameters are fixture inputs, not the values seen by the
    # source test. Materialization cannot claim identity without fixture analysis.
    code = '''import pytest
@pytest.fixture
def value(request):
    return ("prepared", request.param)
@pytest.mark.parametrize("value,want", [(1,1),([1],[1]),(2,7)], indirect=["value"])
def test_table(value,want):
    assert f(value) == want
'''
    (tmp_path / 'test_indirect.py').write_text(code)
    generated = generate(build_corpus(tmp_path, 'python'))
    assert not generated['candidates']


def test_writes_through_objects_are_not_lexical_declarations():
    from prototypes.test_edit_analogy_v02.generate import _binding_labels
    source = Source('invented.py', 'box.value = 1\narray[index] = 2\nassert read(box) == 1\n', 'python')
    tree = from_source(source)
    labels = _binding_labels(source, source.root, tree, [])
    assert all(label[0] != 'single_scope_local' for label in labels.values())


def test_two_independent_statement_insertions_need_more_than_tree_antiunification():
    # Existing implementation transports a structural B edit over an A/C
    # substitution. It does not perform general statement-sequence alignment.
    A = 'value = f(1)\nassert value == 1\n'
    B = 'value = f(1)\nvalue = refresh(value)\nassert value == 1\n'
    C = 'value = f(1)\nvalue = snapshot(value)\nassert value == 1\n'
    result = analogy(term(A), term(B), term(C))
    assert result.status == 'unsupported'
    assert result.reason == 'target_change_not_transportable'


def test_extra_target_preparation_statement_collapses_the_current_block_match():
    A = 'x = f(1)\nassert x == 2\n'
    B = 'x = f(1)\ncheckpoint(x)\nassert x == 2\n'
    C = 'arg = 3\nx = f(arg)\nassert x == 6\n'
    result = analogy(term(A), term(B), term(C))
    assert result.status == 'unsupported'
    assert result.reason == 'target_change_not_transportable'
    # The statement-list arity change abstracts the complete module as one hole,
    # hiding the useful correspondences f(1)->f(arg) and oracle 2->6.
    from generic_composition.terms import Hole
    assert isinstance(result.before_pattern, Hole)
