from eviweave.anchors import parse_source
from eviweave.pre_slice_queries import public_rules, role_points, frequent_seed_filter, authored_anchors


def source(code):
    raw = code.encode()
    return {'id': 'one', 'path': 'test_api.py', 'kind': 'historical_write', 'raw': raw,
            'parsed': parse_source('test_api.py', raw)}


def test_role_queries_do_not_promote_plain_local_variable_words():
    item = source('def check():\n    state = 1\n    print(state)\n    return client.state\n')
    rules = {'calls': set(), 'fields': {'state'}, 'tokens': set()}
    points = role_points([item], rules, precise=True)
    spans = {tuple(p[2:]) for values in points.values() for p in values}
    assert {item['raw'][a:b] for a, b in spans} == {b'client.state'}


def test_precise_input_uses_call_syntax_without_dropping_the_program():
    item = source('record("parse")\nrecord("parse(1)")\n')
    rules = {'calls': {'parse'}, 'fields': set(), 'tokens': set()}
    broad = role_points([item], rules, precise=False)
    narrow = role_points([item], rules, precise=True)
    assert len(broad) == 2 and len(narrow) == 1
    assert [item['raw'][p[2]:p[3]] for values in narrow.values() for p in values] == [b'"parse(1)"']


def test_owner_family_is_an_independent_query_expansion():
    code = 'class Client:\n    def send(self): return 1\n    def receive(self): return 2\n'
    item = source(code)
    final = [('api.py', item['raw'], item['parsed'])]
    changes = {'api.py': {2}}
    direct = public_rules('', changes, final, [item], family=False)
    family = public_rules('', changes, final, [item], family=True)
    assert 'send' in direct['calls'] and 'receive' not in direct['calls']
    assert 'receive' in family['calls']


def test_frequency_pruning_protects_explicit_targets():
    points = {('one', i, i + 1): [('calls', 'explicit', i, i + 1), ('members', 'weak', i, i + 1)]
              for i in range(4)}
    kept, names, counts = frequent_seed_filter(points, {'explicit'}, 2)
    assert counts == {'explicit': 4, 'weak': 4}
    assert names == {'explicit'}
    assert all(all(point[1] == 'explicit' for point in values) for values in kept.values())


def test_authored_channel_preserves_versions_and_edit_scripts():
    original = source('def check():\n    assert run("first") == 1\n')
    revised = source('def check():\n    assert run("second") == 2\n')
    revised['id'] = 'revision'
    editor = source('s = s.replace("old", "new")\n')
    editor.update(id='editor', kind='inline_script')
    existing = source('def test_other():\n    pass\n')
    existing.update(id='existing', kind='final_workspace')
    kept = authored_anchors([original, revised, editor, existing])
    assert {key[0] for key in kept} == {'one', 'revision', 'editor'}
    assert all(anchors == {(a, b)} for (_, a, b), anchors in kept.items())
