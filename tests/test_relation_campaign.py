"""Exercise the campaign coordinator through real isolated local pytest phases.

The only substituted behavior is Docker transport.  Candidate construction,
semantic cache lookup, materialization, phase runner, reports, runtime feedback,
and immutable resume receipts all execute their production implementations.
"""
from types import SimpleNamespace

import pytest

from relation_search.checkpoint import read, write
from scripts.run_relation_campaign import campaign
from test_relation_search_loop import local_transport, prepared


def arguments(tmp_path, mode):
    source, repository, registry = prepared(tmp_path)
    sources = tmp_path / 'sources'
    sources.mkdir()
    (sources / 'toy').symlink_to(source, target_is_directory=True)
    cache = tmp_path / 'semantic_cache.json'
    write(cache, dict(mode='historical_local_oracle_replay', records=[], entries=[]))
    args = SimpleNamespace(
        source=sources, output=tmp_path / 'campaign', cases=['toy'],
        rounds=2, limit=1, pool=16, max_edits=4, strategy='profile',
        workers=1, group_size=4, timeout=15, include_baseline=True,
        oracle_mode=mode, oracle_cache=cache if mode == 'replay' else None,
        semantic_budget=2, per_request=1, model_workers=1,
        registry=registry, dependency_packages_root=source,
    )
    return args, repository


@pytest.mark.parametrize('mode', ['none', 'replay'])
def test_two_real_rounds_source_before_generated_and_idempotent_resume(tmp_path, monkeypatch, mode):
    args, repository = arguments(tmp_path, mode)
    calls = local_transport(monkeypatch, tmp_path, repository)
    result = campaign(args)
    assert result['cases'] == 1
    assert len(calls) == 2
    records = read(args.output / 'campaign.json')
    assert len(records) == 1
    assert records[0]['case'] == 'toy'
    rounds = records[0]['rounds']
    assert [row['round'] for row in rounds] == [0, 1]
    root = args.output / 'toy'
    first = read(root / 'round_000/feedback.json')
    second = read(root / 'round_001/feedback.json')
    chosen = read(root / 'round_001/semantic/candidates.json')['candidates'][0]
    assert chosen['kind'] == 'executed_parent_extension'
    assert chosen['runtime_parent_id'] == 'alias'
    assert first['eligible_parents'][0]['feedback']['profile_baseline_measured']
    assert {'alias', chosen['id']} <= set(second['executed_candidate_ids'])
    assert all(row['counters']['executed_test_outcomes'] == 3 for row in second['rounds'])
    assert all(row['new_generated_profiles'] == 1 for row in second['rounds'])
    for index in range(2):
        folder = root / f'round_{index:03d}'
        phases = read(folder / 'executed/group_000/phases.json')
        assert [row['role'] for row in phases] == ['control', 'source_profile', 'generated']
        assert (folder / 'executed/group_000/source_profile/relation_trace.jsonl').is_file()
        semantic = read(folder / 'semantic/semantic_result.json')
        assert semantic['mode'] == mode
        assert semantic['provider_calls'] == 0
        assert semantic['revised_count'] == 0
        assert read(folder / 'semantic/prepare.json')['source_identity'] == first['source_identity']
        if mode == 'replay':
            replay = read(folder / 'semantic/semantic_replay.json')
            assert replay['counts'] == dict(originals=1, replayed=0, provider_calls=0,
                                           correctness_filtering=False)
    assert campaign(args) == result
    assert len(calls) == 2, 'Resuming completed phases must not execute tests again'


def test_changed_campaign_options_are_rejected_before_execution(tmp_path, monkeypatch):
    args, repository = arguments(tmp_path, 'none')
    calls = local_transport(monkeypatch, tmp_path, repository)
    campaign(args)
    args.limit += 1
    with pytest.raises(ValueError, match='Resume inputs or algorithm changed'):
        campaign(args)
    assert len(calls) == 2


def test_changed_cache_is_rejected_before_replay_or_execution(tmp_path, monkeypatch):
    args, repository = arguments(tmp_path, 'replay')
    calls = local_transport(monkeypatch, tmp_path, repository)
    campaign(args)
    cache = read(args.oracle_cache)
    cache['records'].append(dict(status='tampered'))
    write(args.oracle_cache, cache)
    with pytest.raises(ValueError, match='Resume inputs or algorithm changed'):
        campaign(args)
    assert len(calls) == 2


