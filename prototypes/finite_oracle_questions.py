"""Ask the same finite oracle problem in factored or fully expanded source.

Only presentation changes between the two arms. Each offered candidate keeps
its own inputs, imports, assertion slots and complete source evidence. No model
selects candidates, and missing answers never imply that old assertions apply.
"""
from __future__ import annotations

import copy
import hashlib
import json

from prototypes.finite_oracle_templates import build_catalogue, expand
from relation_search.instrument import _program_edits
from relation_search.oracle import DEPENDENCY_SYSTEM, SYSTEM as SOURCE_SYSTEM, prepare_requests, validate

VERSION = 'finite-oracle-questions-v1'
SYSTEM = (DEPENDENCY_SYSTEM[:DEPENDENCY_SYSTEM.index('Return JSON {"revisions":')]
          + DEPENDENCY_SYSTEM[len(SOURCE_SYSTEM):]).replace(
              'return an empty\nrevision list', 'mark the affected variant unknown') + '''
This request contains a finite family of concrete tests, not equivalent tests.
Each variant has its own imports, setup and old assertions. Assess EVERY variant
independently and all its assertions together. Do not choose only one variant.
The test may be shown fully or as fixed source segments interleaved with H holes.
For a template, reconstruct a variant by interleaving segments[0], replacement
H0, segments[1], replacement H1, ..., the final segment. Replacements are source
text, not values to interpolate or combine. Only the listed complete tuples are
offered; do not invent a Cartesian product or extra inputs. CODE_BLOCK markers
in source evidence expand to the exact shared code at that marker, supplied in
shared_code. Sharing text does not establish equal objects or equal behavior.
The response format for THIS request is {"results":[{"candidate":"C0",
"status":"revise", "updates":[{"assertion":"A0","code":"assert x == 3"}],
"basis":"brief contract/source justification"}]}. Include exactly one row for
each C id. status must be revise, keep, or unknown. keep and unknown have empty
updates; revise must change at least one offered expectation. Use unknown when
the complete expected behavior cannot be justified. Omission is unanswered,
never keep. No natural-language relation labels or new test bodies are wanted.
'''


def _sha(value):
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def factor_evidence(evidences):
    """Share exact declaration code bytes while retaining all rendered facts."""
    originals = [row['rendered'] for row in evidences]
    codes = sorted({d['code'] for row in evidences for d in row['declarations']
                    if len(d['code'].encode()) >= 128}, key=lambda text: (-len(text.encode()), text))
    prefix = 'CODE_BLOCK_' + _sha(originals)[:16] + '_'
    while any(prefix in text for text in [*originals, *codes]):
        prefix += '_'
    shared, rendered = {}, originals[:]
    for index, code in enumerate(codes):
        marker = '@@' + prefix + str(index) + '@@'
        if not any(code in text for text in rendered):
            continue
        shared[marker] = code
        rendered = [text.replace(code, marker) for text in rendered]
    for old, current in zip(originals, rendered):
        if restore_evidence(current, shared) != old:
            raise ValueError('factored evidence did not restore exact source')
    return shared, rendered


def restore_evidence(rendered, shared):
    for marker, code in shared.items():
        rendered = rendered.replace(marker, code)
    return rendered


