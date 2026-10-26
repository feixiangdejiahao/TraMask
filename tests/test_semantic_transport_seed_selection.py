"""Seed budgets count materializable parents without reranking source relevance."""
import copy

import pytest

from prototypes.test_action_and_oracle_transfer.seed_selection import select
from prototypes.test_action_and_oracle_transfer.proposals import Budget, generate
from generic_composition.corpus import build_corpus


def miniature():
    corpus = {'language': 'python', 'tests': {}, 'sources': {}, 'capsules': [], 'donors': []}
    for tid, rank, metadata in [
            ('history', 1, {'complete_file': False}),
            ('foreign', 2, {'language': 'go'}),
            ('broken', 3, {'parse_error': True}),
            ('first', None, {}), ('second', None, {}), ('unranked', None, {})]:
        path = tid + '.py'
        corpus['sources'][path] = dict({'language': 'python', 'complete_file': True,
                                       'parse_error': False, 'code': ''}, **metadata)
        corpus['tests'][tid] = {'id': tid, 'name': tid, 'span': {'path': path, 'line': 1},
                                'retrieval_rank': rank}
        corpus['capsules'].append({'id': 'cap-' + tid, 'test_id': tid, 'retrieval_rank': rank})
        corpus['donors'].append({'id': 'donor-' + tid, 'test_id': tid, 'retrieval_rank': rank})
    anchors = [{'id': 'a-' + tid, 'test_id': tid, 'path': tid + '.py', 'name': tid, 'test_line': 1}
               for tid in ['history', 'foreign', 'broken', 'first', 'second']]
    anchors.append(dict(anchors[3], id='another-first'))
    retrieval = {'anchors': anchors, 'rankings': {'full': [a['id'] for a in anchors[:4]]
                                               + ['another-first', 'a-second']}}
    return corpus, retrieval


def test_complete_parent_budget_restores_full_order_and_retains_original_inputs():
    corpus, retrieval = miniature()
    original, original_retrieval = copy.deepcopy(corpus), copy.deepcopy(retrieval)
    view, report = select(corpus, retrieval, top_k=2)
    assert [row['test_id'] for row in report['selected']] == ['first', 'second']
    assert [row['effective_rank'] for row in report['selected']] == [1, 2]
    assert [row['retrieval_parent_rank'] for row in report['selected']] == [4, 5]
    assert [row['retrieval_anchor_rank'] for row in report['selected']] == [4, 6]
    assert report['selected'][1]['retrieval_anchor_id'] == 'a-second'
    assert all(row['original_corpus_rank'] is None for row in report['selected'])
    assert report['excluded_source_counts'] == {
        'incomplete_source': 1, 'different_language': 1, 'source_parse_error': 1}
    assert set(view['tests']) == {'first', 'second', 'unranked'}
    for key in ['capsules', 'donors']:
        assert [row['retrieval_rank'] for row in view[key]] == [1, 2, 3]
        assert all(row['original_retrieval_rank'] is None for row in view[key])
    assert corpus == original and retrieval == original_retrieval
    assert view['sources']['first.py'] is corpus['sources']['first.py']


def test_parent_location_matching_uses_definition_line_and_unambiguous_identity():
    corpus, retrieval = miniature()
    first = corpus['tests'].pop('first')
    first['id'] = 'rebuilt-first'
    first['span']['line'] = 9  # A decorator can begin before the function.
    first['definition_span'] = {'path': 'first.py', 'line': 1}
    corpus['tests'][first['id']] = first
    for key in ['capsules', 'donors']:
        for row in corpus[key]:
            if row['test_id'] == 'first':
                row['test_id'] = first['id']
    view, report = select(corpus, retrieval, top_k=2)
    assert report['selected'][0]['test_id'] == 'rebuilt-first'
    assert report['selected'][0]['retrieval_test_id'] == 'first'
    assert view['tests']['rebuilt-first']['retrieval_rank'] == 1


def test_ineligible_only_corpus_cannot_become_fallback_seed():
    corpus, retrieval = miniature()
    corpus['tests'] = {tid: row for tid, row in corpus['tests'].items()
                       if tid in {'history', 'foreign', 'broken'}}
    view, report = select(corpus, retrieval)
    assert view['tests'] == {} and view['donors'] == [] and view['capsules'] == []
    assert report['selected'] == []
    assert report['skipped_retrieval_parents']['parent_absent_from_corpus'] == 2


