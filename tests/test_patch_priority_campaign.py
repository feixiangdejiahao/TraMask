"""Source priority survives the real semantic queue and submitted-patch boundary."""
import hashlib
import json
from copy import deepcopy

import pytest

from anchor_retrieval.syntax import Source
from relation_search.checkpoint import read, write
from relation_search.semantic_frontier import advance
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts.run_relation_campaign import semantic_batch, submitted_patch
from test_campaign_batch_recovery import prepared


PATCH = ('--- a/library.py\n+++ b/library.py\n@@ -2 +2 @@\n'
         '-    return value * 2\n+    return value * 3\n')


def fixture():
    code = ('from library import calculate\n\ndef test_example():\n'
            '    unused = 10\n    value = 1\n'
            '    result = calculate(value)\n    assert result == 3\n')
    frontend = extract_frontend([
        Source('library.py', 'def calculate(value):\n    return value * 3\n', 'python'),
        Source('test_example.py', code, 'python'),
    ], patch=PATCH)
    corpus = to_emitter_corpus(frontend)
    base, test = next(iter(corpus['tests'].items()))
    candidates = []
    for name, before, after, rank in [('unused', '10', '11', 0), ('input', '1', '2', 1)]:
        needle = ('unused = ' if name == 'unused' else 'value = ') + before
        offset = code.encode().index(needle.encode(), test['span']['start_byte']) + len(needle.encode()) - len(before)
        candidates.append(dict(id=name, base_test_id=base, operator='literal_change',
            source_retrieval_rank=rank, imports=[], edits=[dict(before=before, after=after,
                role='input', span=dict(path='test_example.py', start_byte=offset, end_byte=offset + len(before)))]))
    return corpus, frontend, candidates


@pytest.mark.parametrize('mode', ['patch-strict', 'patch-may'])
def test_source_priority_keeps_unserved_fallback_and_exact_patch_on_resume(mode):
    corpus, frontend, candidates = fixture()
    first = advance(corpus, candidates, budget=1, frontend=frontend,
                    selection_policy=mode, patch=PATCH)
    assert [c['id'] for c in first['selection']['selected']] == ['input']
    assert first['frontier']['pending_ids'] == ['unused']
    second = advance(corpus, [], first['frontier'], budget=1, frontend=frontend,
                     selection_policy=mode, patch=PATCH)
    assert [c['id'] for c in second['selection']['selected']] == ['unused']
    assert second['frontier']['pending_ids'] == []
    with pytest.raises(ValueError, match='submitted patch changed'):
        advance(corpus, [], second['frontier'], frontend=frontend,
                selection_policy=mode, patch=PATCH + '\n')
    with pytest.raises(ValueError, match='selection policy changed'):
        advance(corpus, [], second['frontier'], selection_policy='shape')


def test_patch_policy_requires_both_patch_and_source_frontend():
    corpus, frontend, candidates = fixture()
    for kwargs in [dict(frontend=frontend), dict(patch=PATCH)]:
        with pytest.raises(ValueError, match='requires source frontend'):
            advance(corpus, candidates, selection_policy='patch-may', **kwargs)


def case_patch(source, patch_path):
    patch_path.write_text(PATCH)
    case = read(source/'case.json')
    case.update(candidate_patch=str(patch_path), repository_provenance=dict(
        patch_sha256=hashlib.sha256(PATCH.encode()).hexdigest()))
    write(source/'case.json', case)


@pytest.mark.parametrize('mode', ['patch-strict', 'patch-may'])
def test_existing_model_stage_records_patch_and_still_uses_source_only_requests(tmp_path, monkeypatch, mode):
    source, args = prepared(tmp_path)
    case_patch(source, tmp_path/'submitted.patch')
    args.semantic_policy = mode
    args.semantic_budget = 1
    requests = []

    def complete(call):
        request = read(call.input)
        requests.append(request)
        write(call.output/'manifest.json', dict(status='complete', request_id=request['id'],
            external_model_calls=1, finish_reason='stop'))
        (call.output/'completion.txt').write_text(json.dumps(dict(revisions=[dict(
            candidate='C0', updates=[], basis='Source-only fixture control.')])))

    monkeypatch.setattr('scripts.relation_search_semantics.complete', complete)
    output = tmp_path/'semantic'
    result = semantic_batch(source, output, args, [])
    assert result['provider_calls'] == 1
    assert len(requests) == 1
    assert requests[0]['kind'] == 'local_existing_assertion_oracle'
    assert read(output/'semantic_frontier.json')['patch_sha256'] == hashlib.sha256(PATCH.encode()).hexdigest()
    stage = read(output/'stage.json')
    assert stage['selection_policy'] == mode
    assert stage['submitted_patch_sha256'] == hashlib.sha256(PATCH.encode()).hexdigest()
    assert all('semantic_revision' not in v['candidate'] for v in requests[0]['offered'].values())


