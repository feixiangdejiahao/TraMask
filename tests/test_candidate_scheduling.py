from prototypes.candidate_scheduling import select


def candidates(families=12, each=20):
    return [dict(id=f'{family}-{index}', base_test_id='seed', operator=f'family_{family:02}',
                 edits=[dict(span=dict(path='source.py', start_byte=0, end_byte=1), before='0',
                             after=str(family*100+index+1))], imports=[])
            for family in range(families) for index in range(each)]


def test_small_budget_cannot_starve_later_families_across_rounds():
    pool = candidates()
    first = select(pool, 8)
    second = select(pool, 8, [x['id'] for x in first])
    assert len({x['operator'] for x in first+second}) == 12
    assert len({x['id'] for x in first+second}) == 16


def test_order_inside_a_family_is_preserved_and_observation_does_not_rank():
    pool = candidates(2, 4)
    for row in pool:
        row['runtime_feedback'] = {'correct': row['id']=='1-3'}
    output = select(pool, 8)
    for family in ['family_00', 'family_01']:
        assert [x['id'] for x in output if x['operator']==family] == [x['id'] for x in pool if x['operator']==family]


def test_exact_edit_cannot_consume_multiple_service_slots():
    pool = candidates(1, 3)
    duplicate = {**pool[0], 'id':'duplicate', 'operator':'other'}
    assert len(select([*pool, duplicate], 10)) == 3
    assert len(select([*pool, duplicate], 10, ['duplicate'])) == 2
