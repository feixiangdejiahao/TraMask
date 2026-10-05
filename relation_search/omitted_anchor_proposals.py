"""Recover only the original whole-context budget omissions, one per request.

The source context builder and atomic complete-body decoder are unchanged.
This module changes which fixed source anchors get their own request budget.
"""
from __future__ import annotations

import copy
import hashlib
import json
from types import FunctionType

from relation_search import contract_gap_proposals as core
from relation_search import atomic_contract_gap_proposals as atomic
from relation_search.direct_generation_provenance import attach

VERSION = 'omitted-anchor-atomic-proposals.v1'
POLICY = dict(atomic.POLICY, version=VERSION,
    purpose='Recover all original batch-budget omissions with independent request budgets. Joint context-granularity and low-generation-reasoning experiment; not a pure ablation.',
    anchors='All and only original R18 whole_context_prompt_budget omissions, in their sealed omission order, at most three per trial. No visible-anchor reuse, outcome selection or refill.',
    context='Rebuild each omitted original ID with the unchanged R18 complete-context builder from its original source projection. Preserve the exact original issue/API catalog and complete original P/Q context. No oracle-dependency retrieval.',
    generation='One fixed omitted anchor per slot; zero or one complete body rewrite; low reasoning, enabled thinking, 16384 output tokens.',
    provenance='Attach exact complete source provenance before fresh review and emission, using the existing atomic decoder and provenance checker.',
    generation_inputs='Only sealed original R18 preparation/omission ledger/source projection. Never generation responses, semantic decisions, audits or native outcomes.')


def omissions(inherited):
    if inherited.get('version') != core.VERSION:
        raise ValueError('R18_source_preparation_required')
    rows = [r for r in inherited.get('omitted', []) if r.get('reason')=='whole_context_prompt_budget']
    if len(rows)>3 or len({r['base_test_id'] for r in rows})!=len(rows):
        raise ValueError('at_most_three_unique_original_omissions_required')
    if any(r['base_test_id'] in {s['base_test_id'] for s in inherited['seeds']} for r in rows):
        raise ValueError('omitted_anchor_already_visible')
    return rows


def recover(corpus, frontend, issue, inherited):
    """Source-only rebuilding; no model or subject execution occurs."""
    selected = omissions(inherited)
    checked = core.decide(corpus, frontend, inherited, '{"tests":[]}') if inherited.get('request') else None
    if selected and (checked is None or checked['status']!='decoded'):
        raise ValueError('original_source_context_unavailable')
    old_payload = json.loads(inherited['request']['prompt']) if inherited.get('request') else None
    recovered = []
    for row in selected:
        identifier = row['base_test_id']
        # Selection follows the sealed omission ledger, not any semantic rank.
        def order(item):
            return [0 if item[0]==identifier else 1, *core._order(item)]
        namespace = dict(vars(core), MAX_SEEDS=1, _order=order)
        build = FunctionType(core.prepare.__code__, namespace, 'prepare', core.prepare.__defaults__, core.prepare.__closure__)
        build.__kwdefaults__ = core.prepare.__kwdefaults__
        prepared = build(corpus, frontend, issue)
        if prepared.get('request'):
            payload = json.loads(prepared['request']['prompt'])
            if (len(prepared['seeds'])!=1 or prepared['seeds'][0]['base_test_id']!=identifier
                    or payload['issue_api_catalog']!=old_payload['issue_api_catalog']
                    or payload['issue']!=old_payload['issue']):
                raise ValueError('single_context_changed_original_issue_catalog_or_anchor')
        recovered.append(dict(original_omission=copy.deepcopy(row), preparation=prepared))
    result = dict(version=VERSION, policy=POLICY,
        inherited_preparation_sha256=core.digest(inherited), source_sha256=inherited['source_sha256'],
        recovered=recovered, provider_calls=0, native_executions=0)
    validate_recovery(corpus, inherited, result)
    return result


def validate_recovery(corpus, inherited, recovered):
    """Validate immutable provenance without repeatedly rebuilding all helpers."""
    if (recovered.get('version')!=VERSION or recovered.get('policy')!=POLICY
            or recovered.get('inherited_preparation_sha256')!=core.digest(inherited)
            or recovered.get('source_sha256')!=inherited['source_sha256']
            or [r['original_omission'] for r in recovered.get('recovered',[])]!=omissions(inherited)):
        raise ValueError('recovery_omission_or_source_origin_changed')
    original_payload = json.loads(inherited['request']['prompt']) if inherited.get('request') else None
    for row in recovered['recovered']:
        prepared = row['preparation'];identifier = row['original_omission']['base_test_id']
        if prepared['source_sha256']!=inherited['source_sha256']:
            raise ValueError('recovered_source_snapshot_changed')
        if prepared.get('request') is None:
            continue
        checked = core.decide(corpus, None, prepared, '{"tests":[]}')
        if checked['status']!='decoded' or len(prepared['seeds'])!=1:
            raise ValueError('invalid_recovered_source_context')
        seed = prepared['seeds'][0]
        if seed['base_test_id']!=identifier:
            raise ValueError('recovered_anchor_identity_changed')
        source,test,_ = core._source_test(corpus,identifier)
        if (seed['span']!=test['span'] or seed['body_span']!=test['body_span']
                or seed['source_sha256']!=hashlib.sha256(source.data).hexdigest()):
            raise ValueError('recovered_source_binding_changed')
        payload = json.loads(prepared['request']['prompt'])
        original = source.data[test['span']['start_byte']:test['span']['end_byte']].decode()
        content = payload['seeds'][0]['context']
        if (content['original_test']!=original or content['modified_test']!=original
                or content['input_edits'] or payload['issue']!=original_payload['issue']
                or payload['issue_api_catalog']!=original_payload['issue_api_catalog']):
            raise ValueError('recovered_context_not_complete_original_identity')
    return recovered


def prepare_slot(recovered, slot):
    if type(slot) is not int or not 1<=slot<=3 or recovered.get('version')!=VERSION:
        raise ValueError('invalid_recovered_slot')
    if slot>len(recovered['recovered']):
        return dict(version=core.VERSION, atomic_version=VERSION, slot=slot, seeds=[], request=None,
            status='no_anchor', source_sha256=recovered['source_sha256'], truncated=False)
    row = recovered['recovered'][slot-1]
    result = atomic.prepare_slot(row['preparation'],1)
    result.update(slot=slot, atomic_version=VERSION, original_omission=copy.deepcopy(row['original_omission']))
    if result['request']:
        request=result['request'];payload=json.loads(request['prompt']);payload['generation_slot']=slot
        request.update(prompt=json.dumps(payload,ensure_ascii=False,separators=(',',':')),
            kind=VERSION, reasoning_effort='low', thinking='enabled', max_tokens=16384)
        request['prompt_bytes']=len(request['system'].encode())+len(request['prompt'].encode())
        request['id']=request['query_sha256']=core._identity(request)
        result['prompt_bytes']=request['prompt_bytes']
    return result


def decide(corpus, frontend, prepared, response, *, finish_reason='stop'):
    result=atomic.decide(corpus,frontend,prepared,response,finish_reason=finish_reason)
    result['atomic_version']=VERSION
    # Candidate generator remains the exact reused atomic constructor identity.
    result['candidates']=[attach(corpus,candidate) for candidate in result['candidates']]
    return result


def aggregate(records):
    result=atomic.aggregate(records)
    result['version']=VERSION
    return result
