"""Actual preparation, fair scheduling, emission and isolated local pytest."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.checkpoint import digest, read, write
from scripts.run_relation_search import algorithm_files, batch, loop, prepare
from scripts.run_relation_campaign import campaign, code_identity
from test_relation_search_loop import arguments, local_transport, prepared


SUBJECT = '''class Stream:
    def __init__(self, broken=False):
        self.closed = False
        self.broken = broken
    def read(self):
        if self.broken:
            raise ValueError('bad data')
    def pump(self):
        self.read()
        self.close()
    def close(self):
        self.closed = True
'''
TEST = '''import pytest
from subject import Stream

def test_use():
    r = Stream()
    other = Stream()
    other.pump()
    r.pump()
    assert r.closed is True
'''


def source_case(tmp_path):
    source, repository, registry = prepared(tmp_path)
    frontend = extract_frontend([Source('subject.py', SUBJECT, 'python'),
                                 Source('test_stream.py', TEST, 'python')])
    corpus = to_emitter_corpus(frontend)
    identifier = next(test_id for test_id, item in corpus['tests'].items() if item['name'] == 'test_use')
    rows = []
    for candidate_id, binding in [('first', 'other'), ('second', 'r')]:
        before = 'Stream()'
        start = TEST.index(f'{binding} = {before}') + len(f'{binding} = ')
        call = f'    {binding}.pump()'
        at = TEST.index(call)
        rows.append(dict(id=candidate_id, base_test_id=identifier, source_test_ids=[],
            language='python', kind='context', imports=[], edits=[
                dict(span=dict(path='test_stream.py', start_byte=start, end_byte=start+len(before)),
                     before=before, after='Stream(True)', role='input'),
                dict(span=dict(path='test_stream.py', start_byte=at, end_byte=at+len(call)),
                     before=call, after=f'    with pytest.raises(ValueError):\n        {binding}.pump()',
                     role='context')]))
    for name, value in [('corpus.json', corpus), ('frontend.json', frontend),
                        ('candidates.json', dict(candidates=rows))]:
        write(source/name, value)
    (source/'issue.md').write_text('Closing is required even when reading raises.\n')
    (repository/'subject.py').write_text(SUBJECT)
    (repository/'test_stream.py').write_text(TEST)
    return source, repository, registry


def ids(path):
    return [row['id'] for row in read(path)['candidates']]


def test_default_keeps_source_order_and_enabled_partition_reaches_fair_scheduler(tmp_path):
    source, _, registry = source_case(tmp_path)
    implicit = arguments(source, tmp_path/'implicit', registry)
    explicit = SimpleNamespace(**{**vars(implicit), 'output': tmp_path/'explicit', 'writer_priority': False})
    enabled = SimpleNamespace(**{**vars(implicit), 'output': tmp_path/'enabled', 'writer_priority': True})
    for args in [implicit, explicit, enabled]:
        prepare(args)
    assert ids(implicit.output/'source_pool.json') == ['first', 'second']
    assert read(implicit.output/'candidates.json') == read(explicit.output/'candidates.json')
    assert ids(implicit.output/'candidates.json') == ['first']
    assert not (implicit.output/'writer_priority.json').exists()
    assert ids(enabled.output/'source_pool.json') == ['second', 'first']
    assert ids(enabled.output/'candidates.json') == ['second']
    report = read(enabled.output/'writer_priority.json')
    assert report['supported_candidates'] == 1
    assert report['ranking'][0]['evidence'][0]['field'] == 'closed'
    assert report['source_sha256']['corpus.json'] == digest(source/'corpus.json')
    assert report['analyzed_source_sha256']
    assert read(enabled.output/'stage.json')['writer_priority'] is True
    assert read(implicit.output/'stage.json')['writer_priority'] is False
    assert prepare(enabled)['resumed']
    enabled.writer_priority = False
    with pytest.raises(ValueError, match='Resume inputs or algorithm changed'):
        prepare(enabled)


@pytest.mark.parametrize('enabled,chosen,generated_status', [(False, 'first', 'pass'), (True, 'second', 'fail')])
def test_selected_candidate_runs_through_actual_local_pytest(tmp_path, monkeypatch, enabled, chosen, generated_status):
    source, repository, registry = source_case(tmp_path)
    calls = local_transport(monkeypatch, tmp_path, repository)
    args = arguments(source, tmp_path/'loop', registry)
    args.rounds, args.writer_priority = 1, enabled
    loop(args)
    assert len(calls) == 1
    assert ids(args.output/'round_000/prepared/candidates.json') == [chosen]
    assert read(args.output/'configuration.json')['writer_priority'] is enabled
    runs = read(args.output/'round_000/executed/runs.json')
    controls = [row for row in runs if row['role'] == 'control']
    generated = [row for row in runs if row['role'] == 'generated' and row['candidate_id'] == chosen]
    assert len(generated) == 1 and controls
    assert all(read(row['result'])['counts']['pass'] == 1 for row in controls)
    assert read(generated[0]['result'])['counts'][generated_status] == 1
    assert loop(args)['rounds'][0]['prepared']['resumed']
    assert len(calls) == 1


def test_unsupported_language_retains_every_candidate_in_original_order(tmp_path):
    source, _, registry = prepared(tmp_path)
    code = '''package sample
import "testing"
func number(v int) int {return v}
func TestNumber(t *testing.T) { if number(1) != 1 {t.Error("bad")} }
'''
    frontend = extract_frontend([Source('x_test.go', code, 'go')])
    corpus = to_emitter_corpus(frontend)
    test_id = next(iter(corpus['tests']))
    start = code.index('number(1)') + len('number(')
    row = dict(id='edit', base_test_id=test_id, source_test_ids=[], language='go', kind='input', imports=[],
        edits=[dict(span=dict(path='x_test.go', start_byte=start, end_byte=start+1), before='1', after='2')])
    for name, value in [('corpus.json', corpus), ('frontend.json', frontend),
                        ('candidates.json', dict(candidates=[row]))]:
        write(source/name, value)
    plain = arguments(source, tmp_path/'plain', registry)
    enabled = SimpleNamespace(**{**vars(plain), 'output': tmp_path/'enabled', 'writer_priority': True})
    prepare(plain)
    prepare(enabled)
    assert ids(plain.output/'source_pool.json') == ids(enabled.output/'source_pool.json')
    assert ids(plain.output/'candidates.json') == ids(enabled.output/'candidates.json')
    report = read(enabled.output/'writer_priority.json')
    assert report['status'] == 'unsupported_language'
    assert report['original_order'] == report['ranked_order']


@pytest.mark.parametrize('entrypoint', ['batch', 'campaign'])
def test_coordinator_propagates_flag_through_real_preparation(tmp_path, monkeypatch, entrypoint):
    source, repository, registry = source_case(tmp_path)
    local_transport(monkeypatch, tmp_path, repository)
    sources = tmp_path/'sources'
    sources.mkdir()
    (sources/'arbitrary_name').symlink_to(source, target_is_directory=True)
    args = arguments(sources, tmp_path/entrypoint, registry)
    args.rounds, args.writer_priority, args.cases = 1, True, ['arbitrary_name']
    if entrypoint == 'campaign':
        args.oracle_mode, args.oracle_cache = 'none', None
        args.semantic_budget, args.per_request, args.model_workers = 1, 1, 1
        campaign(args)
    else:
        batch(args)
    assert read(args.output/'configuration.json')['writer_priority'] is True
    folder = args.output/'arbitrary_name/round_000/prepared'
    assert read(folder/'stage.json')['writer_priority'] is True
    assert read(folder/'writer_priority.json')['supported_candidates'] >= 1


def test_code_identity_includes_all_writer_analysis_dependencies():
    relative = {'prototypes/exception_write_priority.py', 'prototypes/assertion_write_origin.py',
                'scripts/analyze_assertion_write_origin_census.py'}
    assert relative <= set(code_identity())
    assert relative <= {str(path.relative_to(path.parents[1])) for path in algorithm_files()}
