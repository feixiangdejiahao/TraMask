"""Value recipes preserve destination keys, values and independent allocations."""
import json
import subprocess
import sys

import pytest

from eviweave.alignment import RegionAlignmentIndex
from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph
from eviweave.value_recipes import value_candidates


def index(sources):
    built = {}
    for source, (path, text) in sources.items():
        graph = SourceGraph({'id': source, 'path': path, 'raw': text.encode()})
        assert not graph.issues
        built[source] = graph, BehaviorIndex(graph)
    return RegionAlignmentIndex(built)


def candidates(alignment, source, text):
    raw = alignment.sources[source][0].raw
    start = raw.index(text.encode())
    return value_candidates(alignment, source, alignment.select(source, start, start + len(text.encode())))


def replacement(alignment, row):
    return alignment.sources[row['source']][0].raw[slice(*row['replacement_range'])].decode()


def test_typescript_field_key_stays_outside_the_value_replacement():
    alignment = index({'s': ('test.ts', 'const base={a:true}; const donor={other:{x:1,y:2}};')})
    rows = candidates(alignment, 's', 'a:true')
    row = next(row for row in rows if replacement(alignment, row) == '{x:1,y:2}')
    raw = alignment.sources['s'][0].raw
    start, end = row['destination_range']
    assert raw[start:end] == b'true'
    assert row['key_preserved'] is True
    assert raw[:start] + replacement(alignment, row).encode() + raw[end:] == b'const base={a:{x:1,y:2}}; const donor={other:{x:1,y:2}};'
    assert row['fresh_allocation_count'] == 1
    assert 'field_spelling_does_not_establish_semantic_role' in row['unknowns']


def test_equal_closed_literals_merge_all_provenance_but_keep_different_values():
    alignment = index({'base': ('base.ts', 'const base={value:true};'),
                       'one': ('one.ts', 'const donor={p:{x:1,y:2}, q:{x:1,y:3}};'),
                       'two': ('two.ts', 'const donor={q:{ x: 1, y: 2 }};')})
    rows = candidates(alignment, 'base', 'value:true')
    first = next(row for row in rows if replacement(alignment, row) == '{x:1,y:2}')
    second = next(row for row in rows if replacement(alignment, row) == '{x:1,y:3}')
    assert {origin['key'][0] for origin in first['origins']} == {'one', 'two'}
    assert first['origin_occurrence_count'] == 2
    assert first['term_key'] != second['term_key']
    assert first['shape'] == second['shape']


def test_categories_rotate_after_duplicate_primitive_values_are_grouped():
    alignment = index({'s': ('test.ts', 'const base={value:true}; const data={' +
                       ','.join(f'k{i}:true' for i in range(30)) +
                       ',changed:false,record:{x:1,y:2},items:[1,2]};')})
    rows = candidates(alignment, 's', 'value:true')
    assert [row['category'] for row in rows[:3]] == ['primitive', 'object', 'sequence']
    repeated = [row for row in rows if replacement(alignment, row) == 'true']
    assert len(repeated) == 1
    assert repeated[0]['origin_occurrence_count'] == 30
    assert repeated[0]['changes_value'] is False
    assert rows[0]['changes_value'] is True


def test_open_literals_stay_separate_and_retain_their_unresolved_bindings():
    alignment = index({'s': ('test.ts', 'const base={value:true}; const a={x:outside}; '
                       'const b={x:outside}; const c={x:load()}; const d={[field]:1}; '
                       'const e={x:obj.value};')})
    rows = candidates(alignment, 's', 'value:true')
    open_objects = [row for row in rows if replacement(alignment, row) == '{x:outside}']
    assert len(open_objects) == 2
    assert all(not row['closed'] and row['free_bindings'] == ['outside'] for row in open_objects)
    assert all(row['origin_occurrence_count'] == 1 for row in open_objects)
    assert 'call_in_value' in next(row for row in rows if replacement(alignment, row) == '{x:load()}')['unknowns']
    assert 'dynamic_key_or_index' in next(row for row in rows if replacement(alignment, row) == '{[field]:1}')['unknowns']
    assert 'dynamic_attribute_access' in next(row for row in rows if replacement(alignment, row) == '{x:obj.value}')['unknowns']
    assert all(row['fresh_allocation_count'] is None for row in open_objects)
    assert rows[-1]['category'] == 'expression'


