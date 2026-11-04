from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph
from eviweave.port_admission import PortAdmissionIndex, admission_groups
from eviweave.relations import RelationIndex


def build(text, path='test.py'):
    graph = SourceGraph({'id': 's', 'path': path, 'raw': text.encode()})
    assert not graph.issues
    behavior = BehaviorIndex(graph)
    index = PortAdmissionIndex({'s': (graph, behavior)}, {'s': set(range(len(graph.nodes)))})
    return graph, behavior, index


def test_constructor_arguments_are_dependencies_without_becoming_aliases():
    _, behavior, index = build('schema={"field": 1}\nentity=Entity(schema)\nuse(entity)\n')
    root = next(k for k, op in index.operations.items() if op['name'] == 'use')
    definitions, _ = index.construction(root)
    assert {index.definitions[d]['binding'][1] for d in definitions} == {'schema', 'entity'}
    ids = {d['binding'][1]: d['value_identity'] for d in behavior.definitions}
    assert ids['schema'] != ids['entity']


def test_nested_sql_result_keeps_its_consumer_and_argument_role():
    _, _, index = build('ntile(sql.lit(1))\npercentile(sql.lit(0.5))\n')
    roots = [k for k, op in index.operations.items() if op['kind'] == 'call' and op['name'] == 'lit']
    features = [index.feature(k) for k in roots]
    assert {index.descriptor(other)[1] for _, other in features[0]['outputs']} == {'ntile'}
    assert {index.descriptor(other)[1] for _, other in features[1]['outputs']} == {'percentile'}


def test_same_cast_to_different_fields_has_no_common_port_witness():
    graph, _, index = build('package p\nfunc f(){a:=Entry{Dev:uint32(39),Inode:uint32(140626)};use(a)}\n', 'test.go')
    roots = {k for k, op in index.operations.items() if op['name'] == 'uint32'}
    # Individual statement views still retain the distinct field endpoint.
    record = index.view_features({'id': 0, 'source': 's', 'nodes': set(range(len(graph.nodes))), 'anchors': roots})
    casts = [r for r in record if r['key'] in roots]
    assert {r['field'] for r in casts} == {'Dev', 'Inode'}
    # Retain the common consumer while qualifying it by the differing fields.
    assert all(r['roles'] for r in casts)
    assert not (casts[0]['roles'] & casts[1]['roles'])


def test_captured_schema_has_a_may_dependency_not_an_execution_claim():
    graph, behavior, index = build('schema={"field": 1}\ndef f():\n entity=Entity(schema)\n use(entity)\nf()\n')
    root = next(k for k, op in index.operations.items() if op['name'] == 'use')
    definitions, _ = index.construction(root)
    assert 'schema' in {index.definitions[d]['binding'][1] for d in definitions}
    relations = RelationIndex(graph, behavior)
    assert any(e['kind'] == 'construction_input' and e['certainty'] == 'may_lexical_definition' for e in relations.edges)


def test_equal_name_with_only_unrelated_literals_does_not_supply_a_witness():
    graph, _, index = build('send(1)\nsend(2)\n')
    roots = set(index.operations)
    records = index.view_features({'id': 0, 'source': 's', 'nodes': set(range(len(graph.nodes))), 'anchors': roots})
    assert not any(r['roles'] for r in records)
    _, domains = admission_groups(records, 'edge')
    assert not domains


def test_numeric_template_keeps_relative_boundary_instead_of_erasing_values():
    _, _, index = build('use(1,10)\nuse(2,20)\nuse(11,10)\n')
    keys = [k for k, o in index.operations.items() if o['name'] == 'use']
    features = [index.feature(k) for k in keys]
    assert features[0]['template'] == features[1]['template']
    assert features[0]['template'] != features[2]['template']
    assert features[2]['value_relations'] == [('positional:0', 'positional:1', 'greater')]


def test_selecting_different_functions_is_not_a_numeric_payload_change():
    _, _, index = build('fns=[first,second]\na=fns[0]\nb=fns[1]\na.Call()\nb.Call()\n')
    keys = [k for k, o in index.operations.items() if o['kind'] == 'call' and o['name'] == 'Call']
    assert index.feature(keys[0])['template'] != index.feature(keys[1])['template']


def test_direct_literals_are_distinct_allocations_and_callee_seed_is_retained():
    graph, _, index = build('obj=Thing()\nobj.send({}, {})\n')
    member = next(k for k in index.aliases if index.operations[k]['name'] == 'send')
    call = index.aliases[member]
    assert ('positional:0', 'positional:1', 'distinct_allocations') in index.feature(call)['identity_relations']
    rows = index.view_features({'id': 0, 'source': 's', 'nodes': set(range(len(graph.nodes))), 'anchors': {member}})
    assert next(r for r in rows if r['key'] == call)['anchor']


def test_guard_values_join_the_same_construction_dependency_graph():
    _, _, index = build('flag=configure(True)\nif flag:\n use(1)\n')
    root = next(k for k, o in index.operations.items() if o['name'] == 'use')
    _, producers = index.construction(root)
    assert 'configure' in {index.operations[k]['name'] for k in producers}


def test_shared_consumer_exposes_relative_receiver_state_phase():
    _, _, index = build('''def before():
 world=World()
 removed=factory()
 world.spawn()
 world.query(removed)
def after():
 world=World()
 world.spawn()
 removed=factory()
 world.query(removed)
''')
    keys = [k for k, o in index.operations.items() if o['name'] == 'factory']
    a, b = [index.feature(k) for k in keys]
    assert a['exact'] != b['exact']
    phases = [{row[2] for row in r['consumer_state'] if index.operations[row[1]]['name'] == 'spawn'} for r in [a, b]]
    assert phases == [{'after_root'}, {'before_root'}]


def test_same_imported_callable_does_not_connect_independent_input_values():
    _, _, index = build('from pkg import make\na=make(1)\nuse(a)\nb=make(2)\nother(b)\n')
    a = next(k for k, o in index.operations.items() if o['name'] == 'use')
    b = next(k for k, o in index.operations.items() if o['name'] == 'other')
    assert index.flow_components[a] != index.flow_components[b]


def test_multiple_call_results_keep_consumers_without_inventing_aliases():
    _, behavior, index = build('package p\nfunc f(){ db,err:=Open(); if err!=nil{return}; db.Close() }\n', 'test.go')
    root = next(k for k, o in index.operations.items() if o['kind'] == 'call' and o['name'] == 'Open')
    definitions = index.operations[root]['result']['definitions']
    assert {index.definitions['s', d]['binding'][1] for d in definitions} == {'db', 'err'}
    assert all(index.definitions['s', d]['value_identity'] is None for d in definitions)
    assert 'Close' in {index.operations[k]['name'] for _, k in index.feature(root)['outputs']}


def test_go_octal_modes_use_their_numeric_value_in_relations():
    _, _, index = build('package p\nfunc f(){use(0755,500)}\n', 'test.go')
    root = next(k for k, o in index.operations.items() if o['name'] == 'use')
    assert index.feature(root)['value_relations'] == [('positional:0', 'positional:1', 'less')]
