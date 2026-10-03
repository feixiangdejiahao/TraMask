import json

from relation_search import review_repair
from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def fixture():
    source = Source('test_counts.py', 'def test_count():\n    xs = [1]\n    result = len(xs)\n    assert result == 1\n', 'python')
    frontend = extract_frontend([source])
    corpus = to_emitter_corpus(frontend)
    base = next(iter(corpus['tests']))
    at = source.code.index('[1]')
    candidate = dict(id='edit', base_test_id=base, source_test_ids=[], imports=[], edits=[
        dict(span=dict(path=source.path, start_byte=at, end_byte=at+3),
             before='[1]', after='[1, 2]', role='input')])
    request = dict(id='review', prompt=json.dumps(dict(original_test=source.code,
        source_analysis='The input list now has two items.', native_evidence='SECRET',
        evaluator_truth='SECRET', issue='Count all list items.')))
    decision = dict(judgments={'P': 'supported', 'Q0': 'unsupported'},
        basis='The required count changes to two.', native_result='SECRET')
    return corpus, frontend, candidate, request, decision


def test_feedback_does_not_forward_native_or_evaluator_metadata():
    corpus, frontend, candidate, old, decision = fixture()
    request = review_repair.prepare(corpus, frontend, candidate, 'Count all list items.', old, decision)['request']
    assert 'SECRET' not in request['prompt']
    assert 'required count changes' in request['prompt']


def test_repair_preserves_inputs_and_requires_fresh_review_and_execution():
    corpus, frontend, candidate, old, decision = fixture()
    request = review_repair.prepare(corpus, frontend, candidate, 'Count all list items.', old, decision)['request']
    payload = {'revisions': [{'candidate': 'C0', 'basis': 'Two items.',
        'updates': [{'assertion': 'A0', 'code': 'assert result == 2'}]}]}
    new = review_repair.validate(request, payload, corpus)['revisions'][0]
    assert new['edits'][0] == candidate['edits'][0]
    assert new['repair_provenance']['full_review_required']
    assert new['repair_provenance']['native_execution_required']
    payload['revisions'][0]['updates'][0]['code'] = 'xs.clear()\nassert result == 0'
    assert review_repair.validate(request, payload, corpus)['revisions'] == []
    assert review_repair.validate(request, payload, corpus, finish_reason='length')['revisions'] == []
