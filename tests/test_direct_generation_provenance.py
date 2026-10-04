import copy
import json

import pytest

from relation_search import direct_generation_provenance as provenance
from relation_search import oracle
import test_contract_gap_proposals as fixtures


def candidate(language='python'):
    corpus, frontend, prepared = fixtures.prepare(language)
    context = fixtures.shown(prepared)
    changed = context['original_test'].replace('double(3)', 'double(4)').replace(
        '== 6', '== 8').replace('!= 6', '!= 8').replace('toBe(6)', 'toBe(8)')
    result = fixtures.baseline.decide(corpus, frontend, prepared, fixtures.answer(changed))
    return corpus, result['candidates'][0], dict(original_test=context['original_test'], modified_test=changed)


@pytest.mark.parametrize('language', ['python', 'go', 'typescript'])
def test_metadata_only_full_body_and_test_receipts(language):
    corpus, program, payload = candidate(language)
    before = copy.deepcopy((corpus, program))
    augmented = provenance.attach(corpus, program, payload)
    assert (corpus, program) == before
    assert {k:v for k,v in augmented.items() if k != 'source_provenance'} == program
    record = augmented['source_provenance']
    assert record['original_body']['utf8_sha256'] == provenance.sha(program['edits'][0]['before'])
    assert record['original_test']['utf8_sha256'] == provenance.sha(payload['original_test'])
    assert record['modified_test_utf8_sha256'] == provenance.sha(payload['modified_test'])
    assert oracle.preview(corpus, augmented) == payload['modified_test']
    assert provenance.attach(corpus, augmented, payload) == augmented
    assert 'supported' not in json.dumps(record)


@pytest.mark.parametrize('change', ['body', 'id', 'source', 'escape', 'review', 'origin', 'extra'])
def test_source_identity_span_escape_or_review_changes_cannot_gain_provenance(change):
    corpus, program, payload = candidate()
    if change == 'body': program['edits'][0]['span']['start_byte'] += 1
    if change == 'id': program['id'] += 'wrong'
    if change == 'source': corpus['sources']['test_value.py']['code'] = 'x = 1\n'
    if change == 'escape': program['edits'][0]['after'] += '\ndef test_escape():\n    assert False'
    if change == 'review': payload['modified_test'] += '\n'
    if change == 'origin': corpus['sources']['test_value.py']['origin'] = 'trajectory'
    if change == 'extra': program['semantic_supported'] = True
    with pytest.raises((ValueError, KeyError)):
        provenance.attach(corpus, program, payload)


def test_atomic_origin_changes_only_declared_generator_not_id_or_body():
    corpus, program, payload = candidate()
    program['generator'] = provenance.atomic.VERSION
    program['order'] = [3]
    assert provenance.attach(corpus, program, payload)['order'] == [3]
