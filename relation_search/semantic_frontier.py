"""Keep program-selected hypotheses waiting for their bounded oracle turn.

No outcome, cached oracle, or benchmark label enters this queue. Expanding the
program frontier must not silently discard an unserved assertion hypothesis.
"""
from .semantic_selection import select
import hashlib


POLICY = 'persistent-source-semantic-frontier-v1'


def advance(corpus, candidates, previous=None, *, budget=16, selected_ids=(),
            frontend=None, selection_policy='shape', patch=None):
    previous = previous or {}
    if previous.get('selection_policy', selection_policy) != selection_policy:
        raise ValueError('Semantic queue selection policy changed')
    patch_sha = None
    if selection_policy in {'patch-strict', 'patch-may'}:
        if frontend is None or not isinstance(patch, str):
            raise ValueError('Patch selection requires source frontend and submitted patch')
        patch_sha = hashlib.sha256(patch.encode()).hexdigest()
        if previous.get('patch_sha256', patch_sha) != patch_sha:
            raise ValueError('Semantic queue submitted patch changed')
    catalogue = {row['id']: row for row in previous.get('candidates', [])}
    for row in candidates:
        if row['id'] in catalogue and catalogue[row['id']] != row:
            raise ValueError('Same semantic hypothesis ID has changed source edits')
        catalogue[row['id']] = row
    served = set(previous.get('selected_ids', [])) | set(selected_ids)
    if selection_policy == 'impact':
        from .impact_selection import select as select_impact
        if frontend is None:
            raise ValueError('Impact selection requires source frontend facts')
        ordered = select_impact(corpus, frontend, list(catalogue.values()), budget=len(catalogue))
    elif selection_policy == 'shape':
        ordered = select(corpus, catalogue.values(), budget=len(catalogue))
    elif selection_policy in {'patch-strict', 'patch-may'}:
        from experimental.patch_observation_priority import select as select_patch
        ordered = select_patch(corpus, frontend, list(catalogue.values()), patch,
                               budget=len(catalogue), mode=selection_policy.removeprefix('patch-'))
    else:
        raise ValueError('Unknown semantic selection policy')
    pending = [row for row in ordered['selected'] if row['id'] not in served]
    chosen = pending[:budget]
    chosen_ids = {row['id'] for row in chosen}
    remaining = [row['id'] for row in pending[budget:]]
    return dict(selection=dict(selected=chosen,
                ranking=[{**row, 'previously_selected': row['id'] in served,
                          'selected': row['id'] in chosen_ids} for row in ordered.get('ranking', [])],
                policy=POLICY, source_order_policy=ordered.get('policy'), budget=budget,
                catalogue_count=len(catalogue), eligible_count=len(pending),
                selected_count=len(chosen), pending_count=len(remaining)),
                frontier=dict(policy=POLICY, selection_policy=selection_policy,
                              patch_sha256=patch_sha, candidates=list(catalogue.values()),
                              selected_ids=sorted(served | chosen_ids), pending_ids=remaining))
