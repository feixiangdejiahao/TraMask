"""Fresh whole-test review with explicit protocol-refinement obligations."""
from __future__ import annotations

import json
import sys

from relation_search import compact_contract_guarded as whole
from relation_search import protocol_text_refinement as relation

VERSION = 'complete-test-protocol-text-refinement-review.v1'
OBLIGATIONS = {
    'R_DOMAIN': 'The exact imported fixture, receiver class, consumer and public issue establish that both concrete packets belong to the supported receiver protocol domain. Wire grammar alone is insufficient. The old source guard can remain keyword-unknown; inspect the supplied complete source association. Do not infer validity from its status.',
    'R_ORIGINAL': 'Every original setup step and assertion remains valid for the full original host, including all parameters and source helper semantics. No original test is authoritative merely because it existed.',
    'R_REENTRY': 'After all original statements, the same receiver can accept the appended complete packet. No EOF, close, unfinished stream, hidden mutation, callback or prior result binding makes the second call invalid.',
    'R_TEXT': 'The fixed followup changes only associated_text by its declared single-code-point extension. All original and followup fields satisfy the actual public protocol domain. This is not Unicode normalization equivalence.',
    'R_PROJECTIONS': 'Each appended assertion is the shown original projection with only its observed-result variable renamed. The public contract guarantees that its exact passing predicate is invariant for this particular text refinement. Unchanged packet coordinates alone do not establish independence.',
}


def prepare(corpus, frontend, candidate, issue, *, max_prompt_bytes=96000, max_output_tokens=16384, **kwargs):
    metadata = candidate.get('protocol_text_refinement')
    if not metadata or metadata.get('version') != relation.VERSION:
        raise ValueError('Missing protocol refinement provenance')
    result = whole.prepare(corpus, frontend, candidate, issue, max_prompt_bytes=sys.maxsize,
        max_output_tokens=max_output_tokens, **kwargs)
    request = result.get('request')
    if request is None:
        return result
    payload = json.loads(request['prompt'])
    if relation.sha(payload['original_test']) != metadata['original_test_sha256'] or not payload['modified_test'].startswith(payload['original_test']+'\n'):
        raise ValueError('Original complete test was not retained')
    payload['checks'].update({key:dict(scope=value) for key,value in OBLIGATIONS.items()})
    # This is source/constructor evidence only. No selection response or rationale
    # is supplied as support for the independent full-test judgment.
    payload['protocol_text_refinement'] = metadata
    prompt = relation.compact(payload)
    size = len(request['system'].encode())+len(prompt.encode())
    if size > max_prompt_bytes:
        return dict(result,status='unknown_prompt_budget',request=None,required_bytes=size,max_prompt_bytes=max_prompt_bytes,truncated=False)
    request = dict(request,prompt=prompt,prompt_bytes=size,check_ids=list(payload['checks']),
        protocol_text_review=dict(version=VERSION,source_metadata_sha256=relation.core.digest(metadata)),
        external_roles=[*request['external_roles'],'explicit receiver domain, reentry and projection obligations'])
    request['id'] = request['query_sha256'] = whole._identity(request)
    return dict(result,status='prepared',request=request,prompt_bytes=size,truncated=False)


def decide(request, payload, *, finish_reason='stop'):
    evidence=request.get('protocol_text_review',{})
    context=json.loads(request['prompt'])
    if (evidence.get('version')!=VERSION or not set(OBLIGATIONS).issubset(request.get('check_ids',[]))
            or evidence.get('source_metadata_sha256')!=relation.core.digest(context.get('protocol_text_refinement'))):
        raise ValueError('Protocol refinement review obligations changed')
    return whole.decide(request,payload,finish_reason=finish_reason)
