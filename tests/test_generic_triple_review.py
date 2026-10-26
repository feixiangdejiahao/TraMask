"""Read-only search/alignment review, with independent source-only examples."""
from anchor_retrieval.syntax import Source, child, walk
from prototypes.statement_aligned_test_analogy_v03.alignment import align_analogy
from prototypes.test_edit_analogy_allow_erasing_v02_01.analogy import analogy as raw_analogy
from generic_composition.corpus import build_corpus
from generic_composition.terms import from_source, render


EXTRA_OBSERVATION = '''def test_A():
    assert f(1) == 2
def test_B():
    assert f(1) == 2
    assert metadata() == 3
def test_C():
    assert f(5) == 10
'''


def test_assert_statement_only_anchor_reports_distinct_new_observer_as_ambiguous(tmp_path):
    source = Source('test_review.py', EXTRA_OBSERVATION, 'python')
    functions = [n for n in walk(source.root) if n.type == 'function_definition']
    bodies = [from_source(source, child(n, 'body')) for n in functions]
    result = align_analogy(*bodies)
    assert result.status == 'unsupported'
    assert result.reason == 'ambiguous_alignment'
    assert result.provenance['source'] == 'B'


def test_existing_actual_call_facts_can_disambiguate_without_expected_constants(tmp_path):
    (tmp_path / 'test_review.py').write_text(EXTRA_OBSERVATION)
    corpus = build_corpus(tmp_path, 'python')
    source = Source('test_review.py', EXTRA_OBSERVATION, 'python')
    tests = sorted(corpus['tests'].values(), key=lambda t: t['span']['start_byte'])
    bodies, keys = [], []
    for test in tests:
        function = next(n for n in walk(source.root) if n.type == 'function_definition'
                        and n.start_byte == test['definition_span']['start_byte'])
        bodies.append(from_source(source, child(function, 'body')))
        assertions = sorted((a for a in corpus['capsules'] if a['test_id'] == test['id']),
                            key=lambda a: a['assertion_span']['start_byte'])
        labels = []
        for assertion in assertions:
            observed = assertion['observed']['span']
            call = next(c for c in assertion['calls']
                        if (c['span']['start_byte'], c['span']['end_byte']) ==
                           (observed['start_byte'], observed['end_byte']))
            identity = call['callee_identity']
            labels.append(identity.get('canonical') or identity['scope_key'])
        keys.append(labels)
    assert keys[0] == keys[2] and keys[1][0] == keys[0][0] and keys[1][1] != keys[0][0]
    result = align_analogy(*bodies, anchor_keys=keys)
    assert result.status == 'hypothesis'
    assert render(result.output) == 'assert f(5) == 10\n    assert metadata() == 3'
    assert all(result.provenance['checks'].values())


def test_changed_observation_still_needs_a_fallback_beyond_exact_call_identity():
    def term(code):
        return from_source(Source('toy.py', code, 'python'))
    A = term('assert f(1) == 2\n')
    B = term('assert wrap(f(1)) == [2]\n')
    C = term('assert f(5) == 10\n')
    assert align_analogy(A, B, C, anchor_keys=(['f'], ['wrap'], ['f'])).reason == 'missing_anchor'
    result = align_analogy(A, B, C)
    assert result.status == 'hypothesis'
    assert render(result.output) == 'assert wrap(f(5)) == [10]\n'
    assert 'oracle_validity' in result.provenance['unproved']


def test_full_embedding_loses_an_erasing_edit_already_supported_by_raw_analogy():
    def term(code):
        return from_source(Source('toy.py', code, 'python'))
    A = term('setup(1)\nassert f(3) == 6\n')
    B = term('assert f(3) == 6\n')
    C = term('setup(9)\nassert f(5) == 10\n')
    raw = raw_analogy(A.term, B.term, C.term)
    aligned = align_analogy(A, B, C)
    assert raw.status == 'hypothesis'
    assert render(raw.output) == 'assert f(5) == 10\n'
    assert raw.provenance['omitted_holes']
    assert all(raw.provenance['checks'].values())
    assert aligned.status == 'unsupported' and aligned.reason == 'missing_anchor'


def test_full_embedding_loses_a_statement_kind_change_supported_by_raw_analogy():
    def term(code):
        return from_source(Source('toy.py', code, 'python'))
    A = term('x = f(1)\nassert x == 2\n')
    B = term('observe(f(1))\nassert last() == 2\n')
    C = term('x = f(3)\nassert x == 6\n')
    raw = raw_analogy(A.term, B.term, C.term)
    aligned = align_analogy(A, B, C)
    assert raw.status == 'hypothesis'
    assert render(raw.output) == 'observe(f(3))\nassert last() == 6\n'
    assert all(raw.provenance['checks'].values())
    assert aligned.status == 'unsupported' and aligned.reason == 'missing_anchor'
