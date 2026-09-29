from relation_search.frontier import Frontier, canonical_profile, select_round


def event(values, phase='after', origins=None):
    return dict(source_window='source-call', phase=phase, alias_partition=[],
                roles=[dict(name=k, status='observed', value=v, origin_span=(origins or {}).get(k))
                       for k, v in values.items()])


def test_same_relative_order_ignores_absolute_integer_translation():
    left = event({'x': {'type': 'int', 'value': 4}, 'y': {'type': 'int', 'value': 7}})
    right = event({'x': {'type': 'int', 'value': 104}, 'y': {'type': 'int', 'value': 107}})
    assert canonical_profile(left) == canonical_profile(right)
    right['phase'] = 'before'
    assert canonical_profile(left) != canonical_profile(right)
    right['phase'] = 'after'
    right['roles'][1]['origin_span'] = {'path': 'source.py', 'start_byte': 80}
    assert canonical_profile(left) != canonical_profile(right)


def test_dict_shape_uses_runtime_fields_and_ignores_opaque_metadata():
    full = {'type': 'dict', 'items': [[{'type': 'str', 'value': 'a'}, {'type': 'int', 'value': 1}]], 'length': 1}
    result = canonical_profile(event({'m': full, 'object': {'type': 'Custom', 'opaque': True, 'alias': 0}}))
    assert result['presence'] == [('m', ['a'], False)]
    assert ('object', 'Custom', 'opaque') in result['scalar']
    missing = event({'m': {'type': 'dict', 'items': [], 'length': 0}})
    assert canonical_profile(missing)['presence'] != result['presence']


def test_unexecuted_hypothesis_never_counts_as_profile():
    frontier = Frontier()
    result = frontier.observe('candidate', [])
    assert not result['retained'] and not frontier.profiles
    assert result['status'] == 'no_runtime_profile'


def test_all_unknown_events_do_not_create_profiles_or_retained_parents():
    unknown = dict(source_window='source-call', phase='after', alias_partition=[], roles=[
        dict(name='property', status='unknown', kind='read', reason='TypeError')])
    frontier = Frontier()
    result = frontier.observe('candidate', [unknown])
    assert result == dict(candidate_id='candidate', measured_profiles=[], new_profiles=[],
                          retained=False, status='no_runtime_profile')
    assert not frontier.profiles
    # Legacy event dictionaries use an explicit unknown marker as their value.
    unknown['roles'] = {'property': {'status': 'unknown'}}
    assert not frontier.observe('other', [unknown])['retained']
    assert not frontier.profiles


def test_repeated_runtime_containers_resolve_contents_instead_of_empty_presence():
    from relation_search.runtime import HELPER_SOURCE
    helper = {}
    exec(HELPER_SOURCE, helper)
    shared_dict, shared_list = {'field': 1}, [1, 2]
    aliases, seen = {}, set()
    values = {name: helper['_encode'](value, aliases, seen)
              for name, value in [('map_first', shared_dict), ('map_again', shared_dict),
                                  ('list_first', shared_list), ('list_again', shared_list)]}
    assert values['map_again']['reference'] and values['list_again']['reference']
    profile = canonical_profile(event(values))
    assert profile['presence'] == [('list_again', 2, False), ('list_first', 2, False),
                                   ('map_again', ['field'], False), ('map_first', ['field'], False)]


def test_reference_resolution_uses_nested_first_occurrence_and_snapshot_scope():
    from relation_search.runtime import HELPER_SOURCE
    helper = {}
    exec(HELPER_SOURCE, helper)
    shared = {'field': 1}
    aliases, seen = {}, set()
    parent = helper['_encode']([shared], aliases, seen)
    reference = helper['_encode'](shared, aliases, seen)
    profile = canonical_profile(event({'parent': parent, 'child': reference}))
    assert ('child', ['field'], False) in profile['presence']
    # No earlier event or concrete object ID supplies content to this snapshot.
    orphan = canonical_profile(event({'child': reference}))
    assert orphan['presence'] == []


def test_partial_string_capture_is_distinct_from_complete_shape():
    full = event({'text': {'type': 'str', 'value': 'prefix', 'truncated': False}})
    partial = event({'text': {'type': 'str', 'value': 'prefix', 'truncated': True}})
    assert canonical_profile(full)['strings'] == [('text', True, False, False, False, False)]
    assert canonical_profile(partial)['strings'] == [('text', True, False, False, False, True)]
    assert canonical_profile(full) != canonical_profile(partial)


def test_rotation_excludes_executed_ids_and_does_not_starve_second_operator():
    def edit(after):
        return {'span': {'path': 'test_values.py', 'start_byte': 20, 'end_byte': 21},
                'before': '0', 'after': after}
    rows = [dict(id=str(i), kind='a', base_test_id='one', edits=[edit(str(i))]) for i in range(30)]
    rows.append(dict(id='other', kind='b', base_test_id='two', edits=[edit('z')]))
    # Family a has already received one slot in the preceding round; b receives
    # its first slot before a receives a second one.
    assert [r['id'] for r in select_round(rows, 2, ['0'])] == ['other', '1']


def test_rotation_preserves_frontend_relation_order_across_source_seeds():
    def edit(after):
        return {'span': {'path': 'test_values.py', 'start_byte': 20, 'end_byte': 21},
                'before': '0', 'after': after}
    rows = [dict(id='first', operator='a', base_test_id='z_seed', edits=[edit('long_value')]),
            dict(id='second', operator='a', base_test_id='a_seed', edits=[edit('x')]),
            dict(id='third', operator='b', base_test_id='other', edits=[edit('z')])]
    assert [row['id'] for row in select_round(rows, 3)] == ['first', 'third', 'second']


def test_frontier_resume_preserves_representative_limit_and_checks_sha():
    import copy
    import pytest
    observed = event({'x': {'type': 'bool', 'value': True}})
    frontier = Frontier()
    frontier.observe('first', [observed])
    resumed = Frontier.restore(frontier.snapshot())
    assert resumed.observe('second', [observed])['retained']
    assert not resumed.observe('third', [observed])['retained']
    changed = copy.deepcopy(frontier.snapshot())
    changed['representatives'] += 1
    with pytest.raises(ValueError, match='checkpoint changed'):
        Frontier.restore(changed)
