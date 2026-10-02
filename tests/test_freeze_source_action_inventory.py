"""Inventory source selection must be deterministic and independent of labels."""
from scripts.freeze_source_action_inventory import source_groups


def row(key, corpus='corpus', label='unused'):
    return dict(case=key.split(':')[0], key=key, round=int(key.split(':')[1]),
                inputs=dict(corpus=dict(path=corpus, sha256='c'),
                            frontend=dict(path='frontend', sha256='f'), runs=dict(path='forbidden')),
                classification=label, native_evidence='forbidden')


def test_order_and_projection_exclude_outcomes_and_labels():
    records = [row('B:1:c'), row('A:1:z'), row('A:0:x')]
    groups = source_groups(records)
    assert list(groups) == ['A', 'B']
    assert groups['A'][0]['key'] == 'A:0:x'
    assert source_groups(list(reversed(records))) == groups
    assert all(set(item) == {'case', 'key', 'round', 'inputs'}
               and set(item['inputs']) == {'corpus', 'frontend'}
               for items in groups.values() for item in items)
    records[0]['classification'] = 'valid'
    records[1]['native_evidence'] = 'changed runtime outcome'
    assert source_groups(records) == groups


def test_source_path_breaks_ties_without_label_input():
    groups = source_groups([row('A:0:x', 'z', 'positive'), row('A:0:x', 'a', 'negative')])
    assert groups['A'][0]['inputs']['corpus']['path'] == 'a'
