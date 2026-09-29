"""Drain a semantic backlog through real materialization and local pytest.

Only provider dispatch and Docker transport are replaced.  The oracle request,
validation, program search, campaign checkpoints, source controls and feedback
all use their production implementations.
"""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from relation_search.checkpoint import digest, read, write
from scripts.run_relation_campaign import campaign
from test_relation_campaign import arguments
from test_relation_oracle import setup
from test_relation_search_loop import local_transport


class InterruptedAfterTransport(BaseException):
    """A process interruption, rather than an execution infrastructure error."""


def count_campaign(tmp_path):
    args, repository = arguments(tmp_path, 'fresh')
    args.rounds, args.limit, args.semantic_budget = 4, 2, 1
    source = args.source / 'toy'
    corpus, frontend, first = setup()
    first.update(kind='a_length', language='python')
    second = deepcopy(first)
    second['id'] = 'three_items'
    second['edits'][0]['after'] = '[1, 2, 3]'
    for name, value in [('corpus.json', corpus), ('frontend.json', frontend),
                        ('candidates.json', dict(candidates=[first, second]))]:
        write(source / name, value)
    (source / 'issue.md').write_text('Count the items.\n')
    for path, metadata in corpus['sources'].items():
        (repository / path).write_text(metadata['code'])
    return args, repository, {row['id']: row for row in [first, second]}


def exact_list_length_provider(monkeypatch):
    requests = []

    def dispatch(request, output, *, root):
        requests.append(deepcopy(request))
        assert list(request['offered']) == ['C0']
        candidate = request['offered']['C0']['candidate']
        count = len(ast.literal_eval(candidate['edits'][0]['after']))
        output.mkdir(parents=True, exist_ok=False)
        manifest = dict(status='complete', request_id=request['id'],
                        external_model_calls=1, finish_reason='stop')
        write(output / 'manifest.json', manifest)
        (output / 'completion.txt').write_text(json.dumps({'revisions': [dict(
            candidate='C0', basis='The supplied literal list has this many items.',
            updates=[dict(assertion='A0', code=f'assert result == {count}')],
        )]}))
        return manifest

    monkeypatch.setattr('relational_gap.provider.dispatch', dispatch)
    return requests


def assert_passing_control_binding(runs, candidate_id):
    generated = [row for row in runs if row['candidate_id'] == candidate_id
                 and row['role'] == 'generated']
    assert len(generated) == 1
    row = generated[0]
    assert row['control_ids']
    controls = [control for control in runs if control['role'] == 'control'
                and control['manifest'] == row['manifest']]
    assert set(row['control_ids']) == {name for control in controls for name in control['test_ids']}
    for control in controls:
        report = read(control['result'])
        assert report['errors'] == []
        assert report['counts']['pass'] == 1
        assert all(test['status'] == 'pass' for test in report['tests'])
        # The independently executed source retains its original assertion and
        # list; it is not the revised generated test reused as a control.
        context = read(control['execution_context']['context_file'])
        assert context['role'] == 'control'
        mounts = {mount['target']: Path(mount['source'])
                  for mount in read(control['manifest'])['mounts']}
        snapshot = mounts[context['source_files'][0]['staged']]
        code = ast.parse(snapshot.read_text())
        function = next(node for node in code.body if isinstance(node, ast.FunctionDef)
                        and node.name == control['test_ids'][0])
        assert ast.literal_eval(function.body[0].value) == [1]
        assert ast.unparse(function.body[-1]) == 'assert result == 1'
    return row


