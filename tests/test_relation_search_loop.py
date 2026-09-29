"""Run the real prepare/materialize/feedback loop with local isolated pytest.

Only the Docker transport is substituted; source snapshots, probe helper,
pytest reports, phase order, measured retention and resume logic are real.
"""
import copy
import json
from pathlib import Path
import shlex
import shutil
import sys
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.checkpoint import read, write
from scripts.run_relation_search import loop


CODE = '''def accepts(a, b, options): return True
def test_pairs():
    a = []
    b = []
    options = {"x": 1, "y": 2}
    assert accepts(a, b, options)
'''


def prepared(tmp_path):
    path = 'test_profile.py'
    def span(text, last=False):
        start = (CODE.rindex if last else CODE.index)(text)
        return dict(path=path, start_byte=start, end_byte=start+len(text))
    frontend = extract_frontend([Source(path, CODE, 'python')])
    corpus = to_emitter_corpus(frontend)
    identifier = next(iter(corpus['tests']))
    call_b = span('b, options', True)
    call_b['end_byte'] = call_b['start_byte'] + 1
    roles = [dict(name='a', expression='a', origin_span=span('a = []')),
             dict(name='b', expression='b', origin_span=span('b = []'), input_span=call_b),
             dict(name='options', expression='options', origin_span=span('options = {"x": 1, "y": 2}'))]
    probe = dict(phase='before_call', insert_before=span('assert accepts(a, b, options)'), roles=roles)
    rows = []
    for key, kind, edit in [('alias', 'a_alias', dict(span=call_b, before='b', after='a')),
                           ('presence', 'z_presence', dict(span=span('{"x": 1, "y": 2}'),
                                                          before='{"x": 1, "y": 2}', after='{"x": 1}'))]:
        rows.append(dict(id=key, base_test_id=identifier, source_test_ids=[], language='python',
                         kind=kind, edits=[edit], imports=[], runtime_probes=[copy.deepcopy(probe)],
                         control_runtime_probes=[copy.deepcopy(probe)]))
    rows[0]['runtime_probes'][0]['roles'][1]['expression'] = 'a'
    repository = tmp_path/'repository'
    repository.mkdir()
    (repository/path).write_text(CODE)
    source = tmp_path/'source'
    for name, value in [('corpus.json', corpus), ('frontend.json', frontend),
                        ('candidates.json', dict(candidates=rows)), ('selection.json', {}),
                        ('case.json', dict(id='toy', language='python', repository=str(repository))),
                        ('prepare.json', dict(status='prepared'))]:
        write(source/name, value)
    (source/'issue.md').write_text('The test accepts each supplied input.\n')
    registry = tmp_path/'registry.json'
    write(registry, [])
    return source, repository, registry


def local_transport(monkeypatch, tmp_path, repository):
    from scripts.relational_phase_runner import execute_plan
    calls = []
    def harness(repository, language, files, name_filter):
        return dict(command='env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ' + shlex.quote(sys.executable) +
                    ' -m pytest -q -c /dev/null --rootdir=. --confcutdir=. -p no:cacheprovider ' +
                    ' '.join(shlex.quote(path) for path in files) + ' -k ' + shlex.quote(name_filter) +
                    ' --junitxml="$COMBINATION_REPORT_DIR/junit.xml"', files={},
                    report_format='pytest-junit', report_path='junit.xml')
    def replay(case, command, *, mounts, timeout, output, registry):
        calls.append(str(output))
        root = tmp_path/('replay_' + str(len(calls)))
        shutil.copytree(repository, root)
        output.mkdir(parents=True)
        for mount in mounts:
            destination = root/mount['target']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mount['source'], destination)
        plan = read(root/'.relational_phase_inputs/plan.json')
        assert [row['role'] for row in plan['phases']] in (['control', 'source_profile', 'generated'], ['control', 'generated'])
        execute_plan(plan, repository=root, logs=output)
        result = dict(returncode=0, output=str(output))
        write(output/'execution.json', result)
        return result
    monkeypatch.setattr('generic_composition.runner.infer_harness', harness)
    monkeypatch.setattr('scripts.run_relational_gap_case.run_case', replay)
    return calls


def arguments(source, output, registry, strategy='profile'):
    return SimpleNamespace(source=source, output=output, previous=None, rounds=2, limit=1, pool=16,
                           max_edits=4, strategy=strategy, workers=1, group_size=4, timeout=15,
                           include_baseline=True, representations_only=True, registry=registry,
                           dependency_packages_root=source)


def test_two_real_rounds_seed_first_runtime_extension_and_idempotent_resume(tmp_path, monkeypatch):
    source, repository, registry = prepared(tmp_path)
    calls = local_transport(monkeypatch, tmp_path, repository)
    args = arguments(source, tmp_path/'campaign', registry)
    result = loop(args)
    assert len(calls) == 2
    first = read(args.output/'round_000/feedback.json')
    second = read(args.output/'round_001/feedback.json')
    selected = read(args.output/'round_001/prepared/candidates.json')['candidates']
    assert selected[0]['kind'] == 'executed_parent_extension'
    assert selected[0]['runtime_parent_id'] == 'alias'
    assert first['eligible_parents'][0]['feedback']['retained']
    assert first['eligible_parents'][0]['feedback']['profile_baseline_measured']
    assert {'alias', selected[0]['id']} <= set(second['executed_candidate_ids'])
    assert all(round_['counters']['executed_test_outcomes'] == 3 for round_ in second['rounds'])
    assert all(round_['new_generated_profiles'] == 1 for round_ in second['rounds'])
    assert 'presence' in {row['id'] for row in read(args.output/'round_001/prepared/source_pool.json')['candidates']}
    for i in range(2):
        executed = args.output/f'round_{i:03d}/executed/group_000'
        assert read(executed/'phases.json')[1]['role'] == 'source_profile'
        assert (executed/'source_profile/relation_trace.jsonl').exists()
    resumed = loop(args)
    assert len(calls) == 2
    assert resumed['final_feedback'] == result['final_feedback']
    changed = args.output/'round_000/emitted/group_000/generated/files/test_profile.py'
    changed.write_text(changed.read_text()+'\n# tamper\n')
    with pytest.raises(ValueError, match='checkpoint artifact changed'):
        loop(args)


