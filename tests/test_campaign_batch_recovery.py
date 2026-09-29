"""Run production request construction and validation around a fake provider."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from relation_search.checkpoint import read, write
from scripts.run_relation_campaign import semantic_batch
from test_relation_oracle import setup


def prepared(tmp_path):
    corpus, frontend, first = setup()
    second = deepcopy(first)
    second['id'] = 'three_items'
    second['edits'][0]['after'] = '[1, 2, 3]'
    source = tmp_path/'prepared'
    for name, value in [('corpus.json', corpus), ('frontend.json', frontend),
                        ('case.json', {'id': 'toy'}), ('prepare.json', {'status': 'prepared'}),
                        ('candidates.json', {'candidates': [first, second]})]:
        write(source/name, value)
    (source/'issue.md').write_text('Return the exact number of items.')
    args = SimpleNamespace(oracle_mode='fresh', oracle_cache=None, semantic_budget=2,
                           per_request=2, model_workers=1)
    return source, args


@pytest.mark.parametrize('parent_status', ['length', 'invalid_json', 'valid_empty', 'transport_error'])
def test_bounded_split_preserves_candidates_and_counts_actual_calls(tmp_path, monkeypatch, parent_status):
    source, args = prepared(tmp_path)
    calls = []
    monkeypatch.setattr('relation_search.semantic_selection.select',
                        lambda corpus, candidates, budget: {'selected': candidates})

    def complete(args):
        request = read(args.input)
        calls.append(request)
        child = 'batch_recovery' in request
        manifest = dict(status='complete', request_id=request['id'], external_model_calls=1,
                        finish_reason='stop')
        if child:
            candidate = request['offered']['C0']['candidate']
            count = 3 if candidate['id'] == 'three_items' else 2
            text = json.dumps({'revisions': [{'candidate': 'C0', 'basis': 'Exact source item count.',
                                'updates': [{'assertion': 'A0', 'code': f'assert result == {count}'}]}]})
        elif parent_status in {'length', 'invalid_json'}:
            text = '{"revisions": ['
            if parent_status == 'length':
                manifest['finish_reason'] = 'length'
        else:
            text = '{"revisions": []}'
            if parent_status == 'transport_error':
                manifest['status'] = 'failed'
        write(args.output/'manifest.json', manifest)
        if manifest['status'] == 'complete':
            (args.output/'completion.txt').write_text(text)

    monkeypatch.setattr('scripts.relation_search_semantics.complete', complete)
    output = tmp_path/'semantic'
    result = semantic_batch(source, output, args, [])
    split = parent_status in {'length', 'invalid_json'}
    assert result['provider_calls'] == (3 if split else 1)
    assert result['recovery_calls'] == (2 if split else 0)
    assert result['distinct_offered_candidates'] == 2
    originals = read(source/'candidates.json')['candidates']
    revised = read(output/'candidates.json')['candidates']
    assert revised[:2] == originals
    assert result['revised_count'] == (2 if split else 0)
    for request in calls[1:]:
        assert request['batch_recovery']['depth'] == 1
        assert len(request['offered']) == 1
        assert request['offered']['C0']['candidate'] in originals
    before = len(calls)
    assert semantic_batch(source, output, args, []) == result
    assert len(calls) == before, 'A completed recovery must not make another provider call'

