"""One proposal from one already prepared complete R18 source context.

Only task grain and supplied editable anchors change. The sealed R18 decoder
still binds complete rewrites to original source and checks their boundaries.
"""
from __future__ import annotations

import copy
import json
from types import FunctionType

from relation_search import contract_gap_proposals as core


VERSION = 'atomic-source-contract-gap-proposals.v1'
POLICY = dict(
    version=VERSION,
    purpose='Joint generation task-grain/context experiment; not a pure cost ablation.',
    anchors='At most the first three distinct already-prepared R18 anchors, in their frozen order. No omitted-anchor recovery or repetition.',
    context='Identical public issue/API catalog plus one COMPLETE existing anchor context bundle. Helpers and source controls within that bundle remain intact.',
    output='Zero or one complete body rewrite per fixed slot; original R18 boundary decoder and fresh full-test review.',
    ordering='Slot 1 over all sorted trials, then slot 2, then slot 3. Missing anchors remain ledger entries.',
    duplicate='Keep the earliest exact source-bound complete program per trial; retain later duplicate slots and their cost. No refill.',
    generation_inputs='Only sealed R18 preparation, requests and source contexts; never its generation responses, decisions, audits or native outcomes.',
    review='Reuse R18 fresh candidate source enrichment, whole-test review, complete original controls and first failure plus one repeat.',
)


def prepare_slot(previous, slot):
    if type(slot) is not int or not 1 <= slot <= 3:
        raise ValueError('atomic_slot_out_of_range')
    if previous.get('version') != core.VERSION:
        raise ValueError('R18_generation_preparation_required')
    request = previous.get('request')
    if request is None:
        return dict(version=core.VERSION, atomic_version=VERSION, slot=slot,
                    seeds=[], request=None, status='no_anchor', source_sha256=previous['source_sha256'])
    if request.get('id') != core._identity(request):
        raise ValueError('inherited_request_identity_changed')
    payload = json.loads(request['prompt'])
    shown = {entry['seed_alias']: entry for entry in payload['seeds']}
    if len(shown) != len(payload['seeds']):
        raise ValueError('inherited_anchor_alias_not_unique')
    distinct, seen = [], set()
    for seed in previous['seeds']:
        entry = shown.get(seed['seed_alias'])
        if entry is None or core.digest(entry['context']) != seed['context_sha256']:
            raise ValueError('inherited_anchor_context_changed')
        if seed['base_test_id'] not in seen:
            distinct.append(seed); seen.add(seed['base_test_id'])
    if set(shown) != {seed['seed_alias'] for seed in previous['seeds']}:
        raise ValueError('inherited_anchor_inventory_changed')
    result = dict(version=core.VERSION, atomic_version=VERSION, slot=slot,
                  seeds=[], source_sha256=previous['source_sha256'], request=None,
                  status='no_anchor', truncated=False)
    if slot > min(3, len(distinct)):
        return result
    seed = distinct[slot-1]
    payload = copy.deepcopy(payload)
    payload['seeds'] = [shown[seed['seed_alias']]]
    payload['response_schema']['properties']['tests']['maxItems'] = 1
    payload['generation_slot'] = slot
    system = request['system'].replace('Generate up to three new validation tests',
        'Generate at most one new validation test').replace('Return zero through three tests.',
        'Return zero or one test.').replace(
        'Different tests may use the same seed. Order them by your expected usefulness.',
        'Only the single supplied seed may be used. This is one fixed generation slot.')
    prompt = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    size = len(system.encode())+len(prompt.encode())
    result.update(seeds=[copy.deepcopy(seed)], prompt_bytes=size,
                  inherited_seed_alias=seed['seed_alias'])
    if size > 96000:
        return dict(result, status='whole_context_prompt_budget')
    atomic = dict(request, system=system, prompt=prompt, kind=VERSION,
                  thinking='enabled', reasoning_effort='high', max_tokens=16384,
                  prompt_bytes=size)
    atomic['id'] = atomic['query_sha256'] = core._identity(atomic)
    return dict(result, request=atomic, status='prepared')


def decide(corpus, frontend, prepared, response, *, finish_reason='stop'):
    """Reuse the original decoder with a private one-proposal cardinality."""
    namespace = dict(vars(core), MAX_PROPOSALS=1)
    function = FunctionType(core.decide.__code__, namespace, 'decide',
                            core.decide.__defaults__, core.decide.__closure__)
    function.__kwdefaults__ = core.decide.__kwdefaults__
    decoded = function(corpus, frontend, prepared, response, finish_reason=finish_reason)
    decoded['atomic_version'] = VERSION
    decoded['slot'] = prepared['slot']
    for candidate in decoded['candidates']:
        candidate['order'] = [prepared['slot']]
        candidate['generator'] = VERSION
    return decoded


def aggregate(slot_records):
    """Keep every slot, including unavailable/unknown/refused/duplicate rows."""
    if [row['slot'] for row in slot_records] != [1, 2, 3]:
        raise ValueError('all_three_atomic_slots_required')
    candidates, ledger, seen = [], [], {}
    for record in slot_records:
        decoded = record['decoded']; slot = record['slot']
        row = dict(slot=slot, status=decoded['status'], reason=decoded.get('reason'),
                   preparation_status=record['preparation_status'],
                   dispatch_withheld_reason=record.get('dispatch_withheld_reason'),
                   provider_finish_reason=record.get('provider_finish_reason'),
                   proposed=decoded.get('proposed'), rejected=decoded.get('rejected', []),
                   decoded=record['decoded_receipt'], candidate_id=None)
        programs = decoded.get('candidates', [])
        if len(programs) > 1:
            raise ValueError('atomic_slot_contains_multiple_candidates')
        if programs:
            candidate = programs[0]
            if candidate['order'] != [slot]:
                raise ValueError('atomic_candidate_slot_changed')
            # Source-bound identity includes the original anchor and exact body.
            identity = core.digest({key:candidate[key] for key in
                ('base_test_id', 'source_test_ids', 'imports', 'edits')})
            row['candidate_id'] = candidate['id']
            row['complete_program_identity'] = identity
            if identity in seen:
                row.update(disposition='duplicate', duplicate_of_slot=seen[identity])
            else:
                seen[identity] = slot
                row['disposition'] = 'candidate'
                candidates.append(candidate)
        elif record['preparation_status'] == 'no_anchor':
            row['disposition'] = 'no_anchor'
        elif record.get('dispatch_withheld_reason'):
            row['disposition'] = record['dispatch_withheld_reason']
        elif decoded.get('reason') == 'incomplete_provider_response':
            row['disposition'] = ('length' if record.get('provider_finish_reason') == 'length'
                                  else 'incomplete_response')
        elif decoded.get('rejected'):
            row['disposition'] = ('scope_unknown' if any(x['status']=='scope_unknown'
                for x in decoded['rejected']) else 'structurally_rejected')
        elif decoded.get('status') == 'decoded':
            row['disposition'] = 'empty_proposal'
        elif record.get('provider_finish_reason') == 'stop':
            row['disposition'] = 'format_unknown'
        else:
            row['disposition'] = decoded.get('reason', decoded['status'])
        ledger.append(row)
    return dict(version=VERSION, status='aggregated', candidates=candidates,
                rejected=[row for row in ledger if row['disposition'] != 'candidate'],
                slot_ledger=ledger, alarm_eligible=False, semantic_validity='unconfirmed',
                external_model_calls=0, native_executions=0)
