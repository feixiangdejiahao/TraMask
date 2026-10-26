"""Source examples can refute a relation without executing a subject."""
import copy
import pytest
from generic_composition.corpus import build_corpus
from prototypes.test_action_and_oracle_transfer import oracle
from prototypes.test_action_and_oracle_transfer.proposals import generate


def prepare(tmp_path, code):
    (tmp_path / 'test_text.py').write_text(code)
    return generate(build_corpus(tmp_path, 'python'))


SOURCE = '''def render(text):
    return text
def test_plain():
    assert render('a;') == 'a;'
def test_marked():
    assert render('a!;') == 'a!;'
def test_other():
    assert render('b;') == 'b;'
'''


def validate(candidate, expression):
    return oracle.validate_completions({'completions': [{
        'candidate_id': candidate['id'], 'observe': 0,
        'expected': expression, 'guard': None}]}, [candidate])


def test_source_witness_refutes_copy_and_target_specific_constant(tmp_path):
    generated = prepare(tmp_path, SOURCE)
    candidates = [c for c in generated['candidates'] if "render('b!;')" in c['preview_body']
                  and c.get('witnesses') and not c.get('projection')]
    assert candidates, generated['source_witnesses']
    candidate = candidates[0]
    witness = candidate['witnesses'][0]
    assert witness['pre'] == ['a;']
    assert witness['arg'] == ['a!;']
    assert witness['after'] == 'a!;'
    for bad in ('pre[0]', "'b!;'"):
        result = validate(candidate, bad)
        assert not result['accepted']
        assert result['rejected'][0]['code'] == 'witness_refuted'
    good = validate(candidate, 'arg[0]')
    assert good['accepted'][0]['literal'] == "'b!;'"
    assert good['accepted'][0]['witnesses_checked'] == 1


def test_different_other_arguments_are_not_paired_as_witnesses(tmp_path):
    code = SOURCE.replace('render(text)', 'render(text, mode)')
    code = code.replace("render('a;')", "render('a;', 0)")
    code = code.replace("render('a!;')", "render('a!;', 1)")
    code = code.replace("render('b;')", "render('b;', 0)")
    generated = prepare(tmp_path, code)
    candidates = [c for c in generated['candidates'] if "render('b!;', 0)" in c['preview_body']]
    assert candidates
    assert all(not c.get('witnesses') for c in candidates)


def test_witness_extraction_is_deterministic_and_not_an_execution(tmp_path):
    first = prepare(tmp_path, SOURCE)
    second = prepare(tmp_path, SOURCE)
    assert first == second
    assert first['source_witnesses']['attached'] > 0


@pytest.mark.parametrize('before,after', [
    ("    mode = 0\n", "    mode = 1\n"),
    ("    render = identity\n", "    render = alternate\n"),
])
def test_different_setup_or_local_callee_does_not_refute_target(tmp_path, before, after):
    code = SOURCE.replace('def test_plain():\n', 'def test_plain():\n' + before)
    code = code.replace('def test_marked():\n', 'def test_marked():\n' + after)
    code = code.replace('def test_other():\n', 'def test_other():\n' + before)
    generated = prepare(tmp_path, code)
    assert generated['candidates']
    assert generated['source_witnesses']['attached'] == 0


def test_different_fixture_decorators_are_part_of_the_source_condition(tmp_path):
    code = SOURCE.replace('def test_plain()', "@pytest.mark.usefixtures('a')\ndef test_plain()")
    code = code.replace('def test_marked()', "@pytest.mark.usefixtures('b')\ndef test_marked()")
    code = code.replace('def test_other()', "@pytest.mark.usefixtures('a')\ndef test_other()")
    generated = prepare(tmp_path, 'import pytest\n' + code)
    assert generated['candidates']
    assert generated['source_witnesses']['attached'] == 0


def test_literal_inside_noninjective_expected_constructor_is_not_a_witness(tmp_path):
    code = 'def folded(text): return text.lower()\n' + SOURCE
    for literal in ("'a;'", "'a!;'", "'b;'"):
        code = code.replace('== ' + literal, '== folded(' + literal + ')')
    generated = prepare(tmp_path, code)
    assert generated['candidates']
    assert generated['source_witnesses']['attached'] == 0


def test_witness_span_metadata_does_not_alias_the_input_corpus(tmp_path):
    from prototypes.test_action_and_oracle_transfer.source_witnesses import attach
    path = tmp_path / 'test_text.py'
    path.write_text(SOURCE)
    corpus = build_corpus(tmp_path, 'python')
    candidates = generate(corpus)['candidates']
    saved = copy.deepcopy(corpus)
    result = attach(corpus, candidates)
    witness = next(c['witnesses'][0] for c in result['candidates'] if c.get('witnesses'))
    witness['source_before']['start_byte'] = -100
    witness['source_after']['path'] = 'changed'
    assert corpus == saved


def test_parameterized_parent_does_not_borrow_a_different_row_condition(tmp_path):
    code = 'import pytest\n' + SOURCE
    for name in ('plain', 'marked', 'other'):
        code = code.replace(f'def test_{name}():',
                            "@pytest.mark.parametrize('mode', [0, 1])\n" + f'def test_{name}(mode):')
    generated = prepare(tmp_path, code)
    assert generated['candidates']
    assert generated['source_witnesses']['attached'] == 0


def test_foreign_input_escape_is_decoded_before_context_learning(tmp_path):
    from prototypes.test_action_and_oracle_transfer.proposals import _source_string_values
    source = r'''function render(x: string) { return x; }
test('a', () => { expect(render('a\a;')).toBe('aa;'); });
'''
    (tmp_path / 'toy.test.ts').write_text(source)
    corpus = build_corpus(tmp_path, 'typescript')
    saved = copy.deepcopy(corpus)
    normalized, counts = _source_string_values(corpus)
    donor = next(d for d in normalized['donors'] if d['text'] == r"'a\a;'")
    assert donor['literal_value'] == 'aa;'
    assert counts['corrected'] > 0
    assert corpus == saved