def test_python_repeated_application_allocates_two_objects_after_source_grouping():
    alignment = index({'s': ('test.py', "base={'left': True, 'right': True}\ndonor={'x': 1, 'y': 2}\n")})
    rows = candidates(alignment, 's', "'left': True")
    row = next(row for row in rows if replacement(alignment, row) == "{'x': 1, 'y': 2}")
    value = replacement(alignment, row)
    code = f"left={value}\nright={value}\nleft['x']=9\nassert left is not right\nassert right['x']==1\n"
    subprocess.run([sys.executable, '-c', code], capture_output=True, check=True)
    assert row['fresh_allocation_count'] == 1
    assert row['instantiation'] == 'evaluate_literal_separately_at_each_destination'


def test_nested_fresh_allocations_are_not_deduplicated_inside_a_recipe():
    alignment = index({'s': ('test.py', "base={'value': False}\none=[{}]\ntwo=[{}, {}]\n")})
    rows = candidates(alignment, 's', "'value': False")
    one = next(row for row in rows if replacement(alignment, row) == '[{}]')
    two = next(row for row in rows if replacement(alignment, row) == '[{}, {}]')
    assert one['term_key'] != two['term_key']
    assert [one['fresh_allocation_count'], two['fresh_allocation_count']] == [2, 3]


def test_json_material_changes_record_value_without_copying_the_donor_key():
    base = '{"target/2.js":{"duration":300}}'
    donor = '{"donor/b.ts":{"observations":[{"duration":102,"recordedAt":123}]}}'
    json.loads(base)
    json.loads(donor)
    alignment = index({'base': ('material.ts', '(' + base + ')'),
                       'donor': ('material.ts', '(' + donor + ')')})
    rows = candidates(alignment, 'base', '"target/2.js":{"duration":300}')
    row = next(row for row in rows if replacement(alignment, row) == '{"observations":[{"duration":102,"recordedAt":123}]}')
    raw = alignment.sources['base'][0].raw
    start, end = row['destination_range']
    changed = raw[:start] + replacement(alignment, row).encode() + raw[end:]
    parsed = json.loads(changed.decode()[1:-1])
    assert list(parsed) == ['target/2.js']
    assert parsed['target/2.js']['observations'][0]['duration'] == 102


def test_complete_value_selection_and_embedded_json_keep_source_coordinates():
    text = "base={'value': True}\npayload='{\"record\": {\"x\": 1}}'\n"
    alignment = index({'s': ('test.py', text)})
    rows = candidates(alignment, 's', 'True')
    row = next(row for row in rows if replacement(alignment, row) == '{"x": 1}')
    assert row['syntax_language'] == 'json'
    assert row['closed'] is True
    assert 'embedded_literal_source_encoding_not_validated' in row['unknowns']
    assert json.loads(json.dumps(row))['key_preserved'] is True


def test_python_variable_dictionary_key_is_not_a_closed_literal():
    alignment = index({'s': ('test.py', "base={'value': True}\ndonor={name: 1}\n")})
    row = next(row for row in candidates(alignment, 's', "'value': True")
               if replacement(alignment, row) == '{name: 1}')
    assert row['closed'] is False
    assert row['free_bindings'] == ['name']


def test_unrelated_selection_is_an_explicit_domain_error():
    alignment = index({'s': ('test.py', 'consume(1)\n')})
    with pytest.raises(ValueError, match='not a field'):
        candidates(alignment, 's', 'consume(1)')
