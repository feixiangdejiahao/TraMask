from relation_search.contract_selection import validate


def test_selector_cannot_invent_candidates_or_ignore_budget():
    request=dict(aliases={'C0':'fixed'},budget=1)
    row=dict(candidate='C0',obligation='cleanup after rejection',applicability='valid operation',oracle_work='closed state')
    assert validate(request,dict(selected=[row]))['selected'][0]['candidate_id']=='fixed'
    assert validate(request,dict(selected=[row,row]))['error']=='selection_budget_exceeded'
    row['candidate']='invented'
    assert validate(request,dict(selected=[row]))['error']=='invalid_selection_entry'


def test_incomplete_selection_never_creates_a_partial_portfolio():
    assert not validate(dict(aliases={},budget=1),'{}',finish_reason='length')['selected']
