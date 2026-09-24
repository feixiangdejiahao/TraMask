from copy import deepcopy

from experimental.local_literal_contexts import generate, learn
from generic_composition.corpus import build_corpus
from generic_composition.edits import learn_literal_edits


def test_local_boundary_preserves_a_different_surrounding_representation():
    before, after = '[name=alpha]', '[name=alpha;mode=fast]'
    target, expected = 'packet{name=beta}', 'packet{name=beta;mode=fast}'
    assert not any(edit.apply(target) == expected for edit in learn_literal_edits(before, after))
    rules = learn(before, after)
    assert rules
    assert all(rule.apply(before) == after for rule in rules)
    assert any(rule.apply(target) == expected for rule in rules)


def test_repeated_local_boundary_is_not_arbitrarily_selected():
    rules = learn('[name=alpha]', '[name=alpha;mode=fast]')
    target = '[name=beta] [name=gamma]'
    assert all(rule.apply(target) is None for rule in rules)


def test_unrelated_whole_replacement_and_large_differences_are_not_contexts():
    assert learn('alpha', 'beta') == []
    assert learn('x[a]y[b]', 'x[c]y[d]') == []
    assert learn('x[a]', 'x[a;b;c;d;e;f;g;h;i;j;k]') == []


def test_real_corpus_transfer_uses_same_call_port_and_keeps_source_provenance(tmp_path):
    (tmp_path / 'test_terms.py').write_text('''def interpret(value):
    return value
def separate(value):
    return value
def test_plain():
    assert interpret('[name=alpha]') == '[name=alpha]'
def test_changed():
    assert interpret('[name=alpha;mode=fast]') == '[name=alpha;mode=fast]'
def test_other_representation():
    assert interpret('packet{name=beta}') == 'packet{name=beta}'
def test_other_api():
    assert separate('packet{name=delta}') == 'packet{name=delta}'
''')
    corpus = build_corpus(tmp_path, 'python')
    before = deepcopy(corpus)
    result = generate(corpus, max_attempts=10000)
    assert result['candidates']
    transferred = [c for c in result['candidates']
                   if c['edits'][0]['after'] == repr('packet{name=beta;mode=fast}')]
    assert transferred
    assert all(c['provenance']['source_before'] and c['provenance']['source_after'] for c in transferred)
    assert all(c['edits'][0]['before'] != "'packet{name=delta}'" for c in result['candidates'])
    assert result == generate(corpus, max_attempts=10000)
    assert corpus == before


def test_attempt_budget_bounds_rejected_transfers(tmp_path):
    (tmp_path / 'test_terms.py').write_text('''def f(x): return x
def test_a(): assert f('[a=1]') == '[a=1]'
def test_b(): assert f('[a=1;x=2]') == '[a=1;x=2]'
def test_c(): assert f('{b=3}') == '{b=3}'
''')
    corpus = build_corpus(tmp_path, 'python')
    result = generate(corpus, max_attempts=1)
    assert result['attempts'] == 1
    assert result['budget_exhausted']


def test_unresolved_receiver_producer_keeps_different_factories_separate(tmp_path):
    (tmp_path / 'test_ports.py').write_text('''def test_a():
    obj = make_a()
    assert obj.consume('[name=alpha]') == 1
def test_b():
    obj = make_a()
    assert obj.consume('[name=alpha;mode=fast]') == 1
def test_c():
    obj = make_b()
    assert obj.consume('packet{name=beta}') == 1
def test_d():
    obj = make_a()
    assert obj.consume('packet{name=gamma}') == 1
''')
    corpus = build_corpus(tmp_path, 'python')
    result = generate(corpus)
    assert not any('beta;mode=fast' in c['edits'][0]['after'] for c in result['candidates'])
    selected = [c for c in result['candidates'] if 'gamma;mode=fast' in c['edits'][0]['after']]
    assert selected
    assert all(e['resolution'] == 'approximate_receiver_producer'
               for c in selected for e in c['provenance']['port_identity_evidence'])


def test_oversized_literals_are_removed_before_neighbor_similarity(tmp_path, monkeypatch):
    import experimental.local_literal_contexts as local
    long_value = '[x;' * 300
    (tmp_path / 'test_ports.py').write_text(
        'def f(x): return x\n'
        "def test_a(): assert f('[a=1]') == 1\n"
        "def test_b(): assert f('[a=1;x=2]') == 1\n"
        f'def test_long(): assert f({long_value!r}) == 1\n')
    corpus = build_corpus(tmp_path, 'python')
    original = local.difflib.SequenceMatcher
    def bounded_matcher(*args, **kwargs):
        assert len(kwargs.get('a', [])) <= 256
        assert len(kwargs.get('b', [])) <= 256
        return original(*args, **kwargs)
    monkeypatch.setattr(local.difflib, 'SequenceMatcher', bounded_matcher)
    result = generate(corpus)
    assert result['skipped']['literal_token_budget'] >= 1
