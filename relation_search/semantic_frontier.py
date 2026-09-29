"""Keep program-selected hypotheses waiting for their bounded oracle turn.

No outcome, cached oracle, or benchmark label enters this queue. Expanding the
program frontier must not silently discard an unserved assertion hypothesis.
"""
from .semantic_selection import select


POLICY = 'persistent-source-semantic-frontier-v1'


def advance(corpus, candidates, previous=None, *, budget=16, selected_ids=()):
    previous = previous or {}
    catalogue = {row['id']: row for row in previous.get('candidates', [])}
    for row in candidates:
        if row['id'] in catalogue and catalogue[row['id']] != row:
            raise ValueError('Same semantic hypothesis ID has changed source edits')
        catalogue[row['id']] = row
    served = set(previous.get('selected_ids', [])) | set(selected_ids)
    ordered = select(corpus, catalogue.values(), budget=len(catalogue))
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
                frontier=dict(policy=POLICY, candidates=list(catalogue.values()),
                              selected_ids=sorted(served | chosen_ids), pending_ids=remaining))
