import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import replay_csi_guarded_prefix as replay


def gate(decision='allow', outside=False):
    status = {'allow': 'bounded_input_domain_checked', 'unknown': 'input_domain_or_binding_unproved',
              'reject': 'positive_keyboard_input_contradicts_domain'}[decision]
    return dict(version='source-bound-csi-input-domain.v1', decision=decision,
                status='outside_registered_scope' if outside else status,
                allow_prior_gate=decision == 'allow', whole_test_semantics='unconfirmed')


def fixture(outcomes=('rejected', 'supported'), gates=('allow', 'allow')):
    entries = [dict(rank=i, candidate_id=f'candidate{i}', key=f'key{i}') for i in range(1, 4)]
    cases = [dict(case='trial', ranking=entries)]
    rows = [dict(attempt=f'attempt_{i:06d}', selection=dict(case='trial', **entries[i]),
                 semantic_outcome=outcome, original_result=dict(path=f'result{i}', sha256=str(i)),
                 source_gate=dict(guard=gate(gates[i])), call=dict(request=dict(path=f'request{i}')))
            for i, outcome in enumerate(outcomes)]
    return cases, rows


def test_first_allowed_support_transfers_original_receipt_without_mutation():
    cases, rows = fixture()
    before = copy.deepcopy(rows)
    result = replay.derive(cases, rows, 3)[0]
    assert result['alert']['original_result'] == rows[1]['original_result']
    assert result['alert']['validity'] == 'pending_independent_full_test_audit'
    assert result['status'] == 'emitted' and rows == before


@pytest.mark.parametrize('state', ['reject', 'unknown'])
def test_withheld_original_stop_leaves_next_unobserved_rank_pending(state):
    cases, rows = fixture(('supported',), (state,))
    result = replay.derive(cases, rows, 3)[0]
    assert result['alert'] is None and result['status'] == 'pending'
    assert result['next_unobserved']['rank'] == 2


def test_missing_prefix_cannot_be_skipped_to_a_later_known_support():
    cases, rows = fixture()
    result = replay.derive(cases, rows[1:], 3)[0]
    assert result['alert'] is None and result['observed_attempts'] == []
    assert result['next_unobserved']['rank'] == 1


def test_guard_can_withhold_observed_rejection_then_reuse_next_observed_support():
    cases, rows = fixture(gates=('reject', 'allow'))
    assert replay.derive(cases, rows, 3)[0]['alert']['selection']['rank'] == 2


def test_allow_outside_scope_does_not_override_semantic_unknown():
    cases, rows = fixture(('unknown',), ('allow',))
    rows[0]['source_gate']['guard'] = gate(outside=True)
    assert replay.derive(cases, rows, 3)[0]['alert'] is None
    rows[0]['semantic_outcome'] = 'supported'
    assert replay.derive(cases, rows, 3)[0]['status'] == 'emitted'


def test_all_trials_remain_in_denominator_even_when_unobserved():
    cases, rows = fixture()
    cases += [dict(case=f'unobserved{i}', ranking=copy.deepcopy(cases[0]['ranking'])) for i in range(16)]
    result = replay.derive(cases, rows, 3)
    assert len(result) == 17 and sum(r['status'] == 'pending' for r in result) == 16


def test_original_per_case_budget_is_not_refilled():
    cases, rows = fixture(('rejected',), ('reject',))
    result = replay.derive(cases, rows, 1)[0]
    assert result['status'] == 'abstain' and result['next_unobserved'] is None


@pytest.mark.parametrize('bad', [None, {}, {'decision': 'allow', 'status': 'input_domain_or_binding_unproved', 'allow_prior_gate': True}])
def test_unknown_cannot_be_silently_treated_as_allow(bad):
    if bad is None:
        with pytest.raises((ValueError, AttributeError)):
            replay.guard_allows(bad)
    else:
        with pytest.raises(ValueError):
            replay.guard_allows(bad)


def test_candidate_substitution_is_rejected():
    cases, rows = fixture()
    rows[1]['selection']['candidate_id'] = 'some_other_candidate'
    with pytest.raises(ValueError, match='declared cohort'):
        replay.derive(cases, rows, 3)


