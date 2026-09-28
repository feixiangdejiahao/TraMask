from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend
from relational_gap.seed_ranking import rank_seeds


def frontend():
    return extract_frontend([
        Source('pkg/core.py', 'def core(x):\n    return x + 1\n', 'python'),
        Source('pkg/wrap.py', 'from .core import core\ndef wrap(x):\n    return core(x)\n', 'python'),
        Source('tests/test_rank.py', '''from pkg.core import core
from pkg.wrap import wrap
def test_keyword_only():
    text = "core wrap"
    assert text
def test_side_effect():
    core(0)
    assert True
def test_indirect():
    answer = wrap(2)
    assert answer == 3
def test_direct():
    assert core(1) == 2
def test_unknown():
    assert unavailable(1)
''', 'python')])


def test_observation_path_outranks_mentions_and_unobserved_call():
    facts = frontend()
    prior = {t['id']: n for n, t in enumerate(facts['tests'], 1)}
    ranked = rank_seeds(facts, {'pkg/core.py': [2]}, prior)
    names = [r['test_id'].rsplit(':', 1)[-1] for r in ranked['records']]
    assert names == ['test_direct', 'test_indirect', 'test_side_effect', 'test_keyword_only', 'test_unknown']
    assert ranked['records'][1]['distance'] == 1
    assert set(ranked['ranks']) == set(prior)


def test_unresolved_same_name_guess_does_not_create_a_path():
    facts = frontend()
    for call in facts['calls'] + facts['production_calls']:
        for target in call.get('targets', ()):
            target['resolved'] = False
    prior = {t['id']: n for n, t in enumerate(facts['tests'], 1)}
    ranked = rank_seeds(facts, {'pkg/core.py': [2]}, prior)
    assert ranked['ranks'] == prior
    assert all(r['relation'] == 'unresolved_or_no_path' for r in ranked['records'])


def test_no_changed_function_preserves_prior_order():
    facts = frontend()
    prior = {t['id']: n for n, t in enumerate(reversed(facts['tests']), 1)}
    assert rank_seeds(facts, {'pkg/core.py': [100]}, prior)['ranks'] == prior


def test_production_cycles_terminate_with_shortest_path():
    facts = frontend()
    core = next(f['id'] for f in facts['functions'] if f['name'] == 'core')
    wrap = next(f['id'] for f in facts['functions'] if f['name'] == 'wrap')
    facts['production_calls'].append({'function_id': core, 'targets': [{'function_id': wrap, 'resolved': True}]})
    prior = {t['id']: n for n, t in enumerate(facts['tests'], 1)}
    ranked = rank_seeds(facts, {'pkg/core.py': [2]}, prior)
    assert next(r for r in ranked['records'] if r['test_id'].endswith(':test_indirect'))['distance'] == 1
