"""Automatic alignment composition uses the same corpus/gate/emitter contract."""
import json

from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from generic_composition.gate import presentation, selection_candidates
from experimental.generic_v3.generate import Budget, _novelty, gate_evidence, generate
from anchor_retrieval.syntax import Source, child, walk
from generic_composition.terms import from_source


SETUP = '''def test_A():
    x = f(1)
    assert x == 2
def test_B():
    x = f(1)
    checkpoint(x)
    assert x == 2
def test_C():
    arg = 3
    x = f(arg)
    assert x == 6
'''


def corpus(tmp_path, code):
    (tmp_path / 'test_example.py').write_text(code)
    return build_corpus(tmp_path, 'python')


def test_automatically_selected_sources_keep_extra_setup_and_observation(tmp_path):
    data = corpus(tmp_path, SETUP)
    generated = generate(data)
    expected = 'arg = 3\n    x = f(arg)\n    checkpoint(x)\n    assert x == 6'
    matches = [p for p in generated['candidates'] if p['edits'][0]['after'] == expected]
    assert matches
    candidate = matches[0]
    assert sorted(candidate['alignment']['alignment'].values()) == [[0, 2], [1, 2]]
    assert candidate['provenance']['kernel'] == 'test_edit_analogy_v2_1_allow_erasing_rhs'
    assert candidate['binding_check']['status'] == 'unknown'
    assert all(candidate['provenance']['checks'].values())
    emitted = emit(data, [candidate])
    assert emitted['unsupported'] == [] and len(emitted['obligations']) == 1
    json.dumps(generated)


def test_both_gap_orders_share_fixed_triple_and_output_budgets(tmp_path):
    data = corpus(tmp_path, SETUP.replace('    arg = 3\n    x = f(arg)', '    x = f(3)\n    snapshot(x)'))
    generated = generate(data)
    texts = [p['edits'][0]['after'] for p in generated['candidates']]
    assert 'x = f(3)\n    snapshot(x)\n    checkpoint(x)\n    assert x == 6' in texts
    assert 'x = f(3)\n    checkpoint(x)\n    snapshot(x)\n    assert x == 6' in texts
    small = generate(data, Budget(max_candidates=1, max_attempts=2))
    assert small['counts']['attempted_triples'] <= 2
    assert small['counts']['attempted_orders'] <= 4
    assert small['counts']['candidates'] <= 1
    assert small == generate(data, Budget(max_candidates=1, max_attempts=2))


def test_an_existing_full_combination_is_not_reported_with_new_local_ordinals(tmp_path):
    data = corpus(tmp_path, SETUP + '''def test_D():
    arg = 3
    result = f(arg)
    checkpoint(result)
    assert result == 6
''')
    generated = generate(data)
    assert not any('arg = 3\n    x = f(arg)\n    checkpoint(x)\n    assert x == 6' == p['edits'][0]['after']
                   for p in generated['candidates'])
    assert generated['skipped']['existing_combination'] > 0


def test_joint_oracle_transport_retains_parameter_row_adapter(tmp_path):
    data = corpus(tmp_path, '''import pytest
@pytest.mark.parametrize("value,want", [(1,1),([1],[1]),(2,7)])
def test_table(value,want):
    assert f(value) == want
''')
    generated = generate(data)
    assert any('value = [2]' in p['edits'][0]['after'] and 'want = [7]' in p['edits'][0]['after']
               for p in generated['candidates'])
    evidence, candidates = gate_evidence(data, generated, 'Ordinary collection API')
    shown = presentation(evidence, selection_candidates(candidates, 'ordinal_v1'))
    assert all(p['rule_id'] in evidence['analogy_sources'] for p in shown['candidates'])
    assert 'absence of duplicated inline effects' in evidence['composition_policy']
    json.dumps(shown)


def test_extra_setup_does_not_shift_the_corresponding_local_binding_identity(tmp_path):
    data = corpus(tmp_path, SETUP.replace('    x = f(arg)\n    assert x == 6',
                                         '    result = f(arg)\n    assert result == 6'))
    generated = generate(data)
    expected = 'arg = 3\n    result = f(arg)\n    checkpoint(result)\n    assert result == 6'
    matches = [p for p in generated['candidates'] if p['edits'][0]['after'] == expected]
    assert matches
    assert 'aligned_declaration_paths' in matches[0]['provenance']['binding_correspondence']


def test_inline_python_bodies_do_not_treat_definition_text_as_indentation(tmp_path):
    code = '''def test_A(): x = f(1); assert x == 2
def test_B(): x = f(1); checkpoint(x); assert x == 2
def test_C(): arg = 3; x = f(arg); assert x == 6
'''
    data = corpus(tmp_path, code)
    generated = generate(data)
    expected = 'arg = 3; x = f(arg); checkpoint(x); assert x == 6'
    matches = [p for p in generated['candidates'] if p['edits'][0]['after'] == expected]
    assert matches
    assert emit(data, [matches[0]])['unsupported'] == []
    # A fourth source with different local spelling is already this combination.
    data = corpus(tmp_path, code + 'def test_D(): arg = 3; result = f(arg); checkpoint(result); assert result == 6\n')
    regenerated = generate(data)
    assert not any(p['edits'][0]['after'] == expected for p in regenerated['candidates'])
    assert regenerated['skipped']['existing_combination'] > 0


def test_inline_class_body_novelty_only_uses_leading_whitespace():
    def body(name):
        code = f'class Example:\n    def test_one(self): {name} = f(1); assert {name} == 2\n'
        source = Source('example.py', code, 'python')
        fn = next(n for n in walk(source.root) if n.type == 'function_definition')
        return from_source(source, child(fn, 'body')).term
    assert _novelty(body('x'), 'python', ['self'], '    ') == _novelty(body('result'), 'python', ['self'], '    ')
