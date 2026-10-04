"""Replay a frozen CSI source gate over the complete observed semantic prefix.

This command never imports a provider or runs subject code. It does not refill
an exhausted historical budget. Missing future ranks remain pending. Independent
validity audits and provider explanations are not inputs to selection.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

VERSION = 'csi-guarded-historical-prefix.v1'
COST_FIELDS = ('provider_calls', 'reserved_calls', 'measured_tokens', 'reserved_tokens', 'usage_missing')
POLICY = dict(
    evaluation='bounded_historical_prefix_replay',
    ordering='unchanged_source_rank_within_each_original_trial',
    emission='first_observed_semantic_supported_with_frozen_guard_allow',
    missing_prefix='pending_abstention_without_refill_or_future_lookup',
    unknown_guard='withhold; never convert unknown to allow',
    costs='retain all original actual and reserved costs; no counterfactual budget credit',
    guard_scope='allow includes outside_registered_scope; neither proves full-test validity',
    development='retrospective development replay; guard designed after earlier audits',
)


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def frozen(path):
    return dict(path=str(Path(path).resolve()), sha256=digest(path))


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Verifier:
    """Cache hashes only for this read-only validation pass."""
    def __init__(self):
        self.hashes = {}
        self.sources = {}

    def receipt(self, receipt):
        path = str(Path(receipt['path']).resolve())
        if path not in self.hashes:
            self.hashes[path] = digest(path)
        if self.hashes[path] != receipt['sha256']:
            raise ValueError('Changed receipt: ' + path)
        return dict(path=path, sha256=self.hashes[path])

    def source_hashes(self, receipt, field):
        self.receipt(receipt)
        key = (receipt['path'], field)
        if key not in self.sources:
            rows = read(receipt['path'])[field]
            self.sources[key] = {path: hashlib.sha256(row['code'].encode()).hexdigest()
                                 for path, row in rows.items()}
        return self.sources[key]


def guard_allows(guard):
    expected = {'outside_registered_scope': 'allow', 'bounded_input_domain_checked': 'allow',
                'positive_keyboard_input_contradicts_domain': 'reject',
                'input_domain_or_binding_unproved': 'unknown'}
    if not isinstance(guard, dict):
        raise ValueError('Missing frozen source gate')
    if (guard.get('version') != 'source-bound-csi-input-domain.v1'
            or expected.get(guard.get('status')) != guard.get('decision')
            or guard.get('decision') not in {'allow', 'reject', 'unknown'}):
        raise ValueError('Invalid frozen source gate state')
    allowed = guard['decision'] == 'allow'
    if guard.get('allow_prior_gate') is not allowed:
        raise ValueError('Inconsistent source gate permission')
    return allowed


def dispatch_identity(request):
    fields = {k: request[k] for k in ('system', 'prompt', 'thinking', 'max_tokens')}
    if 'reasoning_effort' in request:
        fields['reasoning_effort'] = request['reasoning_effort']
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def call_provenance(directory, result, item, row, verifier):
    request_path = directory / 'admission/item_0000/request.json'
    if bool(item['request_path']) != row['request_exists'] or request_path.exists() != row['request_exists']:
        raise ValueError('Census request existence differs')
    if not row['request_exists']:
        if row['request_receipt'] is not None or result['provider_calls']:
            raise ValueError('Provider call without a prepared request')
        return dict(status='no_prepared_request', actual_provider_calls=0)
    receipt = verifier.receipt(row['request_receipt'])
    if (receipt['path'] != str(request_path.resolve()) or item['request_path'] != receipt['path']
            or item['request_sha256'] != receipt['sha256']):
        raise ValueError('Prepared request differs from frozen census')
    request = read(request_path)
    if (request['request_identity_version'] != 'actual-admission-dispatch-fields-v1'
            or request['id'] != dispatch_identity(request) or request['query_sha256'] != request['id']
            or request['candidate_id'] != result['selection']['candidate_id']):
        raise ValueError('Semantic request identity differs')
    decision = result['decision']
    if (decision.get('request_id') not in {None, request['id']}
            or (result['outcome'] == 'supported' and decision.get('request_id') != request['id'])):
        raise ValueError('Semantic decision refers to a different request')
    standalone = read(request_path.with_name('decision.json'))
    if any(standalone.get(k) != decision.get(k) for k in ('status', 'alarm_eligible', 'request_id')):
        raise ValueError('Standalone semantic decision differs')
    payload = json.loads(request['prompt'])
    for field in ('original_test', 'modified_test'):
        if hashlib.sha256(payload[field].encode()).hexdigest() != row['guard'][field + '_sha256']:
            raise ValueError('Source gate evaluated a different complete test')
    sources = dict(verifier.source_hashes(item['source_inputs']['corpus'], 'sources'))
    if item.get('source_context'):
        sources.update(verifier.source_hashes(item['source_context'], 'added_sources'))
    if any(sources.get(path) != sha for path, sha in request['source_sha256'].items()):
        raise ValueError('Semantic request source hashes differ')
    provenance = dict(status='prepared_without_call_receipt', request=receipt,
                      request_id=request['id'], candidate_sha256=request['candidate_sha256'],
                      source_sha256=request['source_sha256'], actual_provider_calls=result['provider_calls'])
    manifest_path = request_path.parent / 'completion/manifest.json'
    if not manifest_path.exists():
        if result['provider_calls'] or result['outcome'] == 'supported':
            raise ValueError('Counted provider call lacks receipt')
        return provenance
    claim = read(directory / 'dispatch_claim.json')
    if claim['request'] != receipt or claim['reserved_calls'] != 1:
        raise ValueError('Dispatch claim differs')
    expected_reservation = len(request['system'].encode()) + len(request['prompt'].encode()) + request['max_tokens'] + 256
    if claim['reserved_tokens'] != expected_reservation:
        raise ValueError('Dispatch token reservation differs')
    wire_path = manifest_path.with_name('request.json')
    wire, manifest = read(wire_path), read(manifest_path)
    if (wire['messages'] != [dict(role='system', content=request['system']), dict(role='user', content=request['prompt'])]
            or wire['thinking'] != dict(type=request['thinking'])
            or wire.get('reasoning_effort') != request.get('reasoning_effort')
            or wire['max_tokens'] != request['max_tokens']):
        raise ValueError('Wire payload differs from exact prepared request')
    if (manifest['request_sha256'] != digest(wire_path) or manifest['request_id'] != request['id']
            or manifest['thinking'] != request['thinking']
            or manifest.get('reasoning_effort') != request.get('reasoning_effort')
            or manifest['max_output_tokens'] != request['max_tokens']
            or manifest['model'] != wire['model']
            or manifest['external_model_calls'] != result['provider_calls']):
        raise ValueError('Provider receipt differs from request or call accounting')
    if manifest.get('response_sha256') != digest(manifest_path.with_name('response.body')):
        raise ValueError('Provider response bytes differ from receipt')
    usage = manifest.get('usage') or {}
    if not result['usage_missing'] and usage.get('total_tokens') != result['measured_tokens']:
        raise ValueError('Actual token usage differs')
    provenance.update(status='exact_archived_call_receipt', wire_request=frozen(wire_path),
                      manifest=frozen(manifest_path), dispatch_claim=frozen(directory / 'dispatch_claim.json'),
                      usage=usage, model=manifest['model'], reasoning_effort=manifest.get('reasoning_effort'),
                      thinking=manifest['thinking'], max_output_tokens=manifest['max_output_tokens'])
    return provenance


def next_original(cases, rows, maximum):
    counts = Counter(r['selection']['case'] for r in rows)
    solved = {r['selection']['case'] for r in rows if r['semantic_outcome'] == 'supported'}
    names = [c['case'] for c in cases]
    start = (names.index(rows[-1]['selection']['case']) + 1) % len(names) if rows else 0
    for offset in range(len(names)):
        case = cases[(start + offset) % len(names)]
        count = counts[case['case']]
        if case['case'] not in solved and count < min(maximum, len(case['ranking'])):
            return dict(case=case['case'], **case['ranking'][count])
    return None


def load_source(source, census_path, guard_freeze_path):
    """Read machine outcomes and exact receipts, never explanatory/audit fields."""
    source = Path(source).resolve()
    verifier = Verifier()
    base, summary = read(source / 'prepared.json'), read(source / 'summary.json')
    base_receipt = frozen(source / 'prepared.json')
    if (read(source / 'seal.json') != dict(prepared=base_receipt)
            or summary['prepared'] != base_receipt
            or base['version'] != 'sequential-source-admission.v1' or summary['stage'] != 'complete'):
        raise ValueError('Unsealed or incomplete historical experiment')
    cases = base['cases']
    if len({c['case'] for c in cases}) != len(cases) or not cases:
        raise ValueError('Duplicate or empty trial cohort')
    for case in cases:
        ranks = case['ranking']
        if ([e['rank'] for e in ranks] != list(range(1, len(ranks) + 1))
                or len({e['key'] for e in ranks}) != len(ranks)):
            raise ValueError('Source rankings must be complete and contiguous')
    for receipt in [base['inventory'], *base['source_inputs']]:
        verifier.receipt(receipt)
    census, guard_freeze = read(census_path), read(guard_freeze_path)
    if (census['version'] != 'csi-guard-source-recompute.v1'
            or guard_freeze['version'] != 'csi-input-domain-guard-source-freeze.v1'):
        raise ValueError('Unsupported source gate census')
    frozen_files = {str(Path(r['path']).resolve()): r for r in guard_freeze['files']}
    for receipt in [frozen(census_path), census['guard_source_receipt'], census['guard_test_receipt']]:
        verifier.receipt(receipt)
        sealed = frozen_files.get(str(Path(receipt['path']).resolve()))
        if not sealed or sealed['sha256'] != receipt['sha256']:
            raise ValueError('Source gate census or algorithm not in freeze')
    receipts = summary['attempt_receipts']
    if len(receipts) != summary['attempts'] or len(census['rows']) != len(receipts):
        raise ValueError('Source gate must cover every historical attempt')
    census_index = {r['attempt']: r for r in census['rows']}
    if len(census_index) != len(receipts):
        raise ValueError('Duplicate census attempt')
    directories = sorted((source / 'attempts').iterdir())
    if [p.name for p in directories] != [f'attempt_{i:06d}' for i in range(len(receipts))]:
        raise ValueError('Historical attempt directory prefix differs')
    rows = []
    for i, result_receipt in enumerate(receipts):
        directory = directories[i]
        if verifier.receipt(result_receipt) != frozen(directory / 'result.json'):
            raise ValueError('Attempt receipt order differs')
        result, gate = read(result_receipt['path']), census_index.get(directory.name)
        selection = result['selection']
        if (not gate or gate['selection'] != selection or read(directory / 'selection.json') != selection
                or selection != next_original(cases, rows, base['policy']['max_per_case'])):
            raise ValueError('Source gate or historical round-robin selection differs')
        actual_artifacts = {str(p.relative_to(directory)): digest(p) for p in directory.rglob('*')
                            if p.is_file() and p != directory / 'result.json'}
        if actual_artifacts != result['artifacts']:
            raise ValueError('Historical attempt artifacts changed')
        outcome = result['outcome']
        # These are machine status fields. No basis or independent audit is read.
        decision = result['decision']
        expected = ('supported' if decision.get('status') == 'semantic_supported' and decision.get('alarm_eligible') is True
                    else 'rejected' if decision.get('status') == 'semantic_rejected' else 'unknown')
        if outcome != expected:
            raise ValueError('Historical semantic status differs')
        if any(type(result[f]) is not int or result[f] < 0 for f in COST_FIELDS):
            raise ValueError('Invalid historical cost')
        guard_allows(gate['guard'])
        verifier.receipt(gate['analysis_receipt'])
        verifier.receipt(gate['source_corpus_receipt'])
        prepared = read(directory / 'admission/prepared.json')
        if len(prepared['items']) != 1:
            raise ValueError('Historical attempt must contain one full test')
        item = prepared['items'][0]
        if any(item[k] != selection[k] for k in ('case', 'candidate_id', 'key')):
            raise ValueError('Prepared candidate differs')
        if item['source_inputs']['corpus'] != gate['source_corpus_receipt']:
            raise ValueError('Guard source corpus differs')
        if item['analysis_path'] != gate['analysis_receipt']['path']:
            raise ValueError('Guard source analysis differs')
        for name in ('corpus', 'frontend', 'candidates'):
            verifier.receipt(item['source_inputs'][name])
        verifier.receipt(item['issue'])
        row = dict(attempt=directory.name, selection=selection, semantic_outcome=outcome,
                   original_result=result_receipt, source_gate=gate, call=call_provenance(directory, result, item, gate, verifier),
                   source_inputs={name: item['source_inputs'][name] for name in ('corpus', 'frontend', 'candidates')},
                   issue=item['issue'], costs={f: result[f] for f in COST_FIELDS})
        rows.append(row)
    totals = {f: sum(r['costs'][f] for r in rows) for f in COST_FIELDS}
    if any(totals[f] != summary[f] for f in COST_FIELDS):
        raise ValueError('Historical aggregate costs differ')
    totals.update(accounted_calls=totals['provider_calls'] + totals['reserved_calls'],
                  accounted_tokens=totals['measured_tokens'] + totals['reserved_tokens'])
    if any(totals[f] != summary[f] for f in ('accounted_calls', 'accounted_tokens')):
        raise ValueError('Historical budget accounting differs')
    if summary['counts'].get('supported', 0) != sum(r['semantic_outcome'] == 'supported' for r in rows):
        raise ValueError('Historical support count differs')
    return dict(cases=cases, attempts=rows, historical_costs=totals, historical_stop_reason=summary['stop_reason'],
                historical_policy=base['policy'], original_algorithm=base['algorithm'],
                source_inputs=base['source_inputs'], source_ranking_policy_sha256=base['source_ranking_policy_sha256'],
                source_prepared=base_receipt, source_summary=frozen(source / 'summary.json'),
                census=frozen(census_path), guard_freeze=frozen(guard_freeze_path))


def derive(cases, rows, maximum):
    """Missing rank terminates a trial even if later observations exist."""
    observed = {(r['selection']['case'], r['selection']['rank']): r for r in rows}
    if len(observed) != len(rows):
        raise ValueError('Duplicate observed trial rank')
    expected = {(c['case'], e['rank']): dict(case=c['case'], **e) for c in cases for e in c['ranking']}
    if any(key not in expected or row['selection'] != expected[key] for key, row in observed.items()):
        raise ValueError('Observed candidate differs from declared cohort/ranking')
    results = []
    for case in cases:
        result = dict(case=case['case'], status='abstain', alert=None, observed_attempts=[], next_unobserved=None,
                      stop_reason='per_case_budget_or_source_exhausted')
        for entry in case['ranking'][:maximum]:
            row = observed.get((case['case'], entry['rank']))
            if row is None:
                result.update(status='pending', stop_reason='required_semantic_prefix_not_observed',
                              next_unobserved=dict(case=case['case'], **entry))
                break
            guard = row['source_gate']['guard']
            allowed = guard_allows(guard)
            result['observed_attempts'].append(dict(attempt=row['attempt'], rank=entry['rank'],
                semantic_outcome=row['semantic_outcome'], guard_decision=guard['decision'], guard_status=guard['status']))
            if row['semantic_outcome'] == 'supported' and allowed:
                result.update(status='emitted', stop_reason='first_observed_supported_and_guard_allowed',
                              alert=dict(selection=row['selection'], original_result=row['original_result'],
                                         source_gate_attempt=row['attempt'], request=row['call'].get('request'),
                                         validity='pending_independent_full_test_audit'))
                break
        results.append(result)
    return results


def algorithm():
    root = Path(__file__).resolve().parents[1]
    return [frozen(__file__), frozen(root / 'tests/test_csi_guarded_prefix_replay.py')]


def prepare(args):
    source = load_source(args.source, args.census, args.guard_freeze)
    record = dict(version=VERSION, policy=POLICY, algorithm=algorithm(), **source,
                  trial_denominator=len(source['cases']), created_utc=datetime.now(timezone.utc).isoformat(),
                  fresh_provider_calls=0, fresh_native_executions=0, evaluation_labels_used=False,
                  actual_fresh_budgeted_algorithm_run=False)
    Path(args.output).mkdir(parents=True, exist_ok=False)
    write_new(Path(args.output) / 'prepared.json', record)
    write_new(Path(args.output) / 'seal.json', frozen(Path(args.output) / 'prepared.json'))
    return dict(trials=record['trial_denominator'], attempts=len(record['attempts']),
                mode=POLICY['evaluation'], fresh_provider_calls=0, fresh_native_executions=0)


def run(args):
    directory = Path(args.input)
    prepared = read(directory / 'prepared.json')
    if (prepared['version'] != VERSION or prepared['policy'] != POLICY
            or read(directory / 'seal.json') != frozen(directory / 'prepared.json')
            or prepared['algorithm'] != algorithm()):
        raise ValueError('Changed replay protocol or implementation')
    source = load_source(Path(prepared['source_prepared']['path']).parent,
                         prepared['census']['path'], prepared['guard_freeze']['path'])
    if any(prepared[k] != v for k, v in source.items()):
        raise ValueError('Changed historical prefix or frozen source gate')
    results = derive(prepared['cases'], prepared['attempts'], prepared['historical_policy']['max_per_case'])
    output = dict(version=VERSION, prepared=frozen(directory / 'prepared.json'), results=results,
                  trial_denominator=len(results), detector_alerts=sum(r['alert'] is not None for r in results),
                  trial_states=dict(Counter(r['status'] for r in results)),
                  frozen_source_gate_attempts=len(prepared['attempts']),
                  source_gate_counts=dict(Counter(r['source_gate']['guard']['decision'] for r in prepared['attempts'])),
                  historical_costs=prepared['historical_costs'], historical_stop_reason=prepared['historical_stop_reason'],
                  fresh_provider_calls=0, fresh_native_executions=0, budget_credit_or_refill=0,
                  mode=POLICY['evaluation'], actual_fresh_budgeted_algorithm_run=False,
                  retrospective=True, evaluation_labels_used=False, independent_audit_complete=False)
    write_new(directory / 'summary.json', output)
    write_new(directory / 'summary_seal.json', frozen(directory / 'summary.json'))
    return {k: v for k, v in output.items() if k != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--census', type=Path)
    parser.add_argument('--guard-freeze', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    required = ('source', 'census', 'guard_freeze', 'output') if args.stage == 'prepare' else ('input',)
    if any(getattr(args, key) is None for key in required):
        parser.error('Required arguments: ' + ', '.join('--' + key.replace('_', '-') for key in required))
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
