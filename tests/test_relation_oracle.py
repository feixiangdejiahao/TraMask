import json

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.oracle import imported_api_contexts, issue_contract, prepare_requests, validate


def test_benchmark_runner_wrapper_is_not_part_of_the_contract():
    issue = ('Implement the requested behavior.\n\n'
             'You can execute bash commands and edit files to implement the necessary changes.\n'
             '\n## Recommended Workflow\nRun commands.\n'
             '\n## Command Execution Rules\nSubmit output.')
    assert issue_contract(issue) == 'Implement the requested behavior.'
    ordinary = 'The document should explain: You can execute bash commands.'
    assert issue_contract(ordinary) == ordinary


def test_import_context_follows_source_alias_and_barrel_to_function_body():
    source = dict(language='typescript', sources={
        'lib/index.ts': {'code': "export * from './wrap.ts';"},
        'lib/wrap.ts': {'code': 'export function wrap(x: object): object;\nexport function wrap(x: object) { return {...x, stamp: true}; }'},
        'elsewhere/wrap.ts': {'code': 'export function wrap(x: object) { return {other: x}; }'}})
    candidate = {'imports': [{'name': 'generated_alias', 'module': '../lib/index.ts', 'imported_name': 'wrap',
                               'source_path': 'tests/donor.test.ts'}]}
    rows = imported_api_contexts(source, 'tests/target.test.ts', candidate)
    assert len(rows) == 1
    assert rows[0]['path'] == 'lib/wrap.ts' and rows[0]['imported_alias'] == 'generated_alias'
    assert 'stamp: true' in rows[0]['code'] and 'other' not in rows[0]['code']


def setup():
    source = Source('test_numbers.py', '''def test_count():
    values = [1]
    result = len(values)
    assert result == 1
''', 'python')
    front = extract_frontend([source])
    corpus = to_emitter_corpus(front)
    test = next(iter(corpus['tests'].values()))
    at = source.code.index('[1]')
    candidate = dict(id='input_edit', base_test_id=test['id'], source_test_ids=[], imports=[],
                     edits=[dict(span=dict(path=source.path, start_byte=at, end_byte=at+3),
                                 before='[1]', after='[1, 2]', role='input')])
    return corpus, front, candidate


def test_only_offered_assertion_is_changed_and_source_inputs_survive():
    corpus, front, candidate = setup()
    request = prepare_requests(corpus, front, [candidate], 'Count the items.')[0]
    response = {'revisions': [{'candidate': 'C0', 'updates': [{'assertion': 'A0', 'code': 'assert result == 2'}],
                               'basis': 'Two source input items.'}]}
    result = validate(request, response, corpus)
    revised = result['revisions'][0]
    assert revised['edits'][0] == candidate['edits'][0]
    assert revised['edits'][1]['role'] == 'semantic_expected'
    assert len(candidate['edits']) == 1


def test_model_cannot_replace_test_body_or_force_unrelated_failure():
    corpus, front, candidate = setup()
    request = prepare_requests(corpus, front, [candidate], 'Count the items.')[0]
    for code in ['values.clear()\nassert result == 0', 'assert False', 'assert result == result',
                 'assert exec("raise RuntimeError()") == result']:
        result = validate(request, {'revisions': [{'candidate': 'C0', 'basis': 'claim',
                          'updates': [{'assertion': 'A0', 'code': code}]}]}, corpus)
        assert result['revisions'] == []


def test_missing_model_judgment_does_not_create_or_delete_candidates():
    corpus, front, candidate = setup()
    request = prepare_requests(corpus, front, [candidate], 'Count the items.')[0]
    result = validate(request, '{"revisions": []}', corpus)
    assert result['revisions'] == []
    assert request['offered']['C0']['candidate'] == candidate
