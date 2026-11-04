from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph
from eviweave.relational_alignment import RelationalAlignmentIndex


def index_of(left, right, path='test.py'):
    sources = {}
    for name, text in [('a', left), ('b', right)]:
        graph = SourceGraph({'id': name, 'path': path, 'raw': text.encode()})
        assert not graph.issues
        sources[name] = graph, BehaviorIndex(graph)
    selected = {name: set(range(len(graph.nodes))) for name, (graph, _) in sources.items()}
    return RelationalAlignmentIndex(sources, selected)


def align(index, name):
    keys = [next(key for key, op in index.operations.items() if key[0] == source and op['name'] == name)
            for source in ('a', 'b')]
    return index.align(*keys)


def kinds(result):
    return {d['kind'] for d in result['delta']}


def test_renaming_is_not_a_relation_edit():
    index = index_of('x=[]\nif x:\n use(x)\nassert x==[]\n',
                     'y=[]\nif y:\n use(y)\nassert y==[]\n')
    assert align(index, 'use')['delta'] == []


def test_equal_path_shapes_retain_identity_difference():
    index = index_of('a=[]\nuse(a,a)\n', 'b=[]\nc=[]\nuse(b,c)\n')
    result = align(index, 'use')
    assert result['footprint_equal']
    assert 'identity' in kinds(result)


def test_guard_negation_and_guard_binding_are_differences():
    index = index_of('def f(x):\n if x:\n  use(x)\n',
                     'def f(x):\n if not x:\n  use(x)\n')
    assert 'condition' in kinds(align(index, 'use'))
    index = index_of('def f(x,y):\n if x:\n  use(x)\n',
                     'def f(x,y):\n if y:\n  use(x)\n')
    assert 'binding_topology' in kinds(align(index, 'use'))


def test_setup_and_option_differences_coexist():
    index = index_of('c=Container()\nc.register(a=make(),b=make(),d=make())\nc.initialize(limit=2)\n',
                     'c=Container()\nc.register(a=make(),b=make())\nc.initialize()\n')
    result = align(index, 'initialize')
    assert result['removed_ports'] == ['keyword:limit']
    assert 'related_operation' in kinds(result)


def test_observation_is_conditional_and_has_its_source():
    index = index_of('x=[]\nif ready:\n use(x)\nelse:\n assert not x\n',
                     'y=[]\nuse(y)\nassert not y\n')
    result = align(index, 'use')
    assert {'condition', 'observation'} <= kinds(result)
    key = tuple(result['left'])
    observation = next(n for n in index.profile(key)['neighbors'] if n['observation'])
    assert observation['guards'][0]['polarity'] is False


def test_factored_count_equals_explicit_occurrence_pairs():
    index = index_of('use(1)\nuse(2)\n', 'use(1)\nuse(1)\n')
    anchors = set(index.operations)
    groups, domains = index.grouped_domains(anchors)
    actual = [index.align(a,b) for a in anchors for b in anchors if a != b]
    assert sum(d['occurrence_pairs'] for d in domains) == len(actual)
    assert sum(d['changed_occurrence_pairs'] for d in domains) == sum(bool(a['delta']) for a in actual)
    assert sum(len(g['members']) for g in groups) == len(anchors)


def test_visible_member_write_is_a_state_delta():
    index=index_of('obj=Box()\nobj.enabled=True\nuse(obj)\n',
                   'box=Box()\nbox.enabled=False\nuse(box)\n')
    assert 'state' in kinds(align(index,'use'))


def test_a_relation_outside_the_view_is_not_an_edit_of_this_view():
    index=index_of('obj=Box()\nuse(obj)\nobj.enabled=True\n',
                   'box=Box()\nuse(box)\nbox.enabled=False\n')
    keys=[next(k for k,o in index.operations.items() if k[0]==s and o['name']=='use') for s in ('a','b')]
    assert 'state' in kinds(index.align(*keys))
    projected=[index.profile(key,nodes={0,1}) for key in keys]
    assert projected[0]['components']==projected[1]['components']


def test_view_pair_count_agrees_with_explicit_pairs_on_parsed_graphs():
    from scripts.pilot_view_port_relations import count_pairs
    index=index_of('use(1)\nuse(2)\n', 'use(1)\nuse(1)\n')
    views=[]
    for s in ('a','b'):
        for n in (0,1):
            views.append({'id':len(views),'source':s,'nodes':{n},'anchors':set(index.by_statement[s,n])})
    groups,domains=index.grouped_view_domains(views)
    explicit=set()
    for v in views:
        left=next(iter(v['anchors']))
        for w in views:
            if v['id']==w['id']:continue
            right=next(iter(w['anchors']))
            if index.profile(left,nodes=v['nodes'])['components']!=index.profile(right,nodes=w['nodes'])['components']:
                explicit.add((v['id'],w['id']))
    assert count_pairs(groups,domains)==len(explicit)==6
