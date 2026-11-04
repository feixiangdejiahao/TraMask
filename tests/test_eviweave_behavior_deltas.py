from eviweave.behavior import BehaviorIndex
from eviweave.behavior_deltas import BehaviorDeltaIndex
from eviweave.evidence import SourceGraph
from eviweave.port_admission import PortAdmissionIndex


def records(text):
    graph = SourceGraph({'id':'s','path':'test.py','raw':text.encode()})
    assert not graph.issues
    behavior = BehaviorIndex(graph)
    index = PortAdmissionIndex({'s':(graph,behavior)}, {'s':set(range(len(graph.nodes)))})
    keys = {k for k,o in index.operations.items() if o['kind']=='call' and o['name']=='send'}
    rows = index.view_features({'id':0,'source':'s','nodes':set(range(len(graph.nodes))),'anchors':keys})
    return BehaviorDeltaIndex(index), [r for r in rows if r['key'] in keys]


def test_local_differences_keep_numeric_order_and_concrete_parameter_changes():
    index, rows = records('send(1,10)\nsend(2,20)\nsend(11,10)\n')
    payload = index.difference(rows[0],rows[1])
    boundary = index.difference(rows[0],rows[2])
    assert payload['parameter_only']
    assert not boundary['parameter_only']
    assert payload['schema'] != boundary['schema']
    assert ('numeric_relation','positional:0','positional:1') in boundary['addresses']


def test_constructor_difference_is_bound_to_the_corresponding_port():
    index, rows = records('a=make(1)\nb=make(2)\nsend(a,b)\nc=make(1)\nd=make(3)\nsend(c,d)\n')
    result = index.difference(*rows)
    assert ('construction','positional:1') in result['addresses']
    assert ('construction','positional:0') not in result['addresses']
    edits = index.syntax_difference(rows[0]['key'],rows[1]['key'])
    changed = [r['role'] for r in edits if r['holes']]
    assert changed == ['positional:1']


def test_equal_literal_values_and_distinct_objects_are_separate_relations():
    index, rows = records('send({}, {})\nsend({"x":1}, {"x":1})\nsend({"x":1}, {"x":2})\n')
    facts = [index.facets(r) for r in rows]
    content = ('content_relation','positional:0','positional:1')
    identity = ('identity','positional:0','positional:1')
    assert facts[0][content] == facts[1][content]
    assert facts[1][content] != facts[2][content]
    assert facts[0][identity] == facts[1][identity]


def test_array_function_selector_does_not_become_a_payload_parameter():
    index, rows = records('fns=[first,second]\na=fns[0]\nb=fns[1]\nsend(a)\nsend(b)\n')
    result = index.difference(*rows)
    assert ('construction','positional:0') in result['addresses']
    assert not result['parameter_only']


def test_transfer_bundle_keeps_two_coordinated_replacements():
    index, rows = records('send(1,1)\nsend(2,2)\nsend(2,3)\n')
    same = index.difference(rows[0],rows[1])
    distinct = index.difference(rows[0],rows[2])
    assert ('port','positional:0') in same['addresses']
    assert ('port','positional:1') in same['addresses']
    assert same['schema'] != distinct['schema']


def test_output_consumer_is_a_difference_instead_of_a_new_admission_rule():
    index, rows = records('a=send(1)\nobserve(a)\nb=send(1)\nconsume(b)\n')
    result = index.difference(*rows)
    addresses = result['addresses']
    assert ('connection','outputs','positional:0','call','observe') in addresses
    assert ('connection','outputs','positional:0','call','consume') in addresses


def test_nested_consumer_traces_the_construction_of_its_receiver():
    index, rows = records('r=Response(content=body)\nsend(r.parse())\ns=Response(stream=chunks)\nsend(s.parse())\n')
    result = index.difference(*rows)
    assert ('construction','positional:0') in result['addresses']


def test_minimal_edit_schema_shares_closed_values_but_keeps_their_bindings():
    index, rows = records('send(True,True)\nsend({"x":1},{"x":1})\nsend({"a":False,"b":2},{"a":False,"b":2})\nsend({"x":1},{"x":2})\n')
    first = index.edit_schema(rows[0]['key'],rows[1]['key'])
    second = index.edit_schema(rows[0]['key'],rows[2]['key'])
    unequal = index.edit_schema(rows[0]['key'],rows[3]['key'])
    assert first['schema'] == second['schema']
    assert first['schema'] != unequal['schema']
    assert len(first['fresh_value_occurrences']) == 2
    assert first['bindings'] != second['bindings']


def test_identical_calls_do_not_prove_equal_content_of_their_results():
    index, rows = records('send(make(),make())\n')
    assert ('content_relation','positional:0','positional:1') not in index.facets(rows[0])


def test_same_lexical_cell_is_kept_separate_from_equal_constructions():
    index, rows = records('a=make()\nb=make()\nsend(a,a)\nsend(a,b)\n')
    assert ('lexical_topology',) in index.difference(*rows)['addresses']


def test_edit_schema_keeps_function_selection_indices_concrete():
    index,rows=records('send(fns[0])\nsend(fns[1])\nsend(fns[2])\n')
    one=index.edit_schema(rows[0]['key'],rows[1]['key'])
    two=index.edit_schema(rows[0]['key'],rows[2]['key'])
    assert one['schema'] != two['schema']


def test_callee_spelling_is_not_a_closed_payload_parameter():
    index,rows=records('send(first(1))\nsend(second(1))\nsend(third(1))\n')
    one=index.edit_schema(rows[0]['key'],rows[1]['key'])
    two=index.edit_schema(rows[0]['key'],rows[2]['key'])
    assert one['schema'] != two['schema']
