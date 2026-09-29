import copy
import json

from relation_search.semantic_cache import apply_cache, build_cache, file_digest, program_key


def inputs():
    corpus = {'tests': {'t': {'span': {'path': 'test.py'}}},
              'sources': {'test.py': {'code': 'helper = 1\ninput = 2\nassert input == 2\n'}}}
    candidate = dict(id='same', base_test_id='t', imports=[], edits=[
        dict(span=dict(path='test.py', start_byte=19, end_byte=20), before='2', after='3', role='input')])
    revision = {**copy.deepcopy(candidate), 'id': 'revised',
                'semantic_revision': {'parent': 'same'},
                'edits': [*candidate['edits'], dict(span=dict(path='test.py', start_byte=37, end_byte=38),
                                                  before='2', after='3', role='semantic_expected')]}
    cache = {'entries': [dict(program_key=program_key(corpus, candidate, 'contract'), candidate=revision,
                              request='source_request.json', completion='recorded_completion')]}
    return corpus, candidate, cache


def test_replay_keeps_original_inputs_and_never_selects_by_cache():
    corpus, candidate, cache = inputs()
    result = apply_cache(corpus, [candidate], cache, 'contract')
    assert [r['id'] for r in result['candidates']] == ['same', 'revised']
    assert result['candidates'][1]['edits'][0] == candidate['edits'][0]
    assert len(candidate['edits']) == 1
    assert result['counts']['provider_calls'] == 0


def test_changed_helper_issue_or_input_cannot_reuse_even_same_id():
    corpus, candidate, cache = inputs()
    changed = copy.deepcopy(corpus)
    changed['sources']['test.py']['code'] = changed['sources']['test.py']['code'].replace('helper = 1', 'helper = 9')
    assert apply_cache(changed, [candidate], cache, 'contract')['counts']['replayed'] == 0
    assert apply_cache(corpus, [candidate], cache, 'different')['counts']['replayed'] == 0
    changed_candidate = copy.deepcopy(candidate)
    changed_candidate['edits'][0]['after'] = '4'
    assert apply_cache(corpus, [changed_candidate], cache, 'contract')['counts']['replayed'] == 0


def test_raw_provider_and_contract_provenance_are_required(tmp_path):
    from test_relation_oracle import setup
    from relation_search.oracle import prepare_requests
    from relation_search.checkpoint import write
    corpus, front, candidate = setup()
    source, completion = tmp_path/'source', tmp_path/'completion'
    write(source/'corpus.json', corpus)
    (source/'issue.md').write_text('Count the items.')
    write(source/'prepare.json', {'files_sha256': {
        name: file_digest(source/name) for name in ['corpus.json', 'issue.md']}})
    request = prepare_requests(corpus, front, [candidate], 'Count the items.')[0]
    request['source_prepared'] = str(source)
    request_path = tmp_path/'request.json'
    write(request_path, request)
    wire = {'messages': [{'role': 'system', 'content': request['system']},
                         {'role': 'user', 'content': request['prompt']}],
            'thinking': {'type': request.get('thinking', 'disabled')}}
    write(completion/'request.json', wire)
    answer = json.dumps({'revisions': [{'candidate': 'C0', 'basis': 'Two input items.',
                         'updates': [{'assertion': 'A0', 'code': 'assert result == 2'}]}]})
    write(completion/'response.body', {'choices': [{'message': {'content': answer}}]})
    (completion/'completion.txt').write_text(answer)
    write(completion/'manifest.json', {'status': 'complete', 'request_id': request['id'],
          'request_sha256': file_digest(completion/'request.json'),
          'response_sha256': file_digest(completion/'response.body')})
    cache = build_cache([request_path], [completion])
    assert len(cache['entries']) == 1
    assert cache['records'][0]['cache_status'] == 'revalidated'
    (source/'issue.md').write_text('Changed contract.')
    changed = build_cache([request_path], [completion])
    assert changed['entries'] == []
    assert changed['records'][0]['cache_status'] == 'changed_source_issue'
    (source/'issue.md').write_text('Count the items.')
    (completion/'completion.txt').write_text('{"revisions": []}')
    changed = build_cache([request_path], [completion])
    assert changed['entries'] == []
    assert changed['records'][0]['cache_status'] == 'changed_provider_response'