def test_changed_semantic_candidates_are_rejected_before_execution(tmp_path, monkeypatch):
    args, repository = arguments(tmp_path, 'none')
    calls = local_transport(monkeypatch, tmp_path, repository)
    campaign(args)
    candidates = args.output / 'toy/round_000/semantic/candidates.json'
    changed = read(candidates)
    changed['candidates'][0]['edits'][0]['after'] = 'None'
    write(candidates, changed)
    with pytest.raises(ValueError, match='Frozen semantic artifact changed'):
        campaign(args)
    assert len(calls) == 2


def test_replayed_assertion_revision_runs_beside_original_without_changing_inputs(tmp_path, monkeypatch):
    from relation_search.oracle import prepare_requests, validate
    from relation_search.semantic_cache import program_key
    from test_relation_oracle import setup

    args, repository = arguments(tmp_path, 'replay')
    args.rounds = 1
    source = args.source / 'toy'
    corpus, front, candidate = setup()
    candidate.update(kind='a_length', language='python')
    issue = 'Count the items.'
    for name, value in [('corpus.json', corpus), ('frontend.json', front),
                        ('candidates.json', dict(candidates=[candidate]))]:
        write(source / name, value)
    (source / 'issue.md').write_text(issue)
    for path, metadata in corpus['sources'].items():
        (repository / path).write_text(metadata['code'])
    request = prepare_requests(corpus, front, [candidate], issue)[0]
    revision = validate(request, {'revisions': [dict(
        candidate='C0', basis='The supplied list contains two items.',
        updates=[dict(assertion='A0', code='assert result == 2')],
    )]}, corpus)['revisions'][0]
    write(args.oracle_cache, dict(records=[], entries=[dict(
        program_key=program_key(corpus, candidate, issue), candidate=revision,
        request='local_validated_request', completion='local_validated_completion',
    )]))
    calls = local_transport(monkeypatch, tmp_path, repository)
    campaign(args)
    assert len(calls) == 2  # Program and oracle candidates retain distinct lanes.
    folder = args.output / 'toy/round_000'
    semantic = read(folder / 'semantic/semantic_result.json')
    assert semantic['revised_count'] == 1
    assert semantic['provider_calls'] == 0
    batch = read(folder / 'semantic/candidates.json')['candidates']
    assert [row['id'] for row in batch] == [candidate['id'], revision['id']]
    assert batch[0]['edits'] == candidate['edits']
    assert batch[1]['edits'][0] == candidate['edits'][0]
    assert batch[1]['edits'][1]['role'] == 'semantic_expected'
    outcomes = []
    for group in ['group_000', 'group_001']:
        executed = folder / 'executed' / group
        phases = read(executed / 'phases.json')
        assert [row['role'] for row in phases] == ['control', 'generated']
        assert read(executed / 'control/normalized.json')['counts']['pass'] == 1
        outcomes.extend(read(executed / 'generated/normalized.json')['tests'])
    statuses = {row['id'].split('::')[-1]: row['status'] for row in outcomes}
    assert statuses['test_gc_' + candidate['id']] == 'fail'
    assert statuses['test_gc_' + revision['id']] == 'pass'
    feedback = read(folder / 'feedback.json')
    assert {candidate['id'], revision['id']} <= set(feedback['executed_candidate_ids'])
    assert feedback['measured_profile_count'] == 0
    campaign(args)
    assert len(calls) == 2


@pytest.mark.parametrize('relative', ['configuration.json', 'toy/configuration.json'])
def test_changed_saved_configuration_is_rejected_before_it_is_overwritten(tmp_path, monkeypatch, relative):
    args, repository = arguments(tmp_path, 'none')
    calls = local_transport(monkeypatch, tmp_path, repository)
    campaign(args)
    configuration = args.output / relative
    changed = read(configuration)
    changed['limit'] = 999
    write(configuration, changed)
    with pytest.raises(ValueError, match='[Cc]onfiguration|[Aa]rtifact|[Rr]esume'):
        campaign(args)
    assert len(calls) == 2
    assert read(configuration)['limit'] == 999, 'Preserve changed evidence for inspection'
