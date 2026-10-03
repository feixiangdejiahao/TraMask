from relation_search.contract_selection import validate


def test_selector_cannot_invent_candidates_or_ignore_budget():
    request=dict(aliases={'C0':'fixed','C1':'another'},budget=1)
    assert validate(request,dict(ranking=['C0']))['selected'][0]['candidate_id']=='fixed'
    assert len(validate(request,dict(ranking=['C0','C1']))['selected'])==1
    assert validate(request,dict(ranking=['C0','C0']))['error']=='invalid_selection_entry'
    assert validate(request,dict(ranking=['invented']))['error']=='invalid_selection_entry'


def test_incomplete_selection_never_creates_a_partial_portfolio():
    assert not validate(dict(aliases={},budget=1),'{}',finish_reason='length')['selected']
