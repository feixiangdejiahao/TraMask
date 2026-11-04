"""Check finite-search completeness against real parsed source and global constraints."""

import ast
import json
import random

import pytest

from eviweave.composition import indexed_search, naive_search, parse_relations


def compare(raw):
    relations = parse_relations(json.loads(json.dumps(raw)))
    naive = naive_search(relations)
    indexed = indexed_search(relations)
    expected = {plan.choices for plan in naive.plans}
    actual = [plan.choices for plan in indexed.iter_plans()]
    assert set(actual) == expected
    assert len(actual) == len(expected) == indexed.plan_count
    # Expanding the compact representation must still satisfy the full boundary.
    assert [plan.as_dict() for plan in indexed.iter_plans()] == [plan.as_dict() for plan in naive.plans]
    return naive, indexed


def test_parsed_history_produces_multi_role_rows_and_shared_suffixes():
    source = '''
def test_buffered():
    response = Response(body="malformed", transport="buffer")
    consume(response, transport="buffer")
    assert response.closed

def test_streamed():
    response = Response(body="valid", transport="stream")
    consume(response, transport="stream")
    assert response.closed

def test_dynamic(mode):
    response = Response(body="empty", transport=mode)
    assert response.closed

def test_unsupported():
    response = Response(body="other", transport="unimplemented")
    assert response.closed
'''
    bodies, constructors, consumers, observations = [], [], [], []
    for function in ast.parse(source).body:
        assignment = function.body[0]
        keywords = {kw.arg: kw.value for kw in assignment.value.keywords}
        origin = f"history.py:{function.lineno}"
        bodies.append({'id': function.name, 'bindings': {'body': ast.literal_eval(keywords['body'])},
                       'provenance': [origin]})
        transport = keywords['transport']
        constructors.append({
            'id': function.name,
            'bindings': {'receiver': assignment.targets[0].id,
                         'transport': ast.literal_eval(transport) if isinstance(transport, ast.Constant) else None},
            'order': [['construct', 'consume']], 'provenance': [origin],
        })
        for statement in function.body[1:]:
            if isinstance(statement, ast.Expr):
                consumers.append({
                    'id': function.name,
                    'bindings': {'receiver': statement.value.args[0].id,
                                 'transport': ast.literal_eval(statement.value.keywords[0].value)},
                    'order': [['consume', 'observe']], 'provenance': [origin],
                })
            else:
                assert isinstance(statement, ast.Assert)
                observations.append({'id': function.name, 'bindings': {'receiver': statement.test.value.id},
                                     'provenance': [origin]})
    naive, indexed = compare([
        {'id': 'body', 'rows': bodies}, {'id': 'construct', 'rows': constructors},
        {'id': 'consume', 'rows': consumers}, {'id': 'observe', 'rows': observations},
    ])
    assert indexed.plan_count == 64
    assert 'test_unsupported' not in indexed.surviving[1]
    assert 'test_dynamic' in indexed.surviving[1]
    assert indexed.stats['cache_hits'] > 0
    assert indexed.stats['search_row_checks'] < naive.stats['search_row_checks']
    assert any('binding:transport' in p.as_dict()['unknown'] for p in indexed.iter_plans())
    assert len(list(indexed.iter_plans(limit=3))) == 3
    assert indexed.plan_count == 64  # A retrieval budget does not truncate the space.


def test_joint_setup_is_one_choice_and_provenance_is_not_an_extra_dimension():
    _, space = compare([
        {'id': 'durations', 'rows': [
            {'id': 'original', 'bindings': {'left.duration': 1, 'right.duration': 10}},
            {'id': 'migrate', 'bindings': {'left.duration': 10, 'right.duration': 1},
             'provenance': ['old.py:3', 'other.py:8']},
        ]},
        {'id': 'observation', 'rows': [{'id': 'total', 'bindings': {'check': 'sum'}}]},
    ])
    assert space.plan_count == 2
    assignments = [p.as_dict() for p in space.iter_plans()]
    assert {(p['bindings']['left.duration'], p['bindings']['right.duration']) for p in assignments} == {(1, 10), (10, 1)}
    assert assignments[1]['provenance'] == ['old.py:3', 'other.py:8']


def test_unknown_is_not_false_and_concrete_guards_conflict():
    _, space = compare([
        {'id': 'setup', 'rows': [
            {'id': 'unknown', 'bindings': {'object': None}, 'guards': {'enabled': None}, 'unknown': ['factory identity']},
            {'id': 'disabled', 'bindings': {'object': 'a'}, 'guards': {'enabled': False}},
            {'id': 'enabled', 'bindings': {'object': 'a'}, 'guards': {'enabled': True}},
        ]},
        {'id': 'use', 'rows': [{'id': 'enabled', 'bindings': {'object': 'a'}, 'guards': {'enabled': True}}]},
    ])
    assert space.surviving[0] == ('unknown', 'enabled')
    assert space.plan_count == 2
    assert 'factory identity' in next(space.iter_plans()).as_dict()['unknown']


def test_global_three_cycle_survives_pair_support_but_has_no_plan():
    _, space = compare([
        {'id': 'first', 'rows': [{'id': 'a', 'bindings': {}, 'order': [['a', 'middle']]}]},
        {'id': 'second', 'rows': [{'id': 'b', 'bindings': {}, 'order': [['middle', 'b']]}]},
        {'id': 'third', 'rows': [{'id': 'c', 'bindings': {}, 'order': [['b', 'a']]}]},
    ])
    assert space.stats['surviving_rows'] == 3
    assert space.plan_count == 0


