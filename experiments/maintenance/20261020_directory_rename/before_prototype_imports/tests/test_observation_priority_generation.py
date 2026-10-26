"""The optional ordering changes search order, not composition or admission."""
import importlib
import json

from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from experimental.generic_v5.views import compose_views
from experimental.observation_priority.generate import Budget, gate_evidence

generator = importlib.import_module('experimental.observation_priority.generate')


def make_corpus(tmp_path):
    (tmp_path / 'test_order.py').write_text('''from sample_api import Factory, left, right, normalize, prepare
def test_A():
    box = Factory()
    assert left(box) == 1
def test_irrelevant():
    box = Factory()
    unused = prepare()
    assert left(box) == 1
def test_different():
    box = Factory()
    assert right(box) == 2
def test_target():
    box = Factory()
    assert left(box) == 2
def test_edit():
    box = Factory()
    assert normalize(left(box)) == 1
def test_unknown():
    box = Factory()
    assert mystery(box) == 2
''')
    corpus = build_corpus(tmp_path, 'python')
    for test in corpus['tests'].values():
        test['retrieval_rank'] = 1 if test['name'] == 'test_A' else None
    return corpus


def record_attempts(monkeypatch):
    attempts = []

    def tracked(A, B, C, **options):
        attempts.append(tuple(r['test']['name'] for r in (A, B, C)))
        return compose_views(A, B, C, **options)

    monkeypatch.setattr(generator, 'compose_views', tracked)
    return attempts


def test_first_focus_prefers_same_observer_and_connected_edit(tmp_path, monkeypatch):
    corpus = make_corpus(tmp_path)
    attempts = record_attempts(monkeypatch)
    result = generator.generate(corpus, Budget(max_attempts=1))
    assert attempts == [('test_A', 'test_edit', 'test_target')]
    assert result['counts']['attempted_triples'] == 1
    assert result['budget']['max_candidates'] == 128
    assert any('normalize(left(box)) == 2' in p['edits'][0]['after'] for p in result['candidates'])
    assert emit(corpus, result['candidates'])['unsupported'] == []
    json.dumps(result)


def test_default_budget_preserves_unknown_and_unrelated_queues(tmp_path, monkeypatch):
    corpus = make_corpus(tmp_path)
    attempts = record_attempts(monkeypatch)
    result = generator.generate(corpus)
    assert result['budget']['max_attempts'] == 2000
    assert result['budget']['max_candidates'] == 128
    assert len(attempts) == len(set(attempts)) == result['counts']['attempted_triples'] <= 2000
    assert result['counts']['candidates'] <= 128
    focus_attempts = [abc for abc in attempts if abc[0] == 'test_A']
    assert any(abc[2] == 'test_unknown' for abc in focus_attempts)
    assert any(abc[1] == 'test_irrelevant' for abc in focus_attempts)
    # One attempt per eligible focus/producer queue remains the driver policy.
    assert attempts[1][0] != 'test_A'


def test_repeat_determinism_output_budget_and_identical_gate_policy(tmp_path):
    corpus = make_corpus(tmp_path)
    budget = Budget(max_attempts=12, max_candidates=1)
    result = generator.generate(corpus, budget)
    assert result == generator.generate(corpus, budget)
    assert result['counts']['attempted_triples'] <= 12
    assert result['counts']['candidates'] == 1
    evidence, candidates = gate_evidence(corpus, result, 'Existing toy contract')
    assert 'Each triple was tried as raw syntax' in evidence['composition_policy']
    assert 'priority' not in evidence['composition_policy']
    assert candidates == result['candidates']
    json.dumps(evidence)


def test_concrete_parameter_rows_remain_supported(tmp_path):
    (tmp_path / 'test_rows.py').write_text('''import pytest
@pytest.mark.parametrize("value,want", [(1,1),([1],[1]),(2,7)])
def test_table(value,want):
    assert f(value) == want
''')
    result = generator.generate(build_corpus(tmp_path, 'python'))
    assert result['counts']['attempted_triples'] > 0
    assert any('value = [2]' in p['edits'][0]['after'] and 'want = [7]' in p['edits'][0]['after']
               for p in result['candidates'])
