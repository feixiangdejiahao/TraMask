"""Review a complete fixed test with API context and a local codec guard.

This method preserves the compact review's complete-test P/Q obligations. It
adds source-bound documentation and types, and withholds a request when the
codec guard cannot justify passing it to the semantic reviewer. A withheld
candidate is unknown, not invalid. The caller may continue its frozen ranking.
"""
from __future__ import annotations

import hashlib
import json
import sys

from relation_search import compact_admission, codec_boundary_guard, source_contract_evidence


VERSION = 'compact-contract-codec-review.v1'


def _identity(request):
    fields = {key: request[key] for key in
              ('system', 'prompt', 'thinking', 'max_tokens', 'reasoning_effort')
              if key in request}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def prepare(corpus, frontend, candidate, issue, *, checks=None,
            max_prompt_bytes=64000, max_output_tokens=2048):
    # Build the whole fixed test before applying the final augmented budget.
    # No source, check, or test suffix is removed to fit the request.
    result = compact_admission.prepare(corpus, frontend, candidate, issue,
        checks=checks, max_prompt_bytes=sys.maxsize, max_output_tokens=max_output_tokens)
    request = result.get('request')
    if request is None:
        return result
    payload = json.loads(request['prompt'])
    # These are compact's original/modified complete test spans, not standalone
    # edit fragments. The guard resolves fragment syntax against those spans.
    guard = codec_boundary_guard.analyze(payload)
    evidence = source_contract_evidence.collect(corpus, result['analysis'])
    result.update(codec_guard=guard, api_contract_context=evidence)
    payload['api_contract_context'] = evidence
    prompt = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    size = len(request['system'].encode()) + len(prompt.encode())
    result.update(prompt_bytes=size, truncated=False)
    if not guard['allow_prior_gate']:
        return dict(result, status='unknown_codec_or_input_boundary', request=None,
                    alarm_eligible=False, semantic_validity='unconfirmed',
                    reason=guard['status'], withheld_not_invalid=True)
    if size > max_prompt_bytes:
        return dict(result, status='unknown_prompt_budget', request=None,
                    alarm_eligible=False, required_bytes=size,
                    max_prompt_bytes=max_prompt_bytes)
    request = dict(request, kind=VERSION, prompt=prompt, prompt_bytes=size,
                   codec_guard=guard,
                   external_roles=[*request['external_roles'],
                                   'source-bound API documentation and type declarations'])
    request['id'] = request['query_sha256'] = _identity(request)
    return dict(result, status='prepared', request=request)


def decide(request, payload, *, finish_reason='stop'):
    # A model's all-supported response must not bypass the local withholding
    # decision. The runner freezes this guard with the complete request.
    if (request.get('kind') != VERSION
            or request.get('codec_guard', {}).get('allow_prior_gate') is not True):
        return dict(status='unknown', alarm_eligible=False,
                    semantic_validity='unconfirmed',
                    reason='codec_guard_not_confirmed', request_id=request['id'])
    return compact_admission.decide(request, payload, finish_reason=finish_reason)