def archive_fixture(tmp_path):
    """Real on-disk receipts, one trial, no provider or subject process."""
    source = tmp_path / 'history'
    source.mkdir()
    def put(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        return replay.frozen(path)
    def text(path, value):
        path.write_text(value)
        return replay.frozen(path)
    cases, abstract = fixture()
    source_code = 'def operation(): pass\n'
    sha = lambda value: hashlib.sha256(value.encode()).hexdigest()
    corpus = put(tmp_path / 'corpus.json', dict(sources={'api.py': dict(code=source_code)}))
    frontend = put(tmp_path / 'frontend.json', {})
    candidates = put(tmp_path / 'candidates.json', [])
    inventory = put(source / 'inventory.json', {})
    issue = text(tmp_path / 'issue.md', 'Public contract')
    base = dict(version='sequential-source-admission.v1', cases=cases,
                policy=dict(max_per_case=3, max_model_calls=2), inventory=inventory,
                source_inputs=[corpus, frontend, candidates, issue], algorithm={'old_source': 'archived_hash'},
                source_ranking_policy_sha256='ranking_hash')
    prepared_receipt = put(source / 'prepared.json', base)
    put(source / 'seal.json', dict(prepared=prepared_receipt))
    census_rows, result_receipts = [], []
    for i, row in enumerate(abstract):
        directory = source / 'attempts' / row['attempt']
        item_dir = directory / 'admission/item_0000'
        item_dir.mkdir(parents=True)
        put(directory / 'selection.json', row['selection'])
        analysis = put(item_dir / 'analysis.json', {'analysis': {}})
        payload = dict(original_test='def test(): pass', modified_test='def test(): operation()')
        request = dict(system='Review all setup and assertions', prompt=json.dumps(payload), thinking='enabled',
                       max_tokens=100, reasoning_effort='high', candidate_id=row['selection']['candidate_id'],
                       candidate_sha256='candidate_bytes', source_sha256={'api.py': sha(source_code)},
                       request_identity_version='actual-admission-dispatch-fields-v1')
        request['id'] = request['query_sha256'] = replay.dispatch_identity(request)
        request_receipt = put(item_dir / 'request.json', request)
        wire = dict(messages=[dict(role='system', content=request['system']), dict(role='user', content=request['prompt'])],
                    thinking=dict(type='enabled'), max_tokens=100, reasoning_effort='high', model='test-model')
        wire_receipt = put(item_dir / 'completion/request.json', wire)
        response = text(item_dir / 'completion/response.body', 'response bytes are only hashed')
        put(item_dir / 'completion/manifest.json', dict(request_sha256=wire_receipt['sha256'], request_id=request['id'],
            thinking='enabled', reasoning_effort='high', max_output_tokens=100, model='test-model',
            external_model_calls=1, response_sha256=response['sha256'], usage=dict(total_tokens=123)))
        put(directory / 'dispatch_claim.json', dict(request=request_receipt, reserved_calls=1,
            reserved_tokens=len(request['system'].encode()) + len(request['prompt'].encode()) + 100 + 256))
        put(directory / 'admission/prepared.json', dict(items=[dict(name='item_0000',
            **{k: row['selection'][k] for k in ('key', 'case', 'candidate_id')},
            source_inputs=dict(corpus=corpus, frontend=frontend, candidates=candidates), issue=issue,
            analysis_path=analysis['path'], request_path=request_receipt['path'], request_sha256=request_receipt['sha256'])]))
        guard = gate()
        guard.update({key + '_sha256': sha(value) for key, value in payload.items()})
        census_rows.append(dict(attempt=row['attempt'], selection=row['selection'], request_exists=True,
                               request_receipt=request_receipt, analysis_receipt=analysis,
                               source_corpus_receipt=corpus, reconstruction=None, guard=guard))
        decision = dict(status='semantic_' + row['semantic_outcome'], request_id=request['id'],
                        alarm_eligible=row['semantic_outcome'] == 'supported', basis='UNUSED')
        put(item_dir / 'decision.json', decision)
        result = dict(selection=row['selection'], outcome=row['semantic_outcome'], decision=decision,
                      provider_calls=1, reserved_calls=0, measured_tokens=123, reserved_tokens=0, usage_missing=0,
                      artifacts={str(p.relative_to(directory)): replay.digest(p) for p in directory.rglob('*') if p.is_file()})
        result_receipts.append(put(directory / 'result.json', result))
    put(source / 'summary.json', dict(prepared=prepared_receipt, stage='complete', attempts=2,
        attempt_receipts=result_receipts, stop_reason='call_budget', counts=dict(supported=1),
        provider_calls=2, reserved_calls=0, measured_tokens=246, reserved_tokens=0, usage_missing=0,
        accounted_calls=2, accounted_tokens=246))
    guard_source = text(tmp_path / 'guard.py', '# frozen source gate')
    guard_test = text(tmp_path / 'guard_test.py', '# frozen gate tests')
    census_path = tmp_path / 'census.json'
    census_receipt = put(census_path, dict(version='csi-guard-source-recompute.v1',
        guard_source_receipt=guard_source, guard_test_receipt=guard_test, rows=census_rows))
    freeze_path = tmp_path / 'freeze.json'
    put(freeze_path, dict(version='csi-input-domain-guard-source-freeze.v1', files=[guard_source, guard_test, census_receipt]))
    return SimpleNamespace(source=source, census=census_path, guard_freeze=freeze_path, output=tmp_path / 'replay')


def test_prepare_and_run_preserve_exact_receipts_all_costs_and_zero_new_calls(tmp_path):
    args = archive_fixture(tmp_path)
    assert replay.prepare(args)['attempts'] == 2
    output = replay.run(SimpleNamespace(input=args.output))
    assert output['detector_alerts'] == 1 and output['historical_costs']['provider_calls'] == 2
    assert output['historical_costs']['measured_tokens'] == 246
    assert output['fresh_provider_calls'] == output['fresh_native_executions'] == output['budget_credit_or_refill'] == 0
    assert output['actual_fresh_budgeted_algorithm_run'] is False
    protocol = replay.read(args.output / 'prepared.json')
    assert len(protocol['attempts']) == 2
    assert all(r['call']['status'] == 'exact_archived_call_receipt' for r in protocol['attempts'])
    assert 'UNUSED' not in (args.output / 'prepared.json').read_text()


def test_run_rejects_changed_wire_even_if_guard_and_old_result_are_unchanged(tmp_path):
    args = archive_fixture(tmp_path)
    replay.prepare(args)
    wire = args.source / 'attempts/attempt_000000/admission/item_0000/completion/request.json'
    body = replay.read(wire)
    body['messages'][1]['content'] = 'changed full test'
    wire.write_text(json.dumps(body))
    with pytest.raises(ValueError, match='artifacts changed'):
        replay.run(SimpleNamespace(input=args.output))


def test_partial_census_cannot_be_used_as_alert_only_filter(tmp_path):
    args = archive_fixture(tmp_path)
    census = replay.read(args.census)
    census['rows'] = census['rows'][1:]
    args.census.write_text(json.dumps(census))
    freeze = replay.read(args.guard_freeze)
    freeze['files'][-1] = replay.frozen(args.census)
    args.guard_freeze.write_text(json.dumps(freeze))
    with pytest.raises(ValueError, match='every historical attempt'):
        replay.prepare(args)


def test_frozen_guard_cannot_be_changed_after_preparation(tmp_path):
    args = archive_fixture(tmp_path)
    replay.prepare(args)
    census = replay.read(args.census)
    census['rows'][1]['guard'] = gate('reject')
    args.census.write_text(json.dumps(census))
    with pytest.raises(ValueError, match='not in freeze'):
        replay.run(SimpleNamespace(input=args.output))


def reseal_fixture_attempt(args, index, result):
    """Build a different synthetic archive, not an edit to real experiment data."""
    directory = args.source / 'attempts' / f'attempt_{index:06d}'
    result['artifacts'] = {str(p.relative_to(directory)): replay.digest(p)
                           for p in directory.rglob('*') if p.is_file() and p.name != 'result.json'}
    (directory / 'result.json').write_text(json.dumps(result))
    summary = replay.read(args.source / 'summary.json')
    summary['attempt_receipts'][index] = replay.frozen(directory / 'result.json')
    for name in replay.COST_FIELDS:
        summary[name] = sum(replay.read(r['path'])[name] for r in summary['attempt_receipts'])
    summary['accounted_calls'] = summary['provider_calls'] + summary['reserved_calls']
    summary['accounted_tokens'] = summary['measured_tokens'] + summary['reserved_tokens']
    (args.source / 'summary.json').write_text(json.dumps(summary))


def test_cached_semantic_decision_for_another_request_cannot_transfer(tmp_path):
    args = archive_fixture(tmp_path)
    directory = args.source / 'attempts/attempt_000001'
    result = replay.read(directory / 'result.json')
    result['decision']['request_id'] = 'another_request'
    (directory / 'admission/item_0000/decision.json').write_text(json.dumps(result['decision']))
    reseal_fixture_attempt(args, 1, result)
    with pytest.raises(ValueError, match='different request'):
        replay.prepare(args)


def test_unrequested_source_attempt_remains_in_frozen_gate_denominator(tmp_path):
    args = archive_fixture(tmp_path)
    directory = args.source / 'attempts/attempt_000000'
    for path in list((directory / 'admission/item_0000/completion').iterdir()):
        path.unlink()
    (directory / 'admission/item_0000/completion').rmdir()
    (directory / 'admission/item_0000/request.json').unlink()
    (directory / 'dispatch_claim.json').unlink()
    prepared = replay.read(directory / 'admission/prepared.json')
    prepared['items'][0].update(request_path=None, request_sha256=None)
    (directory / 'admission/prepared.json').write_text(json.dumps(prepared))
    result = replay.read(directory / 'result.json')
    result.update(outcome='unknown', decision=dict(status='unknown', alarm_eligible=False),
                  provider_calls=0, measured_tokens=0)
    (directory / 'admission/item_0000/decision.json').write_text(json.dumps(result['decision']))
    reseal_fixture_attempt(args, 0, result)
    census = replay.read(args.census)
    census['rows'][0].update(request_exists=False, request_receipt=None)
    args.census.write_text(json.dumps(census))
    freeze = replay.read(args.guard_freeze)
    freeze['files'][-1] = replay.frozen(args.census)
    args.guard_freeze.write_text(json.dumps(freeze))
    replay.prepare(args)
    output = replay.run(SimpleNamespace(input=args.output))
    assert output['frozen_source_gate_attempts'] == 2 and output['detector_alerts'] == 1
    assert output['historical_costs']['provider_calls'] == 1
    assert replay.read(args.output / 'prepared.json')['attempts'][0]['call']['status'] == 'no_prepared_request'