def test_unknown_anchor_id_fails_closed():
    corpus, retrieval = miniature()
    retrieval['rankings']['full'].append('missing')
    with pytest.raises(ValueError, match='full_ranking_anchor_missing'):
        select(corpus, retrieval)


def test_generation_accepts_full_retrieval_and_uses_complete_parent_seed(tmp_path):
    (tmp_path / 'test_toy.py').write_text('''def make(value): return value
def wrap(value): return '<' + value + '>'
def test_plain():
    assert make('a') == 'a'
def test_wrapped():
    assert wrap(make('b')) == '<b>'
''')
    corpus = build_corpus(tmp_path, 'python')
    plain = next(row for row in corpus['tests'].values() if row['name'] == 'test_plain')
    retrieval = {'anchors': [
        {'id': 'old', 'test_id': 'missing-history', 'path': 'history.py', 'name': 'test_old', 'test_line': 1},
        {'id': 'current', 'test_id': plain['id'], 'path': 'test_toy.py', 'name': plain['name'],
         'test_line': plain['definition_span']['line']}],
        'rankings': {'full': ['old', 'current']}}
    original = copy.deepcopy(corpus)
    result = generate(corpus, Budget(top_k=1), retrieval=retrieval)
    assert result['candidates']
    assert result['seed_selection']['selected'][0]['test_id'] == plain['id']
    assert result['seed_selection']['selected'][0]['retrieval_parent_rank'] == 2
    assert corpus == original


@pytest.mark.parametrize('contexts_per_observation', [1, 6])
def test_later_higher_ranked_assertion_precedes_earlier_source_assertion(tmp_path, contexts_per_observation):
    (tmp_path / 'test_toy.py').write_text('''def make(value): return value
def wrap(value): return '<' + value + '>'
def test_plain():
    value = make('a')
    assert value == 'a'
    assert len(value) == 1
def test_wrapped():
    assert wrap(make('b')) == '<b>'
''')
    corpus = build_corpus(tmp_path, 'python')
    parent = next(row for row in corpus['tests'].values() if row['name'] == 'test_plain')
    caps = sorted((cap for cap in corpus['capsules'] if cap['test_id'] == parent['id']),
                  key=lambda cap: cap['assertion_span']['start_byte'])
    anchors = [dict(id='anchor-' + str(i), test_id=parent['id'], name=parent['name'], path='test_toy.py',
                    test_line=parent['definition_span']['line'], line=cap['assertion_span']['line'],
                    assertion=cap['assertion'])
               for i, cap in enumerate(reversed(caps))]
    retrieval = {'anchors': anchors, 'rankings': {'full': [a['id'] for a in anchors]}}
    result = generate(corpus, Budget(top_k=1, contexts_per_observation=contexts_per_observation),
                      retrieval=retrieval)
    candidates = [row for row in result['candidates'] if row['base_test_id'] == parent['id']]
    assert candidates[0]['capsule_id'] == caps[-1]['id']
    assert candidates[0]['retrieval_anchor'] == {'id': 'anchor-0', 'rank': 1}
    assert candidates[0]['retrieval_parent']['retrieval_parent_rank'] == 1


def test_two_assertions_on_one_line_keep_their_own_anchor_rank(tmp_path):
    (tmp_path / 'test_toy.py').write_text("def test_pair():\n    assert one() == 1; assert two() == 2\n")
    corpus = build_corpus(tmp_path, 'python')
    caps = sorted(corpus['capsules'], key=lambda cap: cap['assertion_span']['start_byte'])
    parent = corpus['tests'][caps[0]['test_id']]
    anchors = [dict(id='anchor-' + str(i), test_id=parent['id'], name=parent['name'], path='test_toy.py',
                    test_line=parent['definition_span']['line'], line=cap['assertion_span']['line'],
                    assertion=cap['assertion']) for i, cap in enumerate(reversed(caps))]
    # Reproduce the frozen corpus builder's line-only ID join.
    for cap in caps:
        cap['retrieval_anchor_ids'] = [a['id'] for a in anchors]
    retrieval = {'anchors': anchors, 'rankings': {'full': [a['id'] for a in anchors]}}
    view, _ = select(corpus, retrieval)
    by_id = {cap['id']: cap for cap in view['capsules']}
    assert by_id[caps[0]['id']]['retrieval_anchor_rank'] == 2
    assert by_id[caps[1]['id']]['retrieval_anchor_rank'] == 1