@pytest.mark.parametrize('interrupt_after_pending_execution', [False, True])
def test_pending_oracle_candidate_survives_program_exhaustion_and_resume(
        tmp_path, monkeypatch, interrupt_after_pending_execution):
    args, repository, original = count_campaign(tmp_path)
    requests = exact_list_length_provider(monkeypatch)
    executions = local_transport(monkeypatch, tmp_path, repository)
    if interrupt_after_pending_execution:
        from scripts import run_relational_gap_case
        replay = run_relational_gap_case.run_case
        interrupted = []

        def pause_after_execution(case, command, **kwargs):
            outcome = replay(case, command, **kwargs)
            if 'round_001' in Path(kwargs['output']).parts and not interrupted:
                interrupted.append(True)
                raise InterruptedAfterTransport()
            return outcome

        monkeypatch.setattr(run_relational_gap_case, 'run_case', pause_after_execution)
        with pytest.raises(InterruptedAfterTransport):
            campaign(args)
        assert len(requests) == 2 and len(executions) == 3
        pending_folder = args.output / 'toy/round_001'
        assert (pending_folder / 'executed/group_000/execution.json').is_file()
        assert not (pending_folder / 'feedback.json').exists()

    result = campaign(args)
    assert len(requests) == 2
    assert len(executions) == 3  # Two initial lanes, then only the pending revision.
    offered = [request['offered']['C0']['candidate']['id'] for request in requests]
    assert len(set(offered)) == 2 and set(offered) == set(original)
    record = read(args.output / 'campaign.json')[0]
    assert record['stopped_reason'] == 'exhausted'
    assert [row['round'] for row in record['rounds']] == [0, 1]
    assert [row['prepared']['selected'] for row in record['rounds']] == [2, 0]
    root = args.output / 'toy'
    first, later = root / 'round_000', root / 'round_001'
    first_queue = read(first / 'semantic/semantic_frontier.json')
    later_queue = read(later / 'semantic/semantic_frontier.json')
    assert first_queue['pending_ids'] == [offered[1]]
    assert later_queue['pending_ids'] == []
    assert set(later_queue['selected_ids']) == set(original)
    assert read(later / 'prepared/candidates.json')['candidates'] == []
    assert read(Path(record['exhausted_prepare']).parent / 'candidates.json')['candidates'] == []
    semantic = read(later / 'semantic/semantic_result.json')
    assert semantic['source_count'] == 0 and semantic['revised_count'] == 1
    assert semantic['provider_calls'] == 1 and semantic['recovery_calls'] == 0
    assert semantic['offered_ids'] == [offered[1]]
    assert sum(row['semantic']['provider_calls'] for row in record['rounds']) == 2
    revision = read(later / 'semantic/candidates.json')['candidates'][0]
    assert revision['semantic_revision']['parent'] == offered[1]
    assert revision['edits'][:-1] == original[offered[1]]['edits']
    assert revision['edits'][-1]['role'] == 'semantic_expected'
    assert requests[1]['source_prepared'] == str((later / 'prepared').resolve())
    assert read(later / 'semantic/prepare.json')['source_identity'] == read(first / 'prepared/prepare.json')['source_identity']

    later_runs = read(later / 'executed/runs.json')
    generated = assert_passing_control_binding(later_runs, revision['id'])
    report = read(generated['result'])
    assert report['errors'] == [] and report['counts']['pass'] == 1
    assert report['counts'].get('fail', 0) == 0
    assert generated['execution_lane'] == 'relation_search_oracle'
    feedback = read(later / 'feedback.json')
    assert set(original) | {revision['id']} <= set(feedback['executed_candidate_ids'])
    assert len(feedback['current_results']) == 1
    observed = feedback['current_results'][0]
    assert observed['candidate_id'] == revision['id']
    assert observed['executed'] and observed['parent_eligible']
    assert observed['control_and_seed_valid']
    assert observed['candidate_outcomes'][0]['statuses'] == ['pass']
    assert feedback['rounds'][1]['counters']['control_pass'] == 1
    assert feedback['rounds'][1]['counters']['generated_pass'] == 1
    # The raw candidates really ran and failed under the old assertion. Their
    # earlier outcomes do not substitute for the later revision's own evidence.
    first_runs = read(first / 'executed/runs.json')
    for identifier in original:
        raw = assert_passing_control_binding(first_runs, identifier)
        normalized = read(raw['result'])
        outcome = next(test for test in normalized['tests']
                       if test['id'].endswith('::test_gc_' + identifier))
        assert outcome['status'] == 'fail'

    frozen_paths = [*root.glob('round_00[01]/semantic/semantic_frontier.json'),
                    *root.glob('round_00[01]/feedback.json'),
                    *root.glob('round_00[01]/executed/checkpoint.json')]
    checksums = {path: digest(path) for path in frozen_paths}
    assert campaign(args) == result
    assert len(requests) == 2 and len(executions) == 3
    assert {path: digest(path) for path in frozen_paths} == checksums