def test_future_boundary_keeps_order_through_forgotten_events():
    _, space = compare([
        {'id': 'first', 'rows': [
            {'id': 'cyclic', 'bindings': {'body': 'one'}, 'order': [['a', 'middle']]},
            {'id': 'possible', 'bindings': {'body': 'two'}, 'order': [['c', 'middle']]},
        ]},
        {'id': 'second', 'rows': [{'id': 'bridge', 'bindings': {}, 'order': [['middle', 'b']]}]},
        {'id': 'third', 'rows': [{'id': 'last', 'bindings': {}, 'order': [['b', 'a']]}]},
    ])
    assert space.stats['surviving_rows'] == 4
    assert [dict(p.choices)['first'] for p in space.iter_plans()] == ['possible']


def test_future_boundary_keeps_transitive_identity_and_disequality():
    _, space = compare([
        {'id': 'first', 'rows': [
            {'id': 'shared', 'bindings': {}, 'same': [['left', 'hidden']]},
            {'id': 'independent', 'bindings': {}},
        ]},
        {'id': 'second', 'rows': [{'id': 'bridge', 'bindings': {}, 'same': [['hidden', 'right']]}]},
        {'id': 'third', 'rows': [{'id': 'separate', 'bindings': {}, 'different': [['left', 'right']]}]},
    ])
    assert space.stats['surviving_rows'] == 4
    assert [dict(p.choices)['first'] for p in space.iter_plans()] == ['independent']


def test_forgotten_object_still_excludes_its_identity_from_future_role():
    _, space = compare([
        {'id': 'allocate', 'rows': [{'id': 'old', 'bindings': {'hidden': 'cell-1'}}]},
        {'id': 'distinct', 'rows': [{'id': 'new', 'bindings': {}, 'different': [['hidden', 'future']]}]},
        {'id': 'bind', 'rows': [
            {'id': 'same', 'bindings': {'future': 'cell-1'}},
            {'id': 'other', 'bindings': {'future': 'cell-2'}},
        ]},
    ])
    assert space.stats['surviving_rows'] == 4
    assert [dict(p.choices)['bind'] for p in space.iter_plans()] == ['other']


def test_hash_support_propagates_backwards_and_does_not_drop_unknown_row():
    _, space = compare([
        {'id': 'body', 'rows': [
            {'id': 'bad', 'bindings': {'input': 'a'}},
            {'id': 'good', 'bindings': {'input': 'b'}},
            {'id': 'unknown', 'bindings': {'input': None}},
        ]},
        {'id': 'constructor', 'rows': [
            {'id': 'bad', 'bindings': {'input': 'a', 'stage': 'prefix'}},
            {'id': 'good', 'bindings': {'input': 'b', 'stage': 'body'}},
        ]},
        {'id': 'observe', 'rows': [{'id': 'body', 'bindings': {'stage': 'body'}}]},
    ])
    assert space.surviving == (('good', 'unknown'), ('good',), ('body',))
    assert space.plan_count == 2


def test_dag_counts_all_independent_joint_assignments_without_expansion():
    relations = parse_relations([
        {'id': f'factor-{i}', 'rows': [
            {'id': 'zero', 'bindings': {f'position-{i}': 0}},
            {'id': 'one', 'bindings': {f'position-{i}': 1}},
        ]}
        for i in range(24)
    ])
    space = indexed_search(relations)
    assert space.plan_count == 2 ** 24
    assert space.stats['search_nodes'] == 24
    assert space.stats['search_row_checks'] == 48
    assert len(list(space.iter_plans(limit=5))) == 5
    assert list(space.iter_plans(limit=0)) == []


def test_small_seeded_constraint_domains_match_exhaustive_enumeration():
    rng = random.Random(98428)
    roles = ['a', 'b', 'c', 'hidden']
    events = ['start', 'call', 'middle', 'observe']
    for _ in range(100):
        relations = []
        for i in range(4):
            rows = []
            for j in range(3):
                rows.append({
                    'id': str(j),
                    'bindings': {r: rng.choice([None, 'x', 'y']) for r in rng.sample(roles, rng.randrange(3))},
                    'same': [rng.sample(roles, 2)] if rng.randrange(5) == 0 else [],
                    'different': [rng.sample(roles, 2)] if rng.randrange(5) == 0 else [],
                    'guards': {'path': rng.choice([None, True, False])} if rng.randrange(3) == 0 else {},
                    'order': [rng.sample(events, 2)] if rng.randrange(2) == 0 else [],
                })
            relations.append({'id': str(i), 'rows': rows})
        compare(relations)


def test_empty_domain_and_empty_problem_have_standard_join_semantics():
    _, no_plans = compare([{'id': 'missing', 'rows': []}])
    assert no_plans.plan_count == 0
    _, empty_plan = compare([])
    assert empty_plan.plan_count == 1


def test_schema_preserves_typed_values_and_rejects_ambiguous_recipe_identity():
    _, space = compare([
        {'id': 'a', 'rows': [{'id': 'boolean', 'bindings': {'value': True}}]},
        {'id': 'b', 'rows': [{'id': 'integer', 'bindings': {'value': 1}}]},
    ])
    assert space.plan_count == 0
    with pytest.raises(ValueError, match='Recipe IDs'):
        parse_relations([{'id': 'a', 'rows': [
            {'id': 'duplicate', 'bindings': {'x': 1}}, {'id': 'duplicate', 'bindings': {'x': 2}},
        ]}])
