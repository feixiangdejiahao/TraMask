"""Attach source receipts to an unchanged, already reviewed body rewrite."""
from __future__ import annotations

import copy
import hashlib

from relation_search import contract_gap_proposals as core
from relation_search import atomic_contract_gap_proposals as atomic
from relation_search import oracle

VERSION = 'direct-generation-source-provenance.v1'


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def attach(corpus, candidate, review_payload=None):
    original_candidate = {k: v for k, v in candidate.items() if k != 'source_provenance'}
    source, test, _ = core._source_test(corpus, candidate['base_test_id'])
    full, body = test['span'], test['body_span']
    original = source.data[full['start_byte']:full['end_byte']].decode()
    before = source.data[body['start_byte']:body['end_byte']].decode()
    edits = candidate.get('edits', [])
    if (len(edits) != 1 or edits[0].get('span') != body or edits[0].get('before') != before
            or edits[0].get('role') != 'program'):
        raise ValueError('Original complete body edit differs')
    modified = oracle.preview(corpus, candidate)
    seed = dict(base_test_id=candidate['base_test_id'], source_sha256=hashlib.sha256(source.data).hexdigest(),
                span=full, body_span=body)
    reconstructed = core._rewrite(corpus, seed, modified)
    if candidate.get('generator') not in {core.VERSION, atomic.VERSION}:
        raise ValueError('Unsupported direct generator')
    reconstructed.update(generator=candidate['generator'], order=candidate['order'])
    if reconstructed != original_candidate:
        raise ValueError('Candidate differs from exact original body reconstruction')
    if review_payload is not None and (
            review_payload.get('original_test') != original or review_payload.get('modified_test') != modified):
        raise ValueError('Reviewed complete test differs from source rewrite')
    provenance = dict(version=VERSION, seed=candidate['base_test_id'],
        source_file=dict(path=source.path, source_sha256=hashlib.sha256(source.data).hexdigest(), origin='repository'),
        original_test=dict(span=copy.deepcopy(full), utf8_sha256=sha(original), bytes=len(original.encode())),
        original_body=dict(span=copy.deepcopy(body), utf8_sha256=sha(before), bytes=len(before.encode())),
        modified_test_utf8_sha256=sha(modified))
    if 'source_provenance' in candidate and candidate['source_provenance'] != provenance:
        raise ValueError('Existing source provenance differs')
    return dict(copy.deepcopy(original_candidate), source_provenance=provenance)