def test_rotation_control_uses_same_constructor_and_instrumented_execution_budget(tmp_path, monkeypatch):
    source, repository, registry = prepared(tmp_path)
    calls = local_transport(monkeypatch, tmp_path, repository)
    args = arguments(source, tmp_path/'campaign', registry, strategy='rotation')
    loop(args)
    assert len(calls) == 2
    feedback = read(args.output/'round_001/feedback.json')
    assert sum(row['counters']['executed_test_outcomes'] for row in feedback['rounds']) == 6
    candidate = read(args.output/'round_001/prepared/candidates.json')['candidates'][0]
    assert candidate['kind'] == 'executed_parent_extension'
    assert candidate['provenance']['composition']['selection_strategy'] == 'rotation'


def test_executed_tests_without_trace_are_checkpointed_and_never_claim_profiles(tmp_path, monkeypatch):
    source, repository, registry = prepared(tmp_path)
    batch = read(source/'candidates.json')
    for row in batch['candidates']:
        row.pop('runtime_probes')
        row.pop('control_runtime_probes')
    write(source/'candidates.json', batch)
    calls = local_transport(monkeypatch, tmp_path, repository)
    args = arguments(source, tmp_path/'campaign', registry)
    args.limit, args.rounds = 2, 2
    result = loop(args)
    feedback = read(args.output/'round_000/feedback.json')
    assert set(feedback['executed_candidate_ids']) == {'alias', 'presence'}
    assert feedback['measured_profile_count'] == 0
    assert all(row['status'] == 'no_runtime_profile' and not row['retained'] for row in feedback['results'])
    assert len(calls) == 1
    assert result['rounds'][-1]['stopped'] == 'no_unexecuted_hypothesis'


def test_materialization_rejection_is_attempted_but_not_executed_or_reselected(tmp_path, monkeypatch):
    source, repository, registry = prepared(tmp_path)
    rows = read(source/'candidates.json')['candidates']
    for row in rows:
        row['edits'][0]['before'] = 'different source text'
    write(source/'candidates.json', dict(candidates=rows))
    calls = local_transport(monkeypatch, tmp_path, repository)
    args = arguments(source, tmp_path/'campaign', registry)
    args.limit = 2
    result = loop(args)
    measured = read(args.output/'round_000/feedback.json')
    assert set(measured['attempted_candidate_ids']) == {'alias', 'presence'}
    assert measured['executed_candidate_ids'] == []
    assert measured['measured_profile_count'] == 0
    assert calls == []
    assert result['rounds'][-1]['stopped'] == 'no_unexecuted_hypothesis'


def test_failed_source_control_cannot_supply_extension_parents(tmp_path, monkeypatch):
    source, repository, registry = prepared(tmp_path)
    corpus = read(source/'corpus.json')
    # The operation returns False, while both original and generated asserts
    # still expect True. Inputs and their probes remain syntactically valid.
    old = corpus['sources']['test_profile.py']['code']
    changed = old.replace('return True', 'return None')  # Equal byte length.
    assert len(old) == len(changed)
    corpus['sources']['test_profile.py']['code'] = changed
    write(source/'corpus.json', corpus)
    (repository/'test_profile.py').write_text(changed)
    calls = local_transport(monkeypatch, tmp_path, repository)
    args = arguments(source, tmp_path/'campaign', registry)
    args.limit = 2
    loop(args)
    measured = read(args.output/'round_000/feedback.json')
    assert measured['measured_profile_count'] > 0
    assert measured['eligible_parents'] == []
    assert len(calls) == 1


def test_semantic_merge_preserves_input_identity_and_does_not_borrow_parent_completion(tmp_path, monkeypatch):
    from scripts.run_relation_search import prepare, feedback
    from scripts.relation_search_semantics import merge
    from scripts.execute_relation_search import emit_batch, run
    source, repository, registry = prepared(tmp_path)
    calls = local_transport(monkeypatch, tmp_path, repository)
    args = arguments(source, tmp_path/'prepared', registry)
    prepare(args)
    merged = tmp_path/'merged'
    merge(SimpleNamespace(input=args.output, output=merged, completions=[]))
    assert not (merged/'checkpoint.json').exists()
    assert not (merged/'stage.json').exists()
    emitted, executed = tmp_path/'emitted', tmp_path/'executed'
    emit_batch(SimpleNamespace(input=merged, output=emitted, group_size=4, timeout=15,
                              dependency_packages_root=source))
    run(SimpleNamespace(input=emitted, output=executed, registry=registry, workers=1))
    checkpoint = tmp_path/'feedback.json'
    feedback(SimpleNamespace(source=executed, output=checkpoint, previous=None))
    assert len(calls) == 1
    assert read(checkpoint)['source_identity'] == read(args.output/'prepare.json')['source_identity']
