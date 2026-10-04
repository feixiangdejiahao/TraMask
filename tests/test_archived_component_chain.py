import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import run_archived_component_chain as chain


def put(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return chain.frozen(path)


@pytest.fixture
def archive(tmp_path):
    # Commits belong exclusively to this disposable fixture repository.
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    code = tmp_path / 'runner.py'
    code.write_text('VERSION = "fixture"\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'runner.py'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    commit = subprocess.check_output(['git', '-C', str(tmp_path), 'rev-parse', 'HEAD']).decode().strip()
    return tmp_path, commit, chain.frozen(code)


def native(root, code, name='native', alert=None):
    source = root / 'original'
    inputs = {}
    for filename in sorted(chain.INPUTS):
        path = source / filename
        if not path.exists():
            put(path, {'original': filename})
        inputs[filename] = chain.frozen(path)
    cohort = root / 'cohort.json'
    if not cohort.exists():
        put(cohort, {'cases': [{'case': 'sample', 'source': str(source)}],
                     # Deliberately unavailable old code. This is input data,
                     # not an executed dependency of the new native component.
                     'algorithm': {'path': str(root / 'obsolete.py'), 'sha256': '0' * 64}})
    prepared = {'version': 'controlled-guest-declaration-order-search.v1',
                'algorithm': {'runner': code}, 'cases': [{'case': 'sample',
                'source': str(source), 'inputs': inputs}],
                'source_cohort': chain.frozen(cohort),
                'source_cohort_use': 'Only original snapshot paths and the full trial list; no old candidates or outcomes.'}
    summary = {'version': prepared['version'], 'results': [{'case': 'sample', 'alert': alert}],
               'trial_denominator': 1, 'native_executions': 2}
    directory = root / name
    prepared_receipt = put(directory / 'prepared.json', prepared)
    put(directory / 'seal.json', prepared_receipt)
    return prepared_receipt, put(directory / 'summary.json', summary)


def components(archive, monkeypatch):
    root, commit, code = archive
    monkeypatch.setattr(chain, 'ROOT', root)
    first_prepared, first_summary = native(root, code, 'base', {'token': 'first'})
    first = root / 'round01'
    p = put(first / 'prepared.json', {
        'version': chain.CHAIN, 'cases': ['sample'], 'algorithm': [code],
        'precedence': ['base'], 'components': [{'name': 'base', 'source': first_prepared,
                                               'prepared': first_prepared}]})
    put(first / 'seal.json', p)
    put(first / 'summary.json', {'version': chain.CHAIN, 'denominator': 1,
        'decisions': [{'case': 'sample', 'branch': 'base', 'alert': {'token': 'first'}}],
        'component_summaries': {'base': first_summary}, 'replayed_native_executions': 2,
        'independent_audit': {'path': str(root / 'do-not-read-audit.json'), 'sha256': '0' * 64}})
    native(root, code, 'declaration', {'token': 'second'})
    roots = {'round01': first, 'declaration': root / 'declaration'}
    return [{'name': name, 'commit': commit,
             **{key: chain.frozen(path / (key + '.json')) for key in ('prepared', 'summary', 'seal')}}
            for name, path in roots.items()]


def test_archived_code_survives_current_file_change(archive):
    root, commit, receipt = archive
    Path(receipt['path']).write_text('changed current code\n')
    verifier = chain.Verifier(root, commit)
    verifier.receipt(receipt, 'executed_code')
    assert verifier.code == [{'path': 'runner.py', 'sha256': receipt['sha256'], 'commit': commit}]


def test_archive_must_match_same_path_not_current_or_another_file(archive):
    root, commit, receipt = archive
    new = root / 'other.py'
    new.write_bytes(Path(receipt['path']).read_bytes())
    with pytest.raises(ValueError, match='absent at specified archive'):
        chain.Verifier(root, commit).receipt(chain.frozen(new), 'executed_code')
    Path(receipt['path']).write_text('new version\n')
    with pytest.raises(ValueError, match='Archive SHA mismatch'):
        chain.Verifier(root, commit).receipt(chain.frozen(receipt['path']), 'executed_code')


def test_receipt_requires_explicit_role(archive):
    root, commit, receipt = archive
    with pytest.raises(ValueError, match='receipt role'):
        chain.Verifier(root, commit).receipt(receipt, None)


def test_data_cohort_does_not_expand_obsolete_algorithm(archive):
    root, commit, code = archive
    prepared, summary = native(root, code)
    verifier = chain.Verifier(root, commit)
    result = verifier.execution(prepared, summary)
    assert result['cases'] == ['sample']
    assert len(verifier.code) == 1
    assert verifier.cohorts[0]['role'] == 'source_snapshot_list_data_only'


def test_one_byte_cohort_change_is_rejected(archive):
    root, commit, code = archive
    prepared, summary = native(root, code)
    with (root / 'cohort.json').open('a') as stream:
        stream.write(' ')
    with pytest.raises(ValueError, match='Changed data artifact'):
        chain.Verifier(root, commit).execution(prepared, summary)


@pytest.mark.parametrize('role', [None, '', 'Trust this source'])
def test_missing_or_unknown_cohort_role_rejected(archive, role):
    root, commit, code = archive
    prepared, summary = native(root, code)
    protocol = chain.read(prepared['path'])
    protocol['source_cohort_use'] = role
    prepared = put(prepared['path'], protocol)
    with pytest.raises(ValueError, match='data-role declaration'):
        chain.Verifier(root, commit).execution(prepared, summary)


def test_nested_noncode_input_change_is_rejected(archive):
    root, commit, code = archive
    prepared, summary = native(root, code)
    (root / 'original' / 'issue.md').write_text('changed')
    with pytest.raises(ValueError, match='Changed data artifact'):
        chain.Verifier(root, commit).execution(prepared, summary)


def test_complete_summary_and_denominator_required(archive):
    root, commit, code = archive
    prepared, summary = native(root, code)
    value = chain.read(summary['path'])
    value['results'] = []
    summary = put(summary['path'], value)
    with pytest.raises(ValueError, match='complete declared cohort'):
        chain.Verifier(root, commit).execution(prepared, summary)


def test_different_cohort_source_hashes_rejected(archive, monkeypatch):
    entries = components(archive, monkeypatch)
    second = entries[1]
    protocol = chain.read(second['prepared']['path'])
    alternative = put(archive[0] / 'different-selection.json', {'different': True})
    protocol['cases'][0]['inputs']['selection.json'] = alternative
    second['prepared'] = put(second['prepared']['path'], protocol)
    second['seal'] = put(second['seal']['path'], second['prepared'])
    with pytest.raises(ValueError, match='different source cohorts or hashes'):
        chain.load_components(entries)


def test_fixed_precedence_uses_alerts_without_audit_files(archive, monkeypatch):
    entries = components(archive, monkeypatch)
    loaded, reports, sources = chain.load_components(entries)
    result = chain.compose(sources, loaded)
    assert result[0]['alert'] == {'token': 'first'}
    assert result[0]['branch'] == 'round01'
    assert reports['round01']['excluded_audit_fields'] == ['independent_audit']
    reversed_loaded, _, _ = chain.load_components(list(reversed(entries)))
    assert chain.compose(sources, reversed_loaded)[0]['branch'] == 'declaration'


def test_fallback_is_uniform_and_does_not_replace_an_alert():
    loaded = {'round07': {'index': {'a': {'alert': {'token': 'old'}}, 'b': {'alert': None}}},
              'round02': {'index': {'a': {'alert': {'token': 'new'}}, 'b': {'alert': {'token': 'new'}}}}}
    result = chain.compose(['b', 'a'], loaded)
    assert [(r['case'], r['branch']) for r in result] == [('a', 'round07'), ('b', 'round02')]


def test_prepare_and_replay_never_spawn_subject_or_provider(archive, monkeypatch):
    entries = components(archive, monkeypatch)
    real_check_output = subprocess.check_output
    def git_only(args, **kwargs):
        assert args[0] == 'git'
        return real_check_output(args, **kwargs)
    monkeypatch.setattr(chain.subprocess, 'check_output', git_only)
    root = archive[0]
    output = root / 'combined'
    put(root / 'components.json', entries)
    chain.prepare(SimpleNamespace(components=root / 'components.json', output=output))
    outcome = chain.run(SimpleNamespace(input=output))
    assert outcome == {'alerts': 1, 'denominator': 1, 'fresh_native_executions': 0,
                       'fresh_provider_calls': 0, 'retrospective': True}
    first = chain.read(output / 'summary.json')
    assert chain.run(SimpleNamespace(input=output)) == first
    assert first['independent_audit_complete'] is False


def queue_fixture(archive, *, code_root=None):
    root, commit, code = archive
    if code_root is not None:
        code = dict(path=str(code_root / 'runner.py'), sha256=code['sha256'])
    output = root / 'queue'
    algorithm = {'relation_search.compact_contract_guarded': code}
    source_inputs, records, cases, inventories = [], [], [], {}
    baseline = put(root / 'legacy-inventory.json', {
        'algorithm': {'path': str(root / 'never-executed-old-code.py'), 'sha256': '0'*64}})
    for name in ['a', 'b']:
        source = root / 'original' / name
        inputs = {filename: put(source / filename, {'original': filename, 'case': name}) for filename in sorted(chain.INPUTS)}
        inventories[name] = dict(source=str(source), inputs=inputs)
        source_inputs.extend(inputs[key] for key in sorted(chain.SEMANTIC_INPUTS))
        ranking = []
        for rank in [1, 2]:
            identifier = name + str(rank)
            candidate = put(root / 'native' / identifier / 'candidates.json', [{'id': identifier}])
            runs = put(root / 'native' / identifier / 'runs.json', [])
            result = put(root / 'native' / identifier / 'normalized.json', {'tests': [{'status': 'fail'}]})
            manifest = put(root / 'native' / identifier / 'manifest.json', {'mounts': []})
            record = dict(key=name+':'+identifier, case=name, candidate_id=identifier,
                inputs={'corpus': inputs['corpus.json'], 'frontend': inputs['frontend.json'],
                        'candidates': candidate, 'runs': runs},
                native_evidence=[dict(result=result, manifest=manifest, test_ids=[identifier], tests=[{'status': 'fail'}])],
                controls=[dict(statuses=['pass'])])
            records.append(record)
            source_inputs.append(candidate)
            ranking.append(dict(rank=rank, candidate_id=identifier, key=record['key']))
        cases.append(dict(case=name, ranking=ranking))
    inventory = put(output / 'inventory.json', dict(controlled_failures=records, source_inventory=baseline))
    protocol = dict(version=chain.SEQUENTIAL, algorithm=algorithm, cases=cases, source_inputs=source_inputs,
        source_inventory=baseline, inventory=inventory,
        policy=dict(method='compact_contract_guarded', ordering='sorted_cases_round_robin_source_rank',
                    stop='first_semantic_supported_per_case', max_per_case=2))
    prepared = put(output / 'prepared.json', protocol)
    put(output / 'seal.json', {'prepared': prepared})
    results, refs = [], []
    for ordinal, outcome in enumerate(['unknown', 'supported', 'supported']):
        selection = chain.next_selection(cases, results, 2)
        record = next(r for r in records if r['key'] == selection['key'])
        directory = output / 'attempts' / f'attempt_{ordinal:06d}'
        put(directory / 'selection.json', selection)
        item_inventory = put(directory / 'inventory.json', dict(controlled_failures=[record], source_inventory=baseline))
        item_dir = directory / 'admission/item_0000'
        request = put(item_dir / 'request.json', {'id': 'request-'+str(ordinal), 'prompt': 'source only'})
        put(item_dir / 'analysis.json', {'status': 'pending'})
        decision = dict(status='semantic_supported' if outcome == 'supported' else 'unknown',
                        alarm_eligible=outcome == 'supported', request_id='request-'+str(ordinal))
        decision_ref = put(item_dir / 'decision.json', decision)
        put(directory / 'dispatch_claim.json', dict(request=request, reserved_calls=1, reserved_tokens=20))
        completion_request = put(item_dir / 'completion/request.json', chain.read(request['path']))
        body = item_dir / 'completion/response.body'
        body.write_text('{"answer":"recorded"}\n')
        put(item_dir / 'completion/response.json', {'answer': 'recorded'})
        (item_dir / 'completion/completion.txt').write_text('recorded answer')
        put(item_dir / 'completion/manifest.json', dict(request_id='request-'+str(ordinal),
            request_sha256=completion_request['sha256'], response_sha256=chain.frozen(body)['sha256']))
        admission = dict(stage='prepared', experiment='incremental_admission_of_frozen_generated_tests',
            method='compact_contract_guarded', method_module='relation_search.compact_contract_guarded',
            request_identity_version='actual-admission-dispatch-fields-v1', baseline=item_inventory,
            algorithm={'runner.py': code['sha256']}, algorithm_entry_modules=algorithm,
            imported_source_modules=algorithm,
            items=[dict(name='item_0000', **{k:selection[k] for k in ('key', 'case', 'candidate_id')},
                        source_inputs=record['inputs'], analysis_path=str(item_dir / 'analysis.json'),
                        request_path=request['path'], request_sha256=request['sha256'])])
        admission_ref = put(directory / 'admission/prepared.json', admission)
        put(directory / 'admission/summary.json', dict(stage='complete', prepared=admission_ref, provider_calls=1,
            decisions=[dict(**{k:selection[k] for k in ('key', 'case', 'candidate_id')},
                            decision=decision, decision_path=decision_ref['path'])]))
        artifacts = {str(path.relative_to(directory)): chain.frozen(path)['sha256']
                     for path in directory.rglob('*') if path.is_file()}
        result = dict(selection=selection, outcome=outcome, decision=decision, provider_calls=1,
                      reserved_calls=0, measured_tokens=10, reserved_tokens=0, usage_missing=0, artifacts=artifacts)
        refs.append(put(directory / 'result.json', result))
        results.append(result)
    summary = dict(version=chain.SEQUENTIAL, stage='complete', prepared=prepared, attempts=3,
        attempt_receipts=refs, counts=dict(pending=1, unknown=1, rejected=0, supported=2),
        outputs=[dict(**r['selection'], decision=r['decision']) for r in results if r['outcome']=='supported'],
        provider_calls=3, reserved_calls=0, measured_tokens=30, reserved_tokens=0, usage_missing=0,
        accounted_calls=3, accounted_tokens=30, native_executions=0)
    return dict(root=root, commit=commit, code=code, output=output, protocol=protocol,
                prepared=prepared, summary=put(output / 'summary.json', summary),
                records=records, inventories=inventories)


def verify_queue(queue):
    verifier = chain.Verifier(queue['root'], queue['commit'])
    return verifier.execution(queue['prepared'], queue['summary']), verifier


def rewrite_attempt_artifact(queue, ordinal, relative, value):
    directory = queue['output'] / 'attempts' / f'attempt_{ordinal:06d}'
    receipt = put(directory / relative, value)
    result = chain.read(directory / 'result.json')
    result['artifacts'][relative] = receipt['sha256']
    result_ref = put(directory / 'result.json', result)
    summary = chain.read(queue['summary']['path'])
    summary['attempt_receipts'][ordinal] = result_ref
    queue['summary'] = put(queue['summary']['path'], summary)


def test_complete_sequential_queue_expands_only_typed_execution_edges(archive):
    queue = queue_fixture(archive)
    result, verifier = verify_queue(queue)
    assert result['cases'] == ['a', 'b']
    assert [result['index'][name]['alert']['candidate_id'] for name in ['a', 'b']] == ['a2', 'b1']
    assert all(set(row['inputs']) == chain.SEMANTIC_INPUTS for row in result['sources'].values())
    assert len(verifier.code) == 1
    assert [d['role'] for d in verifier.dependencies] == ['controlled_candidate_inventory_data_only'] + ['sequential_admission_attempt']*3
    merged = chain.merge_sources(queue['inventories'], result['sources'])
    assert merged == queue['inventories']
    assert verifier.dependencies[0]['unrecorded_metadata'] == ['case.json', 'selection.json']


@pytest.mark.parametrize('kind', ['stage', 'missing_attempt', 'unfinished_attempt', 'outputs', 'counts'])
def test_incomplete_or_inconsistent_sequential_summaries_are_rejected(archive, kind):
    queue = queue_fixture(archive)
    summary = chain.read(queue['summary']['path'])
    if kind == 'stage': summary['stage'] = 'running'
    elif kind == 'missing_attempt': summary['attempt_receipts'].pop()
    elif kind == 'unfinished_attempt': (queue['output'] / 'attempts/attempt_000003').mkdir()
    elif kind == 'outputs': summary['outputs'].reverse()
    else: summary['counts']['supported'] = 1
    queue['summary'] = put(queue['summary']['path'], summary)
    with pytest.raises(ValueError): verify_queue(queue)


def test_changed_raw_provider_outcome_cannot_hide_behind_old_result_receipt(archive):
    queue = queue_fixture(archive)
    (queue['output'] / 'attempts/attempt_000001/admission/item_0000/completion/response.body').write_text('changed')
    with pytest.raises(ValueError, match='Changed data artifact'): verify_queue(queue)


def test_unknown_attempt_artifact_type_is_not_implicitly_trusted(archive):
    queue = queue_fixture(archive)
    rewrite_attempt_artifact(queue, 1, 'new-untyped-execution.json', {'path':'do not follow'})
    with pytest.raises(ValueError, match='Unknown sequential attempt artifact type'): verify_queue(queue)


@pytest.mark.parametrize('relative,change,expected', [
    ('selection.json', lambda v: dict(v, rank=2), 'round-robin selection'),
    ('dispatch_claim.json', lambda v: dict(v, reserved_calls=2), 'Dispatch claim'),
    ('admission/item_0000/completion/manifest.json', lambda v: dict(v, response_sha256='0'*64), 'raw request or response'),
    ('admission/item_0000/completion/manifest.json', lambda v: dict(v, request_id='different'), 'request identity'),
    ('admission/item_0000/decision.json', lambda v: dict(v, alarm_eligible=False), 'Raw admission decision'),
    ('admission/prepared.json', lambda v: dict(v, method='unknown'), 'Unsupported single-admission'),
    ('admission/prepared.json', lambda v: dict(v, algorithm={'runner.py':'0'*64}), 'algorithm differs'),
])
def test_hashes_do_not_substitute_for_cross_artifact_binding_checks(archive, relative, change, expected):
    queue = queue_fixture(archive)
    path = queue['output'] / 'attempts/attempt_000001' / relative
    rewrite_attempt_artifact(queue, 1, relative, change(chain.read(path)))
    with pytest.raises(ValueError, match=expected): verify_queue(queue)


def test_frozen_worktree_checks_head_current_bytes_and_same_archive_path(archive):
    root, commit, code = archive
    worktree = root / 'frozen'
    subprocess.run(['git', '-C', str(root), 'worktree', 'add', '--detach', '-q', str(worktree), commit], check=True)
    archived = dict(path=str(worktree / 'runner.py'), sha256=code['sha256'])
    verifier = chain.Verifier(root, commit, code_root=worktree)
    verifier.receipt(archived, 'executed_code')
    (worktree / 'runner.py').write_text('changed frozen code\n')
    with pytest.raises(ValueError, match='Frozen worktree code SHA mismatch'):
        chain.Verifier(root, commit, code_root=worktree).receipt(archived, 'executed_code')
    with pytest.raises(ValueError, match='root or HEAD differs'):
        chain.Verifier(root, '0'*40, code_root=worktree)
    outside = root / 'outside.py'
    outside.write_text('VERSION = "fixture"\n')
    with pytest.raises(ValueError, match='outside repository'):
        chain.Verifier(root, commit, code_root=worktree).receipt(chain.frozen(outside), 'executed_code')


def test_common_semantic_inputs_must_match_without_inventing_metadata(archive):
    queue = queue_fixture(archive)
    result, _ = verify_queue(queue)
    result['sources']['a']['inputs']['issue.md'] = put(queue['root'] / 'different-issue.md', {'changed':True})
    with pytest.raises(ValueError, match='different source cohorts or hashes'):
        chain.merge_sources(queue['inventories'], result['sources'])


def test_prepare_refuses_missing_summary_before_writing_any_combination(archive, monkeypatch):
    entries = components(archive, monkeypatch)
    root = archive[0]
    Path(entries[0]['summary']['path']).unlink()
    put(root / 'components.json', entries)
    output = root / 'combined'
    with pytest.raises(ValueError, match='Changed data artifact'):
        chain.prepare(SimpleNamespace(components=root/'components.json', output=output))
    assert not output.exists()


def legacy_chain_fixture(queue, code, commit):
    root = queue['root']
    source_cases = [dict(case=name, **source) for name, source in queue['inventories'].items()]
    cohort = put(root / 'legacy-source-list.json', dict(cases=source_cases,
        algorithm={'path':str(root / 'not-an-execution-dependency.py'), 'sha256':'0'*64}))
    def native_component(name, old_alert):
        protocol = dict(version='controlled-guest-declaration-order-search.v1', algorithm={'runner':code},
                        cases=source_cases, source_cohort=cohort, source_cohort_use=next(iter(chain.COHORT_USES)))
        prepared = put(root / name / 'prepared.json', protocol)
        put(root / name / 'seal.json', prepared)
        summary = put(root / name / 'summary.json', dict(version=protocol['version'], trial_denominator=2,
            results=[dict(case=n, alert=old_alert if n=='a' else None) for n in ['a','b']], native_executions=2))
        return prepared, summary
    base, base_summary = native_component('legacy-native', {'token':'earlier-alert'})
    first = put(root / 'legacy-round01/prepared.json', dict(version=chain.CHAIN, cases=['a','b'],
        algorithm=[code], precedence=['base'], components=[dict(name='base', source=base, prepared=base)]))
    put(root / 'legacy-round01/seal.json', first)
    first_summary = put(root / 'legacy-round01/summary.json', dict(version=chain.CHAIN, denominator=2,
        decisions=[dict(case='a', branch='base', alert={'token':'earlier-alert'}), dict(case='b', branch='abstain', alert=None)],
        component_summaries={'base':base_summary}))
    second, second_summary = native_component('legacy-declaration', None)
    components = [dict(name=name, commit=commit, prepared=p, summary=s, seal=chain.frozen(Path(p['path']).with_name('seal.json')))
                  for name,p,s in [('round01',first,first_summary), ('declaration',second,second_summary)]]
    protocol = dict(version=chain.ARCHIVED, algorithm=code, cases=['a','b'],
        source_inventory=queue['inventories'], precedence=['round01','declaration'], components=components,
        # The old derived report is byte-sealed but has no new execution edge.
        provenance={'old':{'code_receipts':[{'path':'obsolete-code.py','sha256':'0'*64,'commit':commit}]}})
    prepared = put(root / 'legacy-round07/prepared.json', protocol)
    put(root / 'legacy-round07/seal.json', prepared)
    summary = put(root / 'legacy-round07/summary.json', dict(version=chain.ARCHIVED, denominator=2,
        decisions=[dict(case='a', branch='round01', alert={'token':'earlier-alert'}, component_branch='base'),
                   dict(case='b', branch='abstain', alert=None)],
        component_summaries={'round01':first_summary,'declaration':second_summary}))
    return prepared, summary


@pytest.mark.parametrize('version', sorted(chain.ARCHIVES))
def test_nested_archive_uses_original_commits_and_does_not_execute_cached_reports(archive, monkeypatch, version):
    queue = queue_fixture(archive)
    prepared, summary = legacy_chain_fixture(queue, archive[2], archive[1])
    prepared = put(prepared['path'], dict(chain.read(prepared['path']), version=version))
    summary = put(summary['path'], dict(chain.read(summary['path']), version=version))
    verifier = chain.Verifier(archive[0], archive[1])
    result = verifier.execution(prepared, summary)
    assert result['index']['a']['alert'] == {'token':'earlier-alert'}
    assert result['sources'] == queue['inventories']
    assert [d['role'] for d in verifier.dependencies] == ['prior_verification_report_data_only',
        'archived_executed_component', 'archived_executed_component']
    protocol = chain.read(prepared['path'])
    protocol['components'][0]['commit'] = '0'*40
    prepared = put(prepared['path'], protocol)
    with pytest.raises(ValueError, match='Code absent at specified archive'):
        chain.Verifier(archive[0], archive[1]).execution(prepared, summary)


def test_new_chain_retains_all_second_component_outputs_without_label_based_replacement(archive, monkeypatch):
    root, commit, code = archive
    worktree = root / 'frozen'
    subprocess.run(['git', '-C', str(root), 'worktree', 'add', '--detach', '-q', str(worktree), commit], check=True)
    queue = queue_fixture(archive, code_root=worktree)
    legacy_chain_fixture(queue, code, commit)
    monkeypatch.setattr(chain, 'ROOT', root)
    output = root / 'combined-fixture'
    entries = [dict(name=name, commit=commit, code_root=str(worktree if name=='queue' else root),
        **{key:chain.frozen(directory/(key+'.json')) for key in ('prepared','summary','seal')})
        for name,directory in [('legacy',root/'legacy-round07'),('queue',root/'queue')]]
    put(root / 'components.json', entries)
    chain.prepare(SimpleNamespace(components=root/'components.json', output=output))
    chain.run(SimpleNamespace(input=output))
    summary = chain.read(output / 'summary.json')
    assert [(row['case'], row['branch']) for row in summary['decisions']] == [('a','legacy'),('b','queue')]
    assert [row['alert']['candidate_id'] for row in summary['component_outputs']['queue']] == ['a2','b1']
    assert summary['independent_audit_complete'] is False
    assert summary['fresh_provider_calls'] == summary['fresh_native_executions'] == 0


def quantity_fixture(archive):
    root, commit, code = archive
    prepared, summary = native(root, code, 'quantity')
    protocol = chain.read(prepared['path'])
    protocol['version'] = chain.QUANTITY
    protocol['source_cohort_use'] = 'Trial list and original source paths only; no candidates or outcomes.'
    relation_ir = put(root / 'relations/sample.json', {'version':'public-quantity-bound-relation.v1', 'relations':[]})
    protocol['cases'][0]['inputs']['relation_ir'] = relation_ir
    prepared = put(prepared['path'], protocol)
    put(root / 'quantity/seal.json', prepared)
    result = chain.read(summary['path'])
    result['version'] = chain.QUANTITY
    return prepared, put(summary['path'], result), relation_ir


def test_quantity_ir_is_sealed_construction_data_not_original_source_or_verified_provider(archive):
    prepared, summary, relation_ir = quantity_fixture(archive)
    verifier = chain.Verifier(archive[0], archive[1])
    result = verifier.execution(prepared, summary)
    assert set(result['sources']['sample']['inputs']) == chain.INPUTS
    assert verifier.dependencies == [dict(role='relation_construction_data', case='sample',
        receipt=relation_ir, provider_discovery_verified=False,
        reason='Native protocol freezes relation bytes but does not declare their discovery protocol.')]
    Path(relation_ir['path']).write_text('changed')
    with pytest.raises(ValueError, match='Changed data artifact'):
        chain.Verifier(archive[0], archive[1]).execution(prepared, summary)


@pytest.mark.parametrize('change', ['missing_ir', 'unrecognized_extra'])
def test_quantity_construction_inputs_require_exact_roles(archive, change):
    prepared, summary, relation_ir = quantity_fixture(archive)
    protocol = chain.read(prepared['path'])
    if change == 'missing_ir':
        del protocol['cases'][0]['inputs']['relation_ir']
    else:
        protocol['cases'][0]['inputs']['other_ir'] = relation_ir
    prepared = put(prepared['path'], protocol)
    with pytest.raises(ValueError, match='incomplete source inputs'):
        chain.Verifier(archive[0], archive[1]).execution(prepared, summary)


def test_components_reject_unknown_fields_duplicate_names_and_undeclared_prerequisite(archive, monkeypatch):
    entries = components(archive, monkeypatch)
    with pytest.raises(ValueError, match='Duplicate component name'):
        chain.load_components([entries[0], entries[0]])
    entries[0]['trust_all'] = True
    with pytest.raises(ValueError, match='Unknown or malformed'):
        chain.load_components(entries)
    del entries[0]['trust_all']
    entries[0]['prerequisite'] = {'kind':'unknown'}
    with pytest.raises(ValueError, match='Unsupported prerequisite kind'):
        chain.load_components(entries)


def test_replay_rejects_changed_frozen_priority_even_with_valid_new_prepared_seal(archive, monkeypatch):
    entries = components(archive, monkeypatch)
    root = archive[0]
    put(root / 'components.json', entries)
    output = root / 'combined'
    chain.prepare(SimpleNamespace(components=root/'components.json', output=output))
    protocol = chain.read(output / 'prepared.json')
    protocol['components'].reverse()
    put(output / 'prepared.json', protocol)
    put(output / 'seal.json', chain.frozen(output/'prepared.json'))
    with pytest.raises(ValueError, match='Unexpected archived chain protocol'):
        chain.run(SimpleNamespace(input=output))
