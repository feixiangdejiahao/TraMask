"""Use a rejected whole-test hypothesis to propose bounded oracle corrections.

The fixed input program is preserved. Repairs change only existing assertions
accepted by the shared structural guard. A fresh whole-test review and native
execution must follow every proposal. Neither review nor repair is truth.
"""
from __future__ import annotations

import copy
import hashlib
import json

from relation_search import oracle


VERSION = 'contract-review-oracle-repair.v1'
SYSTEM = oracle.SYSTEM + '''
A previous semantic review is supplied as a fallible hypothesis. It is not a
test result or an independent specification. Check it against the actual issue,
complete modified test and helper context. Use a demonstrated oracle mismatch
to repair ALL affected offered assertions together. If the setup itself is
inapplicable, or a required repair lies outside offered assertions, return no
revision. Do not change inputs to rescue a test. Do not force a failing test.
Preserve meaningful assertion strength. A replacement which merely weakens a
specific required value into a broad range or non-null check is not a repair.
For a stateful test, compute observations after every preceding call and update;
the same receiver or closure can have changed state since its first use.
The follow-up program will undergo a separate complete-test review. Only native
execution after that review can establish whether it exposes a behavior gap.
'''


def prepare(corpus, frontend, candidate, issue, review_request, review_decision,
            *, max_prompt_bytes=96000, max_output_tokens=4096):
    candidate = oracle.program_candidate(candidate)
    requests = oracle.prepare_requests(corpus, frontend, [candidate], issue,
        max_requests=1, per_request=1, evidence_mode='baseline')
    if not requests:
        return dict(status='unknown_no_editable_assertions', request=None)
    request = copy.deepcopy(requests[0])
    payload = json.loads(request['prompt'])
    context = json.loads(review_request['prompt'])
    # Copy an explicit evidence allowlist, never the inventory or native record.
    context_fields = ('original_test', 'source_controls', 'source_analysis',
                      'conditional_predicate_facts', 'call_default_source_evidence',
                      'recovered_source_controls', 'source_documentation_links')
    payload['whole_test_context'] = {key: context[key] for key in context_fields if key in context}
    payload['previous_semantic_hypothesis'] = {
        key: review_decision[key] for key in ('judgments', 'basis', 'ledger') if key in review_decision}
    request.update(kind=VERSION, system=SYSTEM, prompt=json.dumps(payload, ensure_ascii=False,
                   separators=(',', ':')), thinking='disabled', max_tokens=max_output_tokens,
                   review_request_id=review_request['id'], no_execution_outcomes=True,
                   no_evaluation_labels=True, full_review_required=True)
    size = len(request['system'].encode()) + len(request['prompt'].encode())
    if size > max_prompt_bytes:
        return dict(status='unknown_prompt_budget', request=None, required_bytes=size)
    fields = {key: request[key] for key in ('system', 'prompt', 'thinking', 'max_tokens')}
    request['id'] = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False,
                                             separators=(',', ':')).encode()).hexdigest()
    request['prompt_bytes'] = size
    return dict(status='prepared', request=request)


def validate(request, payload, corpus, *, finish_reason='stop'):
    if finish_reason != 'stop':
        return dict(revisions=[], decisions=[], error='incomplete_provider_response')
    try:
        result = oracle.validate(request, payload, corpus)
    except (ValueError, TypeError, KeyError, AttributeError):
        return dict(revisions=[], decisions=[], error='invalid_repair_response')
    for candidate in result['revisions']:
        candidate['repair_provenance'] = dict(version=VERSION,
            review_request_id=request['review_request_id'], repair_request_id=request['id'],
            unchanged_input_program=True, full_review_required=True,
            native_execution_required=True, semantic_validity='unconfirmed')
    return result