def test_patch_mismatch_is_rejected_before_any_provider_attempt(tmp_path, monkeypatch):
    source, args = prepared(tmp_path)
    patch_path = tmp_path/'submitted.patch'
    case_patch(source, patch_path)
    args.semantic_policy = 'patch-may'
    patch_path.write_text(PATCH.replace('* 3', '* 4'))
    attempts = []
    monkeypatch.setattr('scripts.relation_search_semantics.complete', lambda call: attempts.append(call))
    with pytest.raises(ValueError, match='source-case provenance'):
        semantic_batch(source, tmp_path/'semantic', args, [])
    assert attempts == []
    with pytest.raises(ValueError, match='source-case provenance'):
        submitted_patch(source)


def test_submitted_patch_preserves_exact_newline_bytes_for_queue_identity(tmp_path):
    source, _ = prepared(tmp_path)
    patch_path = tmp_path/'submitted.patch'
    case_patch(source, patch_path)
    data = PATCH.replace('\n', '\r\n').encode()
    patch_path.write_bytes(data)
    case = read(source/'case.json')
    case['repository_provenance']['patch_sha256'] = hashlib.sha256(data).hexdigest()
    write(source/'case.json', case)
    patch, sha = submitted_patch(source)
    assert patch.encode() == data
    assert hashlib.sha256(patch.encode()).hexdigest() == sha


@pytest.mark.parametrize('mode', ['patch-strict', 'patch-may'])
@pytest.mark.parametrize('budget', [0, 1, 2])
def test_unrequestable_prefix_cannot_block_budget_or_expand_batched_model_budget(tmp_path, monkeypatch, mode, budget):
    source, args = prepared(tmp_path)
    case_patch(source, tmp_path/'submitted.patch')
    candidates = read(source/'candidates.json')['candidates']
    third = deepcopy(candidates[0])
    third.update(id='four_items')
    third['edits'][0]['after'] = '[1, 2, 3, 4]'
    corpus, frontend = read(source/'corpus.json'), read(source/'frontend.json')
    original = frontend['observations'][0]
    extent = original.get('assertion_span') or original['span']
    before = corpus['sources'][extent['path']]['code'].encode()[extent['start_byte']:extent['end_byte']].decode()
    blocked = dict(id='no_observation', base_test_id=candidates[0]['base_test_id'],
        operator='aaa_remove_observation', imports=[], source_test_ids=[],
        edits=[dict(span=extent, before=before, after='pass', role='operation')])
    write(source/'candidates.json', dict(candidates=[blocked, *candidates, third]))
    args.semantic_policy, args.semantic_budget, args.per_request = mode, budget, 4
    offered = []

    def complete(call):
        request = read(call.input)
        offered.extend(row['candidate']['id'] for row in request['offered'].values())
        write(call.output/'manifest.json', dict(status='complete', request_id=request['id'],
            external_model_calls=1, finish_reason='stop'))
        (call.output/'completion.txt').write_text('{"revisions": []}')

    monkeypatch.setattr('scripts.relation_search_semantics.complete', complete)
    output = tmp_path/'semantic'
    result = semantic_batch(source, output, args, [])
    selection = read(output/'semantic_selection.json')
    assert selection['ranking'][0]['id'] == 'no_observation', 'The blocked program leads the source ranking'
    assert len(offered) == budget
    assert 'no_observation' not in offered
    assert selection['selected_count'] == budget
    assert result['provider_calls'] == int(budget > 0)
    frontier = read(output/'semantic_frontier.json')
    assert 'no_observation' in frontier['pending_ids']
    assert len(frontier['candidates']) == 4
    assert set(frontier['selected_ids']) == set(offered)
    assert semantic_batch(source, output, args, []) == result
    assert len(offered) == budget


def test_main_code_freeze_includes_source_priority_transitive_parser_dependencies():
    from scripts.run_relation_campaign import code_identity
    paths = code_identity()
    for path in ['experimental/patch_observation_priority.py', 'generic_composition/corpus.py',
                 'experimental/modified_observation_impact.py', 'experimental/local_helper_evidence.py',
                 'experimental/go_assertion_helper.py', 'experimental/source_failure_evidence.py']:
        assert path in paths
