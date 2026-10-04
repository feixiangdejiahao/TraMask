"""Review complete single-row source recombinations before native execution.

All candidates keep a frozen source order. Model judgments use public source
only; only supported tests execute. Native failure never enters that judgment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import table_row_recombination as relation
from relation_search import compact_contract_guarded as review
from relation_search.source_frontend_refresh import refresh
from relational_gap.frontend import to_emitter_corpus
from relational_gap.provider import dispatch
from scripts.discover_quantity_bounds import _cost, _totals, _reservation, _artifacts
from types import SimpleNamespace
import fcntl
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import frozen, verify, write
from scripts.run_documented_default_search import one_run

VERSION = 'controlled-table-row-recombination-search.v1'
EXPECTED_TRIALS = 17


def _verify_algorithm(protocol):
    admission._preload_local_imports(sys.modules[__name__])
    entrypoints = protocol.get('algorithm_entrypoints', {})
    if set(entrypoints) != {'driver', 'constructor', 'semantic_reviewer', 'native_adapter', 'provider_adapter'}:
        raise ValueError('Missing explicit executed entrypoint receipts')
    recorded = {(row['path'], row['sha256']) for row in protocol['algorithm'].values()}
    if any((row['path'], row['sha256']) not in recorded for row in entrypoints.values()):
        raise ValueError('Executed entrypoint missing from imported algorithm seal')
    admission._verify_sources(entrypoints, protocol['algorithm'])


def _verify_protocol(protocol):
    if protocol.get('version') != VERSION:
        raise ValueError('Unsupported protocol')
    names = [case['case'] for case in protocol['cases']]
    if names != sorted(set(names)) or len(names) != protocol['trial_denominator']:
        raise ValueError('Protocol cohort order or denominator differs')
    if protocol['max_candidates_per_trial'] != 16:
        raise ValueError('Unexpected per-trial candidate budget')
    for case in protocol['cases']:
        entries = case['candidates']
        if len(entries) > 16 or [e['rank'] for e in entries] != list(range(1, len(entries)+1)):
            raise ValueError('Candidate ranks are not a complete source prefix')
        if [e['order'] for e in entries] != sorted(e['order'] for e in entries):
            raise ValueError('Frozen candidate order differs')


def repository_projection(corpus, frontend):
    """Rebuild review metadata from exactly repository-origin source bytes.

    Filtering the source map alone would leave historical calls, controls and
    capsules in the old frontend/corpus. Re-extraction removes those records.
    Generation and native execution retain their original frozen snapshots.
    """
    sources = {path: row for path, row in corpus['sources'].items()
               if row.get('origin') == 'repository'}
    tests = {key: row for key, row in corpus['tests'].items()
             if row['span']['path'] in sources}
    base = dict(language=corpus['language'], sources=sources, tests=tests)
    projected_frontend = refresh(base, frontend)
    projected = to_emitter_corpus(projected_frontend)
    for key, row in projected['tests'].items():
        if key in tests:
            row['retrieval_rank'] = tests[key].get('retrieval_rank')
    provenance = dict(version='repository-only-review-projection.v1',
        criterion='Only sources whose original origin is repository; rebuild tests, calls, capsules and controls from those exact bytes.',
        excluded_source_count=len(corpus['sources'])-len(sources),
        source_sha256={path: hashlib.sha256(row['code'].encode()).hexdigest()
                       for path, row in sorted(sources.items())},
        test_ids=sorted(projected['tests']),
        native_policy='Original frozen source snapshots and fixed original repository test IDs; exact complete-test transport remains mandatory.')
    return projected, projected_frontend, provenance


def _verify_nested_receipts(value):
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and 'sha256' in value:
            verify(value)
        for item in value.values():
            _verify_nested_receipts(item)
    elif isinstance(value, list):
        for item in value:
            _verify_nested_receipts(item)


def _verify_case_inputs(case):
    for receipt in [*case['inputs'].values(), case['generation']]:
        verify(receipt)
    if case.get('source_context'):
        verify(case['source_context'])
    if case.get('review_projection'):
        verify(case['review_projection'])
        projection = read(case['review_projection']['path'])
        if projection['original_inputs'] != {key: case['inputs'][key] for key in ('corpus.json', 'frontend.json')}:
            raise ValueError('Review projection source inputs differ')
        _verify_nested_receipts(projection)


def _read_sealed(path):
    seal = read(path.with_name(path.stem+'_seal.json'))
    if seal != frozen(path):
        raise ValueError('Completed artifact seal differs: '+str(path))
    verify(seal)
    return read(path)


def _verified_case_result(directory, case, semantic):
    result = _read_sealed(directory/'result.json')
    if result['case'] != case['case']:
        raise ValueError('Completed native case differs')
    entries = {entry['rank']: entry for entry in case['candidates']}
    admitted_ranks = [rank for rank in entries if (case['case'], rank) in semantic['admitted']]
    if [row['rank'] for row in result['attempts']] != admitted_ranks[:len(result['attempts'])]:
        raise ValueError('Completed native ranks differ from admitted source order')
    expected_alert = None
    for index, attempt in enumerate(result['attempts']):
        rank = attempt['rank']
        if ((case['case'], rank) not in semantic['admitted']
                or attempt['program'] != entries[rank]['program']):
            raise ValueError('Completed native attempt was not admitted')
        for phase in ('initial', 'confirmation'):
            if phase in attempt:
                receipt = attempt[phase+'_receipt']
                expected_path = directory/f'candidate_{rank:04d}'/phase/'outcome.json'
                if receipt != frozen(expected_path) or _read_sealed(expected_path) != attempt[phase]:
                    raise ValueError('Completed native outcome differs')
        failed = _controlled(attempt['initial'])
        controls = (attempt['initial'].get('native') or {}).get('controls', {}).get('status')
        if (failed or controls not in {None, 'all_source_controls_passed'}) and index != len(result['attempts'])-1:
            raise ValueError('Completed native trace continued after its stop condition')
        if 'confirmation' in attempt and not failed:
            raise ValueError('Confirmation has no admitted initial controlled failure')
        if failed and _controlled(attempt.get('confirmation', {})):
            expected_alert = dict(program=entries[rank]['program'],
                initial=attempt['initial_receipt'], confirmation=attempt['confirmation_receipt'],
                semantic=semantic['decisions'][case['case'], rank], validity='pending_independent_full_test_audit')
    if result['alert'] != expected_alert:
        raise ValueError('Completed native alert differs from its repeated admitted failure')
    _verify_nested_receipts(result)
    return result


def collect(args, *, freeze):
    source_seal = read(args.source_cohort/'seal.json')
    if source_seal != frozen(args.source_cohort/'prepared.json'):
        raise ValueError('Source cohort seal points to another protocol')
    verify(source_seal)
    previous = read(args.source_cohort/'prepared.json')
    sources = {}
    for row in previous.get('items', previous.get('cases', [])):
        if (not isinstance(row.get('case'), str) or row['case'] in {'.', '..'}
                or not re.fullmatch(r'[A-Za-z0-9_.-]+', row['case'])):
            raise ValueError('Invalid trial name')
        if sources.setdefault(row['case'], row['source']) != row['source']:
            raise ValueError('One original source snapshot per trial is required')
    if len(sources) != EXPECTED_TRIALS:
        raise ValueError('Complete seventeen-trial source cohort required')
    deadline = admission._deadline(args.deadline_utc) if freeze else None
    if freeze and deadline is None:
        raise ValueError('Deadline required')
    args.output.mkdir(parents=True, exist_ok=False)
    # Include the actual driver and native/provider adapter implementations,
    # including literal local imports inside those helpers.
    admission._preload_local_imports(sys.modules[__name__])
    algorithm = admission._loaded_sources()
    cases = []
    for case, name in sorted(sources.items()):
        source = Path(name)
        inputs = {item: frozen(source/item) for item in
                  ['corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md']}
        generated = relation.generate(read(source/'corpus.json'), read(source/'frontend.json'),
                                      (source/'issue.md').read_text(), limit=16)
        programs = generated.pop('candidates')
        if (len(programs) > 16 or [p['order'] for p in programs] != sorted(p['order'] for p in programs)
                or len({p['id'] for p in programs}) != len(programs)):
            raise ValueError('Constructor changed candidate budget or source order')
        directory = args.output/'cases'/case
        entries = []
        corpus = read(source/'corpus.json'); frontend = read(source/'frontend.json')
        issue = (source/'issue.md').read_text()
        enriched = projection_receipt = None
        if freeze and programs:
            corpus, frontend, projection = repository_projection(corpus, frontend)
            corpus, enriched = admission._enrich(corpus, frontend,
                {candidate['id']: candidate for candidate in programs},
                source/'corpus.json', args.output, len(cases))
            # Enrichment adds only explicit repository dependencies. Refresh
            # both metadata views so review controls cannot use stale graphs.
            corpus, frontend, enriched_projection = repository_projection(corpus,
                dict(frontend, sources=corpus['sources']))
            projection_directory = directory/'review_projection'
            write(projection_directory/'corpus.json', corpus)
            write(projection_directory/'frontend.json', frontend)
            projection.update(original_inputs={key: inputs[key] for key in ('corpus.json', 'frontend.json')},
                enriched_source_sha256=enriched_projection['source_sha256'],
                source_context=enriched,
                corpus=frozen(projection_directory/'corpus.json'),
                frontend=frozen(projection_directory/'frontend.json'))
            write(projection_directory/'manifest.json', projection)
            projection_receipt = frozen(projection_directory/'manifest.json')
        for rank, candidate in enumerate(programs, 1):
            if freeze and candidate['base_test_id'] not in corpus['tests']:
                raise ValueError('Candidate test missing from repository projection')
            path = directory/f'candidate_{rank:04d}'/'program.json'
            write(path, candidate)
            entry = dict(rank=rank, program=frozen(path), order=candidate['order'])
            if freeze:
                result = review.prepare(corpus, frontend, candidate, issue,
                    max_prompt_bytes=96000, max_output_tokens=16384)
                request = result.pop('request')
                destination = path.parent/'review'
                write(destination/'analysis.json', result)
                if request is not None:
                    request = admission._configure_request(request, SimpleNamespace(
                        thinking='enabled', output_token_limit=16384, reasoning_effort='high'))
                    write(destination/'request.json', request)
                entry.update(analysis=frozen(destination/'analysis.json'),
                    request=frozen(destination/'request.json') if request is not None else None)
            entries.append(entry)
        write(directory/'generation.json', generated)
        cases.append(dict(case=case, source=str(source.resolve()), inputs=inputs,
                          generation=frozen(directory/'generation.json'), candidates=entries,
                          status=generated['status'], source_context=enriched,
                          review_projection=projection_receipt))
        print(json.dumps(dict(case=case, selected=len(entries), total=generated['total_candidates'],
                              status=generated['status'], rejected=len(generated['skipped']))), flush=True)
    admission.verify_seal(algorithm)
    if set(admission._loaded_sources())-set(algorithm):
        raise ValueError('Unrecorded local source imported')
    record = dict(version=VERSION, policy=relation.POLICY, algorithm=algorithm,
        algorithm_entrypoints={name: frozen(path) for name, path in {
            'driver': __file__, 'constructor': relation.__file__, 'semantic_reviewer': review.__file__,
            'native_adapter': sys.modules[one_run.__module__].__file__,
            'provider_adapter': sys.modules[dispatch.__module__].__file__,
        }.items()},
        cases=cases, trial_denominator=len(cases), source_cohort=frozen(args.source_cohort/'prepared.json'),
        source_cohort_use='Only original snapshot paths and the full trial list; no old candidates or outcomes.',
        max_candidates_per_trial=16, external_model_calls=0, evaluator_labels_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    if freeze:
        record.update(max_native_executions=17*len(cases), timeout=180, deadline_utc=deadline.isoformat(),
            semantic_policy=dict(method=review.VERSION, max_calls=64, max_total_tokens=1000000,
                max_prompt_bytes=96000, max_output_tokens=16384, thinking='enabled', reasoning_effort='high',
                ordering='source candidate ranks round robin over sorted trial names',
                interrupted_dispatch='unknown with reserved cost; no retry',
                unknown='not executed; not an invalid test judgment',
                native_outcomes_sent=False, evaluation_labels_sent=False),
            ordering=relation.POLICY['ordering'],
            stop='First controlled failure, then one repeat; stop even if the repeat does not confirm.',
            alert='Source-only model support plus repeated controlled native failure; pending independent full-test audit.')
        _verify_protocol(record)
        _verify_algorithm(record)
        write(args.output/'prepared.json', record)
        write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    else:
        record.update(stage='source_census_only_not_a_native_execution_protocol', native_executions=0,
                      total_candidates=sum(len(row['candidates']) for row in cases))
        write(args.output/'census.json', record)
    return dict(trials=len(cases), selected=sum(len(row['candidates']) for row in cases),
                record=frozen(args.output/('prepared.json' if freeze else 'census.json')))


def _controlled(outcome):
    native = outcome.get('native') or {}
    return (outcome.get('transport', {}).get('status') == 'matched'
            and native.get('controls', {}).get('status') == 'all_source_controls_passed'
            and native.get('controlled_failure') is True)


def _native_once(candidate, source, corpus, directory, protocol):
    outcome_path = directory/'outcome.json'
    if outcome_path.exists():
        # A crash before this receipt is sealed needs explicit investigation;
        # it cannot silently authorize replay of an unsealed outcome.
        outcome = _read_sealed(outcome_path)
        _verify_nested_receipts(outcome)
        return outcome
    outcome = one_run(candidate, source, corpus, directory, protocol)
    if read(outcome_path) != outcome:
        raise ValueError('Native adapter returned different persisted outcome')
    _verify_nested_receipts(outcome)
    write(directory/'outcome_seal.json', frozen(outcome_path))
    return outcome


def run(args):
    with (args.input/'.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _run(args)


def _run(args):
    root = args.input
    if read(root/'seal.json') != frozen(root/'prepared.json'):
        raise ValueError('Protocol seal points to another artifact')
    protocol = read(root/'prepared.json')
    _verify_protocol(protocol)
    _verify_algorithm(protocol)
    semantic = _verified_semantic(root, protocol)
    if protocol.get('source_cohort'):
        verify(protocol['source_cohort'])
    for case in protocol['cases']:
        _verify_case_inputs(case)
    if (root/'summary.json').exists():
        summary = _read_sealed(root/'summary.json')
        _verify_nested_receipts(summary)
        rows = [_verified_case_result(root/'cases'/case['case'], case, semantic)
                for case in protocol['cases']]
        if summary['results'] != rows or summary['trial_denominator'] != protocol['trial_denominator']:
            raise ValueError('Completed summary differs from full cohort')
        return summary
    deadline = datetime.fromisoformat(protocol['deadline_utc'].replace('Z', '+00:00'))
    def enough_time():
        return (len(list((root/'cases').glob('*/candidate_*/**/native_outcome.json'))) < protocol['max_native_executions']
                and (deadline-datetime.now(timezone.utc)).total_seconds() > protocol['timeout']+30)
    results = []
    for case in protocol['cases']:
        directory = root/'cases'/case['case']
        if (directory/'result.json').exists():
            results.append(_verified_case_result(directory, case, semantic))
            continue
        source = Path(case['source'])
        corpus = read(source/'corpus.json')
        result = dict(case=case['case'], attempts=[], alert=None, stop_reason=case['status'])
        for entry in case['candidates']:
            verify(entry['program'])
            if (case['case'], entry['rank']) not in semantic['admitted']:
                continue
            if not enough_time():
                result['stop_reason'] = 'execution_budget'
                break
            candidate = read(entry['program']['path'])
            candidate_dir = directory/f"candidate_{entry['rank']:04d}"
            outcome = _native_once(candidate, source, corpus, candidate_dir/'initial', protocol)
            attempt = dict(rank=entry['rank'], program=entry['program'], initial=outcome,
                           initial_receipt=frozen(candidate_dir/'initial/outcome.json'))
            result['attempts'].append(attempt)
            native = outcome.get('native')
            if native is None:
                result['stop_reason'] = 'emission_or_transport_unavailable'
                continue
            if native.get('controls', {}).get('status') != 'all_source_controls_passed':
                result['stop_reason'] = 'source_control_unavailable_or_failed'
                break
            if _controlled(outcome):
                result['stop_reason'] = 'first_failure_unconfirmed'
                if enough_time():
                    confirmation = _native_once(candidate, source, corpus, candidate_dir/'confirmation', protocol)
                    attempt['confirmation'] = confirmation
                    attempt['confirmation_receipt'] = frozen(candidate_dir/'confirmation/outcome.json')
                    if _controlled(confirmation):
                        result['alert'] = dict(program=entry['program'],
                            initial=frozen(candidate_dir/'initial/outcome.json'),
                            confirmation=frozen(candidate_dir/'confirmation/outcome.json'),
                            semantic=semantic['decisions'][case['case'], entry['rank']],
                            validity='pending_independent_full_test_audit')
                        result['stop_reason'] = 'repeated_admitted_table_row_recombination_failure'
                break
            result['stop_reason'] = 'candidate_budget_exhausted'
        write(directory/'result.json', result)
        write(directory/'result_seal.json', frozen(directory/'result.json'))
        results.append(result)
        print(json.dumps(dict(case=case['case'], attempts=len(result['attempts']),
                              alert=bool(result['alert']), stop=result['stop_reason'])), flush=True)
    _verify_algorithm(protocol)
    summary = dict(version=VERSION, results=results, trial_denominator=protocol['trial_denominator'],
        result_receipts=[frozen(root/'cases'/row['case']/'result.json') for row in results],
        native_executions=len(list((root/'cases').glob('*/candidate_*/**/native_outcome.json'))),
        external_model_calls=semantic['provider_calls'], semantic_summary=frozen(root/'semantic_summary.json'),
        detector_alerts=sum(bool(row['alert']) for row in results),
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json', summary)
    write(root/'summary_seal.json', frozen(root/'summary.json'))
    return {key:value for key,value in summary.items() if key != 'results'}


def _review_entries(protocol):
    cases = protocol['cases']
    for rank in range(1, 17):
        for case in cases:
            for entry in case['candidates']:
                if entry['rank'] == rank:
                    yield case, entry


def _unknown(reason):
    return dict(status='unknown', alarm_eligible=False, semantic_validity='unconfirmed', reason=reason)


def verified_completion(request, completion, receipt):
    """Recover exactly the content whose raw response the provider recorded."""
    wire = read(completion/'request.json')
    if (wire.get('messages') != [{'role': 'system', 'content': request['system']},
                                {'role': 'user', 'content': request['prompt']}]
            or wire.get('max_tokens') != request['max_tokens']
            or wire.get('thinking') != {'type': request.get('thinking', 'disabled')}
            or wire.get('reasoning_effort') != request.get('reasoning_effort')
            or wire.get('model') != receipt.get('model')):
        raise ValueError('Provider wire content differs from frozen request')
    body = (completion/'response.body').read_bytes()
    if hashlib.sha256(body).hexdigest() != receipt.get('response_sha256'):
        raise ValueError('Provider raw response hash differs')
    raw = json.loads(body)
    if raw != read(completion/'response.json'):
        raise ValueError('Provider parsed response differs from raw body')
    choice = raw['choices'][0]
    text = choice['message']['content']
    if (not isinstance(text, str) or (completion/'completion.txt').read_bytes() != text.encode()
            or receipt.get('external_model_calls') != 1
            or receipt.get('finish_reason') != choice.get('finish_reason')
            or receipt.get('usage') != raw.get('usage')
            or receipt.get('response_model') != raw.get('model')):
        raise ValueError('Provider completion or accounting differs from raw response')
    return text


def review_all(args):
    root = args.input
    with (root/'.review.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if read(root/'seal.json') != frozen(root/'prepared.json'):
            raise ValueError('Protocol seal points to another artifact')
        protocol = read(root/'prepared.json')
        _verify_protocol(protocol)
        _verify_algorithm(protocol)
        if (root/'semantic_summary.json').exists():
            _verified_semantic(root, protocol)
            return {key:value for key,value in read(root/'semantic_summary.json').items()
                    if key not in {'results', 'result_receipts'}}
        policy = protocol['semantic_policy']; deadline = admission._deadline(protocol['deadline_utc'])
        rows = []
        for case, entry in _review_entries(protocol):
            _verify_case_inputs(case)
            for receipt in [entry['program'], entry['analysis']]:
                verify(receipt)
            if entry['request']: verify(entry['request'])
            directory = root/'cases'/case['case']/f"candidate_{entry['rank']:04d}"/'review'
            if (directory/'result.json').exists():
                row = read(directory/'result.json')
                if (row['case'] != case['case'] or row['rank'] != entry['rank']
                        or row['artifacts'] != _artifacts(directory)):
                    raise ValueError('Completed semantic artifacts changed')
                verify(row['decision']); rows.append(row); continue
            cost = dict(provider_calls=0, reserved_calls=0, measured_tokens=0,
                        reserved_tokens=0, usage_missing=0)
            analysis = read(entry['analysis']['path'])
            decision = _unknown(analysis['status'])
            if entry['request']:
                request = read(entry['request']['path'])
                if request['id'] != admission._request_identity(request):
                    raise ValueError('Frozen dispatch identity changed')
                reservation = _reservation(request)
                claim = directory/'dispatch_claim.json'
                completion = directory/'completion'; manifest = completion/'manifest.json'
                if manifest.exists() and not claim.exists():
                    raise ValueError('Provider receipt without dispatch claim')
                if claim.exists():
                    recorded = read(claim)
                    if recorded['request'] != entry['request'] or recorded['reserved_tokens'] != reservation:
                        raise ValueError('Dispatch claim changed')
                    decision = _unknown('interrupted_dispatch_without_complete_receipt')
                    cost.update(reserved_calls=1, reserved_tokens=reservation, usage_missing=1)
                else:
                    totals = _totals(rows)
                    if (totals['accounted_calls'] >= policy['max_calls']
                            or totals['accounted_tokens']+reservation > policy['max_total_tokens']):
                        decision = _unknown('model_budget')
                    elif (deadline-datetime.now(timezone.utc)).total_seconds() < 300:
                        decision = _unknown('deadline')
                    else:
                        write(claim, dict(request=entry['request'], reserved_tokens=reservation,
                            reserved_calls=1, created_utc=datetime.now(timezone.utc).isoformat()))
                        try:
                            dispatch(request, completion, root=ROOT)
                        except Exception as exc:
                            decision = _unknown('dispatch_exception_'+type(exc).__name__)
                            cost.update(reserved_calls=1, reserved_tokens=reservation, usage_missing=1)
                if manifest.exists():
                    receipt = read(manifest)
                    if receipt.get('request_id') != request['id']:
                        raise ValueError('Provider request identity differs')
                    wire = completion/'request.json'
                    if not wire.exists() or admission.digest(wire) != receipt.get('request_sha256'):
                        raise ValueError('Provider wire receipt differs')
                    cost = _cost(receipt, reservation)
                    decision = _unknown('provider_'+receipt['status'])
                    if receipt['status'] == 'complete':
                        decision = review.decide(request, verified_completion(request, completion, receipt),
                                                 finish_reason=receipt.get('finish_reason'))
            write(directory/'decision.json', decision)
            row = dict(case=case['case'], rank=entry['rank'], program=entry['program'],
                decision=frozen(directory/'decision.json'), status=decision['status'],
                admitted=decision.get('status') == 'semantic_supported' and decision.get('alarm_eligible') is True,
                artifacts=_artifacts(directory), **cost)
            write(directory/'result.json', row); rows.append(row)
            print(json.dumps(dict(case=row['case'], rank=row['rank'], status=row['status'],
                                  admitted=row['admitted'], **_totals(rows))), flush=True)
        _verify_algorithm(protocol)
        summary = dict(version=VERSION, stage='complete', prepared=frozen(root/'prepared.json'),
            trial_denominator=protocol['trial_denominator'], results=rows,
            result_receipts=[frozen(root/'cases'/row['case']/f"candidate_{row['rank']:04d}"/'review/result.json')
                             for row in rows],
            admitted=sum(row['admitted'] for row in rows), native_executions=0,
            independent_semantic_audit_complete=False, **_totals(rows))
        write(root/'semantic_summary.json', summary)
        write(root/'semantic_summary_seal.json', frozen(root/'semantic_summary.json'))
        return {key:value for key,value in summary.items() if key not in {'results','result_receipts'}}


def _verified_semantic(root, protocol):
    summary = _read_sealed(root/'semantic_summary.json')
    verify(summary['prepared'])
    if (summary['version'] != VERSION or summary['stage'] != 'complete'
            or summary['prepared'] != frozen(root/'prepared.json')
            or summary['trial_denominator'] != protocol['trial_denominator']
            or summary['native_executions'] != 0):
        raise ValueError('Semantic cohort differs')
    expected = {(case['case'], entry['rank']): entry
                for case, entry in _review_entries(protocol)}
    rows = summary['results']
    keys = [(row['case'], row['rank']) for row in rows]
    if keys != list(expected):
        raise ValueError('Semantic decisions must cover every frozen candidate')
    if len(summary['result_receipts']) != len(rows):
        raise ValueError('Semantic result receipts differ')
    admitted, decisions = set(), {}
    for row, receipt in zip(rows, summary['result_receipts']):
        verify(receipt)
        expected_directory = root/'cases'/row['case']/f"candidate_{row['rank']:04d}"/'review'
        if receipt != frozen(expected_directory/'result.json'):
            raise ValueError('Semantic result path differs from frozen candidate rank')
        if read(receipt['path']) != row: raise ValueError('Semantic result changed')
        directory = Path(receipt['path']).parent
        if row['artifacts'] != _artifacts(directory): raise ValueError('Semantic artifacts changed')
        key = row['case'], row['rank']; entry = expected[key]
        if row['program'] != entry['program']: raise ValueError('Reviewed candidate differs')
        verify(entry['program']); verify(row['decision'])
        decision = read(row['decision']['path'])
        if row['decision'] != frozen(expected_directory/'decision.json'):
            raise ValueError('Semantic decision path differs')
        if entry['request']:
            verify(entry['request'])
            request = read(entry['request']['path'])
            if request['id'] != admission._request_identity(request):
                raise ValueError('Frozen dispatch identity changed')
            claim = directory/'dispatch_claim.json'
            manifest = directory/'completion/manifest.json'
            if claim.exists():
                recorded = read(claim)
                if (recorded['request'] != entry['request'] or recorded['reserved_calls'] != 1
                        or recorded['reserved_tokens'] != _reservation(request)):
                    raise ValueError('Recorded dispatch differs from the frozen request')
            if manifest.exists():
                if not claim.exists():
                    raise ValueError('Provider receipt without dispatch claim')
                completion = read(manifest)
                if (completion.get('request_id') != request['id']
                        or completion.get('request_sha256') != admission.digest(directory/'completion/request.json')):
                    raise ValueError('Provider request receipt differs')
                if completion['status'] == 'complete':
                    decoded = review.decide(request,
                        verified_completion(request, directory/'completion', completion),
                        finish_reason=completion.get('finish_reason'))
                    if decoded != decision:
                        raise ValueError('Semantic decision differs from sealed raw provider response')
                    cost = _cost(completion, _reservation(request))
                    if any(row[key] != value for key, value in cost.items()):
                        raise ValueError('Semantic accounting differs from raw provider receipt')
                elif decision.get('status') != 'unknown':
                    raise ValueError('Incomplete provider response cannot support a semantic decision')
            elif decision.get('status') != 'unknown':
                raise ValueError('No provider receipt can support this semantic decision')
        elif decision.get('status') != 'unknown':
            raise ValueError('Unprepared candidate cannot have a semantic decision')
        valid = decision.get('status') == 'semantic_supported' and decision.get('alarm_eligible') is True
        if row['admitted'] != valid or row['status'] != decision['status']:
            raise ValueError('Semantic admission differs from fixed decision')
        decisions[key] = row['decision']
        if valid: admitted.add(key)
    if _totals(rows) != {key:summary[key] for key in _totals(rows)}:
        raise ValueError('Semantic accounting differs')
    if summary['admitted'] != len(admitted):
        raise ValueError('Semantic admitted count differs')
    return dict(admitted=admitted, decisions=decisions, provider_calls=summary['provider_calls'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['census', 'prepare', 'review', 'run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--deadline-utc')
    args = parser.parse_args()
    if args.stage == 'prepare' and not args.deadline_utc:
        parser.error('--deadline-utc is required for prepare')
    if args.stage in {'prepare', 'census'} and (args.source_cohort is None or args.output is None):
        parser.error('--source-cohort and --output are required for source preparation')
    if args.stage in {'review', 'run'} and args.input is None:
        parser.error('--input is required for review or run')
    result = (run(args) if args.stage == 'run' else review_all(args) if args.stage == 'review'
              else collect(args, freeze=args.stage == 'prepare'))
    print(json.dumps(result))
