import copy

from relation_search.checkpoint import write
from scripts.analyze_relation_campaign_reachability import MaterialIdentity, classify_loss, round_index


def example():
    code = 'def test_size():\n    xs = [1]\n    assert len(xs) == 1\n'
    path = 'test_size.py'
    corpus = dict(sources={path: dict(code=code)}, tests={'base': dict(span=dict(
        path=path, start_byte=0, end_byte=len(code)))})
    at = code.index('[1]')
    candidate = dict(id='old_id', base_test_id='base', imports=[], edits=[dict(
        span=dict(path=path, start_byte=at, end_byte=at+3), before='[1]', after='[1, 2]')])
    return code, corpus, candidate


def test_content_matching_ignores_ids_but_distinguishes_input_and_assertion():
    code, corpus, parent = example()
    identity = MaterialIdentity(corpus)
    same = {**copy.deepcopy(parent), 'id': 'different_id'}
    assert identity.signature(same) == identity.signature(parent)
    wrong = copy.deepcopy(parent)
    wrong['edits'][0]['after'] = '[1, 3]'
    assert identity.signature(wrong) != identity.signature(parent)
    revised = copy.deepcopy(parent)
    revised['edits'].append(dict(role='semantic_expected', before='1', after='2',
        span=dict(path='test_size.py', start_byte=code.rindex('1'), end_byte=code.rindex('1')+1)))
    assert identity.signature(revised) == identity.signature(parent)
    assert identity.signature(revised, True) != identity.signature(parent, True)
    with_probe = copy.deepcopy(revised)
    with_probe['edits'].append(dict(role='relation_runtime_probe', before='', after='pass\n',
        span=dict(path='test_size.py', start_byte=0, end_byte=0)))
    assert identity.signature(with_probe, True) == identity.signature(revised, True)


def test_equivalent_edit_segmentation_matches_and_source_helper_change_does_not():
    _, corpus, candidate = example()
    identity = MaterialIdentity(corpus)
    equivalent = copy.deepcopy(candidate)
    edit = equivalent['edits'][0]
    edit['span']['start_byte'] += 2
    edit['span']['end_byte'] = edit['span']['start_byte']
    edit.update(before='', after=', 2')
    assert identity.signature(equivalent) == identity.signature(candidate)
    changed = copy.deepcopy(corpus)
    changed['sources']['test_size.py']['code'] += '\nhelper = 2\n'
    assert MaterialIdentity(changed).signature(candidate) != identity.signature(candidate)


def test_pending_case_is_never_classified_as_lost():
    stages = {name: [] for name in ['source_pool', 'selected', 'semantic_input',
                                  'semantic_complete', 'emitted_complete', 'executed_complete']}
    assert classify_loss(stages, complete=False)[0] is None
    assert classify_loss(stages, complete=True)[0] == 'source_pool'
    stages['source_pool'] = [dict(id='anything')]
    assert classify_loss(stages, complete=True)[0] == 'selected'


def test_runs_index_requires_real_named_pass_or_fail_to_count_execution(tmp_path):
    _, corpus, candidate = example()
    identity = MaterialIdentity(corpus)
    round_folder = tmp_path/'round_000'
    write(round_folder/'emitted/accepted.json', [candidate])
    write(round_folder/'emitted/group_000/emission.json', dict(obligations=[], unsupported=[]))
    write(round_folder/'emitted/group_000/manifest.json', dict(obligations=[dict(candidate_id=candidate['id'])]))
    result = round_folder/'executed/group_000/generated/normalized.json'
    run = dict(role='generated', candidate_id=candidate['id'], result=str(result), test_ids=['test_gc_old_id'])
    write(round_folder/'executed/runs.json', [run])
    for tests in [[], [dict(id='test_gc_unrelated', status='fail')],
                  [dict(id='test_gc_old_id', status='skip')], [dict(id='test_gc_old_id', status='error')]]:
        write(result, dict(tests=tests))
        measured = round_index(round_folder, identity)
        assert measured['index']['emitted_complete'][identity.signature(candidate, True)]
        assert not measured['index']['executed_complete']
        assert measured['indexed_runs'][0]['actual_execution'] is False
    write(result, dict(tests=[dict(id='file::test_gc_old_id[param]', status='fail')]))
    measured = round_index(round_folder, identity)
    assert measured['index']['executed_complete'][identity.signature(candidate, True)]