def build_question(corpus, frontend, candidates, issue, *, representation='template'):
    if representation not in {'template', 'expanded'}:
        raise ValueError('unknown test representation')
    candidates = list(candidates)
    if not 1 <= len(candidates) <= 16:
        raise ValueError('a question must offer one to sixteen finite variants')
    # Instrumented inputs keep a pre-probe source snapshot. Both that snapshot
    # and the emitted edits can contain earlier oracle revisions; inspect the
    # effective source view as well as both recorded representations.
    if any(c.get('semantic_revision') or any(e.get('role') == 'semantic_expected'
           for e in [*_program_edits(c), *c.get('edits', []), *c.get('program_edits', [])])
           for c in candidates):
        raise ValueError('new questions cannot use historical oracle revisions')
    catalogue = build_catalogue(corpus, frontend, candidates)
    if len(catalogue['families']) != 1 or catalogue['families'][0]['status'] != 'factorized':
        raise ValueError('a question needs one mechanically factorized family')
    family = catalogue['families'][0]
    by_id = {v['candidate_id']: v for v in family['variants']}
    singletons = []
    for candidate in candidates:
        requests = prepare_requests(corpus, frontend, [candidate], issue,
                                    max_requests=1, per_request=1, evidence_mode='dependency')
        if len(requests) != 1:
            raise ValueError('variant has no complete existing-assertion oracle interface')
        singletons.append(requests[0])
    shared, rendered = factor_evidence([r['analysis_evidence']['C0'] for r in singletons])
    offered, analyses, members = {}, {}, []
    original_payload = json.loads(singletons[0]['prompt'])
    for index, (candidate, request, evidence) in enumerate(zip(candidates, singletons, rendered)):
        alias = 'C' + str(index)
        payload = json.loads(request['prompt'])
        if (payload['language'], payload['issue']) != (original_payload['language'], original_payload['issue']):
            raise ValueError('family oracle contracts differ')
        member = copy.deepcopy(payload['candidates'][0])
        member['candidate'] = alias
        variant = by_id[candidate['id']]
        if member.pop('modified_test') != expand(family, variant):
            raise ValueError('prepared test differs from the mechanical expansion')
        member['dependency_evidence']['rendered'] = evidence
        member['dependency_evidence']['rendered_bytes'] = len(evidence.encode())
        members.append(member)
        offered[alias] = copy.deepcopy(request['offered']['C0'])
        analyses[alias] = copy.deepcopy(request['analysis_evidence']['C0'])
    if representation == 'template':
        source = dict(segments=family['segments'], holes=family['holes'],
            variants=[dict(candidate='C'+str(i), replacements=by_id[c['id']]['replacements'])
                      for i, c in enumerate(candidates)])
    else:
        source = [dict(candidate='C'+str(i), modified_test=expand(family, by_id[c['id']]))
                  for i, c in enumerate(candidates)]
    payload = dict(language=original_payload['language'], issue=original_payload['issue'],
                   representation=representation, test_source=source, variants=members,
                   shared_code=shared)
    prompt = json.dumps(payload, ensure_ascii=False)
    request = {**copy.deepcopy(singletons[0]), 'id':_sha(prompt), 'system':SYSTEM,
        'prompt':prompt, 'offered':offered, 'analysis_evidence':analyses,
        'candidate_source_hash':hashlib.sha256(json.dumps(offered, sort_keys=True).encode()).hexdigest(),
        'kind':'finite_existing_assertion_oracle', 'finite_question_version':VERSION,
        'representation':representation, 'family_id':family['id'],
        'finite_members':[c['id'] for c in candidates], 'joint_member_limit':len(candidates)}
    return request


def validate_question(request, payload, corpus):
    """Validate each answer without treating omissions or unknown as keep."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    rows = payload.get('results') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > len(request['offered']):
        return dict(revisions=[], decisions=[], error='invalid_member_results',
            members=[dict(alias=alias, candidate_id=row['candidate']['id'], status='invalid_answer',
                          semantic_correctness='unreviewed') for alias,row in request['offered'].items()],
            answered_members=0, offered_members=len(request['offered']), all_members_answered=False)
    seen, valid, outcomes = set(), [], {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        alias = row.get('candidate')
        if not isinstance(alias, str) or alias not in request['offered']:
            continue
        if alias in seen:
            outcomes[alias] = 'duplicate_answer'
            valid = [item for item in valid if item['candidate'] != alias]
            continue
        seen.add(alias)
        status, updates = row.get('status'), row.get('updates')
        if (not isinstance(status, str) or status not in {'keep', 'revise', 'unknown'}
                or not isinstance(updates, list) or not isinstance(row.get('basis'), str)
                or any(not isinstance(update, dict)
                    or not isinstance(update.get('assertion'), str)
                    or not isinstance(update.get('code'), str) for update in updates)):
            outcomes[alias] = 'invalid_answer'
        elif status == 'unknown' and not updates:
            outcomes[alias] = 'unknown'
        elif status == 'keep' and not updates or status == 'revise' and updates:
            valid.append(dict(candidate=alias, updates=updates, basis=row['basis']))
            outcomes[alias] = status
        else:
            outcomes[alias] = 'invalid_answer'
    checked = validate(request, {'revisions':valid}, corpus)
    accepted = {r['candidate']:r['status'] for r in checked['decisions']}
    revised = {r['semantic_revision']['parent'] for r in checked['revisions']}
    members = []
    for alias, record in request['offered'].items():
        cid = record['candidate']['id']
        status = outcomes.get(alias, 'unanswered')
        if status in {'keep', 'revise'}:
            if accepted.get(cid) != 'local_hypothesis':
                status = accepted.get(cid, 'rejected_structure')
            elif status == 'revise' and cid not in revised:
                status = 'revision_did_not_change_expectation'
        members.append(dict(alias=alias, candidate_id=cid, status=status,
                            semantic_correctness='unreviewed'))
    return {**checked, 'members':members, 'answered_members':sum(r['status'] in {'keep','revise'} for r in members),
            'offered_members':len(members), 'all_members_answered':all(r['status'] in {'keep','revise'} for r in members)}
