from copy import deepcopy
import json

import pytest

from relation_search.checkpoint import read, write
from relation_search.semantic_frontier import advance
from scripts.run_relation_campaign import semantic_batch
from test_campaign_batch_recovery import prepared


def test_unserved_candidate_survives_program_exhaustion_and_is_dispatched_once(tmp_path, monkeypatch):
    first, args = prepared(tmp_path)
    args.semantic_budget = 1
    calls = []

    def complete(args):
        request = read(args.input)
        candidate = request['offered']['C0']['candidate']
        calls.append(candidate['id'])
        count = 3 if candidate['id'] == 'three_items' else 2
        write(args.output/'manifest.json', dict(status='complete', request_id=request['id'],
              external_model_calls=1, finish_reason='stop'))
        (args.output/'completion.txt').write_text(json.dumps({'revisions': [dict(candidate='C0',
            basis='Exact source item count.', updates=[dict(assertion='A0', code=f'assert result == {count}')])]}))

    monkeypatch.setattr('scripts.relation_search_semantics.complete', complete)
    out_a, out_b = tmp_path/'semantic_a', tmp_path/'semantic_b'
    result_a = semantic_batch(first, out_a, args, [])
    assert result_a['pending_semantic_count'] == 1
    assert result_a['provider_calls'] == 1
    second = tmp_path/'next_prepared'
    for name in ['corpus.json', 'frontend.json', 'case.json', 'prepare.json']:
        write(second/name, read(first/name))
    (second/'issue.md').write_text((first/'issue.md').read_text())
    write(second/'candidates.json', {'candidates': []})
    result_b = semantic_batch(second, out_b, args, result_a['previous_selected'], out_a)
    assert result_b['source_count'] == 0
    assert result_b['revised_count'] == 1
    assert result_b['pending_semantic_count'] == 0
    assert result_b['provider_calls'] == 1
    assert set(calls) == {'input_edit', 'three_items'}
    revision = read(out_b/'candidates.json')['candidates'][0]
    assert revision['semantic_revision']['parent'] == calls[-1]
    source = next(c for c in read(first/'candidates.json')['candidates'] if c['id'] == calls[-1])
    assert revision['edits'][:-1] == source['edits']
    assert semantic_batch(second, out_b, args, result_a['previous_selected'], out_a) == result_b
    assert len(calls) == 2


def test_queue_keeps_zero_budget_pending_and_detects_changed_hypothesis(tmp_path):
    source, _ = prepared(tmp_path)
    corpus = read(source/'corpus.json')
    candidates = read(source/'candidates.json')['candidates']
    step = advance(corpus, candidates, budget=0)
    assert step['selection']['selected'] == []
    assert len(step['frontier']['pending_ids']) == 2
    served = []
    for _ in range(3):
        step = advance(corpus, [], step['frontier'], budget=1)
        served.extend(c['id'] for c in step['selection']['selected'])
    assert set(served) == {c['id'] for c in candidates}
    assert len(served) == 2
    changed = deepcopy(candidates[0])
    changed['edits'][0]['after'] = '[99]'
    with pytest.raises(ValueError, match='changed source edits'):
        advance(corpus, [changed], step['frontier'])

