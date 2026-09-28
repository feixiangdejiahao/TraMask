from relational_gap.closure import ClosureBudget, interval_relation, missing_cells, scalar_relation


def row(identifier, x, y, **extra):
    return dict(id=identifier, observation='read_two_fields', carrier='same_receiver',
                coordinates={'left.present': x, 'right.present': y}, **extra)


def test_mixed_presence_cells_are_generated_and_not_claimed_feasible():
    got = missing_cells([row('full', True, True), row('empty', False, False)])
    assert {tuple(g['constraints'].values()) for g in got['gaps']} == {(True, False), (False, True)}
    assert all(g['coordinate_edit_distance'] == 1 and g['feasibility'] == 'unknown' for g in got['gaps'])
    assert got['counts']['observed_but_check_unknown'] == 6
    assert got['counts'].get('checked_cells', 0) == 0


def test_other_object_phase_or_version_cannot_close_a_gap():
    rows = [row('full', True, True), row('empty', False, False)]
    other = row('other', True, False)
    other['carrier'] = 'other_receiver'
    version = row('old', False, True, candidate_version='old')
    got = missing_cells(rows + [other, version])
    assert len([g for g in got['gaps'] if g['carrier'] == 'same_receiver']) == 2


def test_checked_requires_execution_and_independent_assertion_basis():
    got = missing_cells([row('one', True, True, executed_on_candidate=True, assertion_justified=True)])
    assert got['counts']['checked_cells'] == 3
    assert got['gaps'] == []


def test_determinism_and_unknown_budget_not_no_gap_claim():
    rows = [row('a', True, True), row('b', False, False)]
    assert missing_cells(rows) == missing_cells(list(reversed(rows)))
    got = missing_cells(rows, budget=ClosureBudget(max_cells=1))
    assert got['enumeration_exhausted']


def test_half_open_interval_and_scalar_boundaries():
    assert scalar_relation(7, 7) == 'eq'
    assert scalar_relation(True, 1) is None
    assert interval_relation((1, 4), (4, 8)) == 'disjoint'
    assert interval_relation((1, 4), (3, 8)) == 'partial_overlap'
    assert interval_relation((1, 8), (3, 4)) == 'contains'
