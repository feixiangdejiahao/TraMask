"""Independent full-program gate for added boundary observations."""
from __future__ import annotations

import json
import sys

from relation_search import compact_admission, compact_contract_guarded as whole_test

VERSION = 'complete-test-contract-scalar-observer-review.v1'
EXTRA_CHECKS = {
    'OBSERVER_CONTRACT': dict(kind='required_source_premise', question='Does a public contract preserve this exact scalar observation across the original boundary, on the exact receiver and original input? Resolve owner/child identity, phase and all argument values. Similar method names, current implementation output and a generation quote do not prove the relation.'),
    'OBSERVER_ARGUMENT_CAPTURE': dict(kind='required_source_premise', question='Each new argument initializer is an EXTRA evaluation immediately before the boundary. Original evaluations remain. Prove these extra evaluations are defined and free of effects, and that capturing and reusing the resulting values across the boundary preserves argument meaning. Const does not prove deep immutability, and a source example does not prove call purity. Reject or mark unknown if the argument is a live mutable view or its identity matters.'),
    'OBSERVER_READS': dict(kind='required_source_premise', question='Prove both new Q calls are read-only, repeatable and defined before/after this exact boundary, including destroyed or nullified objects. They must not flush, consume input, schedule work, mutate state or change any old assertion. Require boolean/number/string scalar values and equality semantics without coercion, aliasing, nondeterminism or NaN.'),
    'OBSERVER_WHOLE_TEST': dict(kind='required_source_premise', question='Check the complete retained test, not just the inserted equality. Prove all original setup/actions/assertions remain valid with the added reads and captures. Check callbacks, exception/control-flow branches, object lifetime, external state, and the time at which arguments and observations are evaluated. Missing helper or API bodies must remain explicit unknowns.'),
}


def prepare(corpus, frontend, candidate, issue, *, checks=None,
            max_prompt_bytes=96000, max_output_tokens=16384):
    result = whole_test.prepare(corpus, frontend, candidate, issue, checks=checks,
        max_prompt_bytes=sys.maxsize, max_output_tokens=max_output_tokens)
    request = result.get('request')
    if request is None:
        return result
    payload = json.loads(request['prompt'])
    if set(EXTRA_CHECKS) & set(payload['checks']):
        raise ValueError('observer_check_identity_conflict')
    payload['checks'].update(EXTRA_CHECKS)
    payload['observation_review_boundary'] = 'Judge actual complete code and public source. Generation hypotheses, quotes and source selection do not authorize equality or purity.'
    prompt = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    size = len(request['system'].encode())+len(prompt.encode())
    if size > max_prompt_bytes:
        return dict(result, status='unknown_prompt_budget', request=None,
            prompt_bytes=size, required_bytes=size, max_prompt_bytes=max_prompt_bytes, truncated=False)
    request = dict(request, kind=VERSION, prompt=prompt, prompt_bytes=size,
        check_ids=list(payload['checks']))
    request['id'] = request['query_sha256'] = whole_test._identity(request)
    return dict(result, request=request, status='prepared', prompt_bytes=size,
        observer_premises_required=list(EXTRA_CHECKS), truncated=False)


def decide(request, payload, *, finish_reason='stop'):
    original = json.loads(request['prompt'])
    if (request.get('kind') != VERSION or request.get('codec_guard', {}).get('allow_prior_gate') is not True
            or any(original.get('checks', {}).get(k) != v for k,v in EXTRA_CHECKS.items())
            or request.get('check_ids') != list(original.get('checks', {}))):
        return dict(status='unknown', alarm_eligible=False, semantic_validity='unconfirmed',
            reason='observer_required_premises_changed', request_id=request['id'])
    return compact_admission.decide(request, payload, finish_reason=finish_reason)
