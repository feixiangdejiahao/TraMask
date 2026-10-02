"""Independent lookup audit catches falsified reduction and hidden caps."""
import pytest

from scripts.census_observation_address_search import verify_lookup_rows, verify_source_refs


BANK = [dict(id='a', owner_key=['Store'], fields=['items']),
        dict(id='b', owner_key=['Store'], fields=['other']),
        dict(id='c', owner_key=['Other'], fields=['items'])]
DEMANDS = [dict(id='q', owner_key=['Store'], field='items')]


def test_owner_and_address_domains_can_have_different_valid_hit_sets():
    control = [dict(demand_id='q',all_hit_ids=['a','b'],retrieved_ids=['a','b'])]
    treatment = [dict(demand_id='q',all_hit_ids=['a'],retrieved_ids=['a'])]
    assert verify_lookup_rows(BANK,DEMANDS,control,mode='receiver_only')['raw_retrieved_count'] == 2
    assert verify_lookup_rows(BANK,DEMANDS,treatment,mode='address')['raw_retrieved_count'] == 1


def test_forged_reduction_and_owner_collision_fail():
    for hits in [[], ['b'], ['c']]:
        with pytest.raises(ValueError,match='membership'):
            verify_lookup_rows(BANK,DEMANDS,[dict(demand_id='q',all_hit_ids=hits,retrieved_ids=hits)],mode='address')


def test_silent_query_cap_is_not_an_address_lookup_reduction():
    with pytest.raises(ValueError,match='truncation'):
        verify_lookup_rows(BANK,DEMANDS,[dict(demand_id='q',all_hit_ids=['a','b'],retrieved_ids=['a'])],mode='receiver_only')


def test_literal_alias_provenance_requires_definition_span_for_literal_text():
    corpus = dict(sources={'a.py':dict(code='k="a"\n')})
    alias_use = dict(path='a.py',start_byte=0,end_byte=1)
    definition = dict(path='a.py',start_byte=2,end_byte=5)
    assert verify_source_refs(dict(text='"a"',value_span=definition),corpus) == 2
    with pytest.raises(ValueError,match='provenance'):
        verify_source_refs(dict(text='"a"',span=alias_use),corpus)
