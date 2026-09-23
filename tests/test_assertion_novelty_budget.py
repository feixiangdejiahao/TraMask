"""A representation budget failure skips one item, not the bounded search."""
import pytest

from experimental.assertion_instances.generate import Budget, _statement_key, generate
from generic_composition.corpus import build_corpus
from generic_composition.terms import BudgetExceeded


def corpus(tmp_path):
    (tmp_path / 'test_budget.py').write_text('''def verify(value, expected):
    assert subject(value) == expected
def test_many():
    verify(1, 2)
    verify([1], [2])
    verify(3, 6)
    verify(5, 10)
    verify(7, 14)
''')
    return build_corpus(tmp_path, 'python')


def key(record, text, limit):
    return _statement_key(record['text'] if text is None else text, record['language'],
                          record['test']['parameters'], limit)


def test_input_novelty_budget_failure_preserves_other_candidates(tmp_path):
    def novelty(record, text, limit):
        if text is None and record['text'] == 'verify(7, 14)':
            raise BudgetExceeded('synthetic wrapper node overhead')
        return key(record, text, limit)

    result = generate(corpus(tmp_path), novelty=novelty)
    assert result['skipped']['input_novelty_node_budget'] == 1
    assert result['counts']['eligible_instances'] == 4
    assert any(c['edits'][0]['after'] == 'verify([3], [6])' for c in result['candidates'])


def test_output_novelty_budget_failure_preserves_other_candidates(tmp_path):
    def novelty(record, text, limit):
        if text == 'verify([3], [6])':
            raise BudgetExceeded('synthetic output node overhead')
        return key(record, text, limit)

    result = generate(corpus(tmp_path), novelty=novelty)
    assert result['skipped']['output_novelty_node_budget'] >= 1
    assert not any(c['edits'][0]['after'] == 'verify([3], [6])' for c in result['candidates'])
    assert any(c['edits'][0]['after'] == 'verify([5], [10])' for c in result['candidates'])


def hypothesis_stub(calls):
    def compose(data, A, B, C, **kwargs):
        calls.append((A['instance_id'], B['instance_id'], C['instance_id']))
        return {'status': 'hypothesis', 'rule': {'id': 'toy'}, 'candidate': {
            'id': 'toy', 'rule_id': 'toy', 'base_test_id': C['parent_test_id'],
            'edits': [{'span': C['span'], 'before': C['text'], 'after': 'verify(0, 0)'}],
            'provenance': {'binding_analysis': {'status': 'compatible', 'errors': [], 'unknowns': []}}}}
    return compose


def test_output_failure_still_checks_max_attempts_before_next_focus(tmp_path):
    calls = []

    def novelty(record, text, limit):
        if text is not None:
            raise BudgetExceeded('every output exceeds its representation budget')
        return key(record, text, limit)

    result = generate(corpus(tmp_path), Budget(max_attempts=1),
                      novelty=novelty, compose_instances=hypothesis_stub(calls))
    assert len(calls) == result['counts']['attempted_triples'] == 1
    assert result['skipped']['output_novelty_node_budget'] == 1
    assert result['skipped']['attempt_budget_remaining_triples'] > 0
    assert not result['candidates']


@pytest.mark.parametrize('phase', ['input', 'output'])
def test_non_budget_errors_are_not_swallowed(tmp_path, phase):
    def novelty(record, text, limit):
        if (text is None) == (phase == 'input'):
            raise ValueError('not a representation-budget failure')
        return key(record, text, limit)

    with pytest.raises(ValueError, match='not a representation-budget failure'):
        generate(corpus(tmp_path), novelty=novelty, compose_instances=hypothesis_stub([]))
