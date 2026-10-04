"""Read-only validation of the complete source-review then native protocol.

These are archive verification rules, not a new review, generation or execution.
The caller verifies the actual component algorithms at their immutable commit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from scripts import run_absence_null_search as source
from scripts import run_contract_repair_search as native_reader
from relation_search.candidate_edit_transport import verify_emission

VERSION = 'controlled-absence-null-search.v1'
COST = ('provider_calls', 'reserved_calls', 'measured_tokens', 'reserved_tokens', 'usage_missing')


def require(condition, message):
    if not condition:
        raise ValueError('Absence-null archive: ' + message)


def read(path):
    return json.loads(Path(path).read_text())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def exact(verifier, receipt, path):
    require(verifier.receipt(receipt, 'data') == Path(path).resolve(), 'receipt path differs: ' + str(path))
    return read(path)


def checkpoint(verifier, directory, *, input_receipts=None):
    """Expand explicit native checkpoint inventories; never open audit files."""
    path = directory / 'checkpoint.json'
    value = read(path)
    require(isinstance(value.get('files_sha256'), dict), 'native checkpoint missing inventory')
    for relative, digest in value['files_sha256'].items():
        target = (directory / relative).resolve()
        external = (input_receipts or {}).get(relative)
        require('audit' not in relative.lower() and (target.is_relative_to(directory.resolve()) or
            external == dict(path=str(target), sha256=digest)), 'unknown checkpoint edge')
        verifier.receipt(dict(path=str(target), sha256=digest), 'data')
    verifier.dependencies.append(dict(role='native_checkpoint_data', receipt=source.frozen(path),
        historical_parent_hash_recorded=False,
        boundary='Checkpoint bytes have no parent receipt in the original native outcome; its inventory is cross-checked against the sealed runs/outcome.'))


def projection(verifier, case):
    original = read(case['inputs']['corpus.json']['path'])
    if not case['candidates']:
        require(case.get('review_projection') is None and case.get('source_context') is None, 'unexpected empty-case review projection')
        return
    p = read(verifier.receipt(case['review_projection'], 'data'))
    require(p['version'] == 'repository-only-review-projection.v1', 'unknown source projection')
    require(p['original_inputs'] == {k: case['inputs'][k] for k in ('corpus.json','frontend.json')}, 'projection inputs differ')
    verifier.receipts(p)
    originals = {path: sha(row['code'].encode()) for path,row in original['sources'].items() if row.get('origin') == 'repository'}
    require(p['source_sha256'] == originals, 'projection is not exact repository source')
    require(p['excluded_source_count'] == len(original['sources'])-len(originals), 'projection exclusion count differs')
    require(p['source_context'] == case['source_context'], 'enrichment receipt differs')
    context = read(verifier.receipt(case['source_context'], 'data'))
    require(context['case_metadata'] == case['inputs']['case.json'], 'enrichment case metadata differs')
    require(context['original_source_sha256'] == originals, 'enrichment originals differ')
    metadata = read(case['inputs']['case.json']['path'])
    require(Path(context['repository']).resolve() == Path(metadata['repository']).resolve(), 'enrichment repository differs')
    added = context['added_sources']
    expected = dict(originals)
    for path, receipt in added.items():
        require(path not in originals, 'enrichment replaces original source')
        target = Path(context['repository']) / path
        require(target.resolve().is_relative_to(Path(context['repository']).resolve()), 'enrichment leaves repository')
        require(verifier.receipt(receipt, 'data') == target.resolve(), 'enrichment path differs')
        expected[path] = receipt['sha256']
    require(p['enriched_source_sha256'] == expected, 'enrichment sources differ')
    corpus, frontend = read(p['corpus']['path']), read(p['frontend']['path'])
    for view in (corpus, frontend):
        require(all(row.get('origin') == 'repository' for row in view['sources'].values()), 'historical source entered review')
        require({path:sha(row['code'].encode()) for path,row in view['sources'].items()} == expected, 'review source bytes differ')
    # Static projection is deterministic. Re-extract both views to reject stale
    # historical calls, capsules or source controls left in metadata.
    rebuilt, rebuilt_frontend, _ = source.repository_projection(corpus, frontend)
    require(rebuilt == corpus and rebuilt_frontend == frontend, 'review metadata is not repository projection')
    require(p['test_ids'] == sorted(test_id for test_id in corpus['tests'] if test_id in original['tests']), 'projection test inventory differs')
    verifier.dependencies.append(dict(role='repository_only_semantic_source', projection=case['review_projection'], enrichment=case['source_context']))


def semantic(verifier, protocol, summary, root, prepared_receipt):
    policy = protocol['semantic_policy']
    require(policy['method'] == source.review.VERSION and policy['ordering'] == 'source candidate ranks round robin over sorted trial names', 'unknown semantic policy')
    require(policy['native_outcomes_sent'] is False and policy['evaluation_labels_sent'] is False, 'non-source semantic input role')
    require(protocol['ordering'] == 'retrieval_rank, source path, value start byte' and protocol['max_candidates_per_trial'] == 16, 'unknown candidate order')
    require(protocol['stop'] == 'First controlled failure, then one repeat; stop even if the repeat does not confirm.', 'unknown native stop rule')
    value = exact(verifier, summary['semantic_summary'], root/'semantic_summary.json')
    require(value['prepared'] == prepared_receipt and value['stage'] == 'complete' and value['version'] == VERSION, 'semantic protocol identity differs')
    require(value['native_executions'] == 0 and value['trial_denominator'] == len(protocol['cases']), 'semantic cohort differs')
    ordered = list(source._review_entries(protocol))
    rows = value['results']
    require([(r['case'],r['rank']) for r in rows] == [(c['case'],e['rank']) for c,e in ordered], 'semantic decision order differs')
    require(len(value['result_receipts']) == len(rows), 'semantic receipt count differs')
    decisions, admitted, previous = {}, set(), []
    for (case,entry), row, receipt in zip(ordered, rows, value['result_receipts']):
        directory = root/'cases'/case['case']/f"candidate_{entry['rank']:04d}"/'review'
        require(exact(verifier, receipt, directory/'result.json') == row, 'semantic result bytes differ')
        require(row['artifacts'] == source._artifacts(directory), 'semantic artifact inventory differs')
        for relative,digest in row['artifacts'].items():
            verifier.receipt(dict(path=str(directory/relative),sha256=digest), 'data')
        require(row['program'] == entry['program'], 'reviewed program differs')
        analysis = exact(verifier, entry['analysis'], directory/'analysis.json')
        decision = exact(verifier, row['decision'], directory/'decision.json')
        cost = dict.fromkeys(COST,0)
        request = exact(verifier,entry['request'],directory/'request.json') if entry['request'] else None
        expected_decision = None
        claim = directory/'dispatch_claim.json'; manifest = directory/'completion/manifest.json'
        if request:
            require(request['id'] == source.admission._request_identity(request), 'request identity differs')
            require(request['max_tokens'] == policy['max_output_tokens'] and request['thinking'] == policy['thinking'] and request['reasoning_effort'] == policy['reasoning_effort'], 'request dispatch policy differs')
            reserve = source._reservation(request)
            if claim.exists():
                claimed = read(claim)
                require(claimed['request'] == entry['request'] and claimed['reserved_tokens'] == reserve and claimed['reserved_calls'] == 1, 'dispatch reservation differs')
                totals = source._totals(previous)
                require(totals['accounted_calls'] < policy['max_calls'] and totals['accounted_tokens']+reserve <= policy['max_total_tokens'], 'dispatch exceeded frozen budget')
                cost.update(reserved_calls=1,reserved_tokens=reserve,usage_missing=1)
            if manifest.exists():
                require(claim.exists(), 'completion has no dispatch claim')
                completion = read(manifest)
                require(completion['request_id'] == request['id'], 'completion request ID differs')
                wire = directory/'completion/request.json'
                require(sha(wire.read_bytes()) == completion['request_sha256'], 'wire request SHA differs')
                cost = source._cost(completion,reserve)
                expected_decision = source._unknown('provider_'+completion['status'])
                if completion['status'] == 'complete':
                    content = source.verified_completion(request,directory/'completion',completion)
                    expected_decision = source.review.decide(request,content,finish_reason=completion.get('finish_reason'))
            elif claim.exists():
                require(decision.get('status') == 'unknown' and decision.get('alarm_eligible') is False, 'incomplete dispatch admitted')
            else:
                require(decision == source._unknown('model_budget') or decision == source._unknown('deadline'), 'unclaimed request has semantic decision')
        else:
            require(not claim.exists() and not manifest.exists(), 'unprepared request was dispatched')
            expected_decision = source._unknown(analysis['status'])
        if expected_decision is not None:
            require(decision == expected_decision, 'decision differs from exact raw response')
        require(all(type(row[k]) is int and row[k] >= 0 and row[k] == cost[k] for k in COST), 'provider cost differs')
        supported = decision.get('status') == 'semantic_supported' and decision.get('alarm_eligible') is True
        require(row['admitted'] == supported and row['status'] == decision['status'], 'admission differs from decision')
        key = case['case'],entry['rank']; decisions[key] = row['decision']
        if supported: admitted.add(key)
        previous.append(row)
    require(all(value[k] == n for k,n in source._totals(rows).items()), 'semantic total cost differs')
    require(value['admitted'] == len(admitted), 'admission total differs')
    verifier.dependencies.append(dict(role='source_review_before_native', receipt=summary['semantic_summary'],
        result_receipts=value['result_receipts'], decision_order=[dict(case=r['case'],rank=r['rank']) for r in rows],
        provider_calls=value['provider_calls'], accounted_tokens=value['accounted_tokens']))
    return dict(admitted=admitted,decisions=decisions,provider_calls=value['provider_calls'])


def source_review(verifier, protocol, case):
    """Rebuild the frozen prompt locally; no provider judgment is requested."""
    if not case['candidates']:
        return
    projection = read(case['review_projection']['path'])
    corpus, frontend = read(projection['corpus']['path']), read(projection['frontend']['path'])
    issue = Path(case['inputs']['issue.md']['path']).read_text()
    policy = protocol['semantic_policy']
    for entry in case['candidates']:
        result = source.review.prepare(corpus,frontend,read(entry['program']['path']),issue,
            max_prompt_bytes=policy['max_prompt_bytes'],max_output_tokens=policy['max_output_tokens'])
        request = result.pop('request')
        require(result == read(entry['analysis']['path']), 'source review analysis differs from projected source')
        if request is not None:
            request = source.admission._configure_request(request,SimpleNamespace(
                thinking=policy['thinking'],output_token_limit=policy['max_output_tokens'],reasoning_effort=policy['reasoning_effort']))
        require(request == (read(entry['request']['path']) if entry['request'] else None),
                'review request differs from exact source-only reconstruction')


def native_phase(verifier, case, entry, phase, outcome, receipt, directory):
    require(exact(verifier,receipt,directory/'outcome.json') == outcome, 'native outcome differs')
    verifier.receipts(outcome)
    native = outcome.get('native')
    if native is None:
        require(not (directory/'native/native_outcome.json').exists(), 'unrecorded native outcome')
        return 0
    require(read(directory/'native/native_outcome.json') == native, 'native result differs from outcome')
    for name in ('prepared','emitted','executed'):
        checkpoint(verifier,directory/'native'/name,
                   input_receipts=case['inputs'] if name == 'prepared' else None)
    candidate = read(entry['program']['path'])
    corpus = read(case['inputs']['corpus.json']['path'])
    require(corpus['language'] == 'python', 'unsupported native language for this protocol')
    runs = exact(verifier,native['runs'],directory/'native/executed/runs.json')
    generated = [r for r in runs if r['role']=='generated' and r['candidate_id']==candidate['id']]
    require(bool(generated) and all(r['case']==case['case'] for r in runs), 'native run identity differs')
    for row in runs:
        require(Path(row['result']).resolve().is_relative_to((directory/'native/executed').resolve()),
                'native result points outside this execution phase')
        require(Path(row['manifest']).resolve().is_relative_to((directory/'native/emitted').resolve()),
                'native manifest points outside this execution phase')
        manifest = read(row['manifest'])
        for mount in manifest['mounts']:
            verifier.receipt(dict(path=mount['source'],sha256=mount['sha256']),'data')
    controls = native_reader.inspect_controls(generated,runs)
    tests,errors = [],[]
    for row in generated:
        found, issues, _ = native_reader.native(row['result'])
        tests.extend(t for t in found if any(native_reader.matches_runtime(t['id'],name) for name in row['test_ids']))
        errors.extend(issues)
    failure = bool(tests and any(t['status'] in {'fail','error'} for t in tests) and not errors and controls['status']=='all_source_controls_passed')
    require(native == dict(candidate_id=candidate['id'],controls=controls,tests=tests,parser_errors=errors,runs=native['runs'],controlled_failure=failure), 'native classifications differ from normalized tests')
    require(len({str(Path(r['manifest']).parent) for r in generated})==1, 'multiple native emissions unsupported')
    emission = Path(generated[0]['manifest']).parent
    require(verify_emission(corpus,candidate,emission) == outcome['transport'], 'complete native transport differs')
    return 1


def validate(verifier, protocol, summary, prepared_receipt, root):
    cases = protocol['cases']; names = [c['case'] for c in cases]
    require(names == sorted(names), 'trial order differs')
    require(summary['trial_denominator'] == protocol['trial_denominator'] == len(cases), 'trial denominator differs')
    require(source._read_sealed(root/'summary.json') == summary, 'summary seal differs')
    sources = verifier.source_inventory(protocol)
    for case in cases:
        entries = case['candidates']
        require([e['rank'] for e in entries] == list(range(1,len(entries)+1)) and len(entries)<=16, 'candidate rank differs')
        require([e['order'] for e in entries] == sorted(e['order'] for e in entries), 'candidate source order differs')
        projection(verifier,case)
        source_review(verifier,protocol,case)
        for entry in entries:
            require(read(entry['program']['path'])['order'] == entry['order'], 'program source order differs')
    sem = semantic(verifier,protocol,summary,root,prepared_receipt)
    require([r['case'] for r in summary['results']] == names and len(summary['result_receipts'])==len(cases), 'native cohort differs')
    count = 0; index = {}
    for case,row,receipt in zip(cases,summary['results'],summary['result_receipts']):
        directory = root/'cases'/case['case']
        require(exact(verifier,receipt,directory/'result.json') == row, 'case result receipt differs')
        require(source._verified_case_result(directory,case,sem) == row, 'case result seal differs')
        entries = [e for e in case['candidates'] if (case['case'],e['rank']) in sem['admitted']]
        attempts = row['attempts']
        require([a['rank'] for a in attempts] == [e['rank'] for e in entries[:len(attempts)]], 'native did not follow admitted prefix')
        expected_alert = None; stop = case['status']; stopped = False
        for i,(attempt,entry) in enumerate(zip(attempts,entries)):
            require(not stopped, 'native continued after first failure or failed control')
            require(attempt['program'] == entry['program'], 'native program differs')
            candidate_dir = directory/f"candidate_{entry['rank']:04d}"
            initial = attempt['initial']
            count += native_phase(verifier,case,entry,'initial',initial,attempt['initial_receipt'],candidate_dir/'initial')
            native = initial.get('native')
            if native is None: stop='emission_or_transport_unavailable'
            elif native['controls']['status']!='all_source_controls_passed': stop='source_control_unavailable_or_failed'; stopped=True
            elif source._controlled(initial):
                stop='first_failure_unconfirmed'; stopped=True
                if 'confirmation' in attempt:
                    count += native_phase(verifier,case,entry,'confirmation',attempt['confirmation'],attempt['confirmation_receipt'],candidate_dir/'confirmation')
                    if source._controlled(attempt['confirmation']):
                        expected_alert=dict(program=entry['program'],initial=attempt['initial_receipt'],confirmation=attempt['confirmation_receipt'],semantic=sem['decisions'][case['case'],entry['rank']],validity='pending_independent_full_test_audit')
                        stop='repeated_admitted_absence_null_failure'
            else: stop='candidate_budget_exhausted'
            require('confirmation' not in attempt or source._controlled(initial), 'confirmation of nonfailure')
        require(row['alert'] == expected_alert, 'emitted alert differs from admitted repeated failure')
        if len(attempts)<len(entries) and not stopped:
            require(row['stop_reason']=='execution_budget', 'admitted prefix ended without budget reason')
        else: require(row['stop_reason']==stop, 'native stop reason differs')
        index[case['case']]=row
    observed=list((root/'cases').glob('*/candidate_*/**/native_outcome.json'))
    require(count == len(observed) == summary['native_executions'] and count<=protocol['max_native_executions'], 'native cost or unrecorded execution differs')
    require(summary['external_model_calls']==sem['provider_calls'] and summary['detector_alerts']==sum(bool(r['alert']) for r in index.values()), 'output accounting differs')
    verifier.dependencies.append(dict(role='admitted_native_prefix', result_receipts=summary['result_receipts'],native_executions=count,
        order='Each trial uses the supported source-rank prefix and stops at its first controlled failure, regardless of confirmation.'))
    return dict(cases=names,sources=sources,index=index,summary=summary)
