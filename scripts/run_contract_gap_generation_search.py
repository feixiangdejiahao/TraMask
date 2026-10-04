"""Generate direct source tests, then fresh review and controlled native execution.

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
from relation_search import contract_gap_proposals as relation
from relation_search import compact_contract_guarded as review
from relation_search import csi_repair_transport
from relation_search.candidate_edit_transport import verify_emission
from relation_search.source_frontend_refresh import refresh
from relational_gap.frontend import to_emitter_corpus
from relational_gap.provider import dispatch
from scripts.discover_quantity_bounds import _cost, _totals, _reservation, _artifacts
from types import SimpleNamespace
import fcntl
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import execute, frozen, verify, write
from scripts.resume_test_prefix_probe import try_emit

VERSION = 'controlled-direct-contract-gap-generation.v1'
EXPECTED_TRIALS = 17


def one_run(candidate, source, corpus, directory, protocol):
    """Check complete Python values before the single native adapter call."""
    artifact, refusal = try_emit(candidate, source, directory/'native', protocol)
    checker = csi_repair_transport.verify if corpus['language'] == 'python' else verify_emission
    transport = (checker(corpus, candidate, artifact) if artifact else
                 dict(status='not_emitted', reason=refusal))
    native = (execute(candidate, source, corpus, directory/'native', protocol)
              if transport['status'] == 'matched' else None)
    outcome = dict(transport=transport, native=native, emission_refusal=refusal)
    write(directory/'outcome.json', outcome)
    return outcome


def _verify_algorithm(protocol):
    admission._preload_local_imports(sys.modules[__name__])
    entrypoints = protocol.get('algorithm_entrypoints', {})
    if set(entrypoints) != {'driver', 'constructor', 'semantic_reviewer', 'native_adapter', 'provider_adapter'}:
        raise ValueError('Missing explicit executed entrypoint receipts')
    recorded = {(row['path'], row['sha256']) for row in protocol['algorithm'].values()}
    if any((row['path'], row['sha256']) not in recorded for row in entrypoints.values()):
        raise ValueError('Executed entrypoint missing from imported algorithm seal')
    admission._verify_sources(entrypoints, protocol['algorithm'])


def _verify_protocol(protocol, phase='semantic_native'):
    if protocol.get('version') != VERSION or protocol.get('phase') != phase:
        raise ValueError('Unsupported protocol')
    names = [case['case'] for case in protocol['cases']]
    if names != sorted(set(names)) or len(names) != protocol['trial_denominator']:
        raise ValueError('Protocol cohort order or denominator differs')
    if protocol['max_candidates_per_trial'] != 3:
        raise ValueError('Unexpected per-trial candidate budget')
    for case in protocol['cases']:
        entries = case['candidates']
        ranks = [e['rank'] for e in entries]
        if len(entries) > 3 or ranks != sorted(set(ranks)) or any(type(rank) is not int or not 1 <= rank <= 3 for rank in ranks):
            raise ValueError('Candidate ranks are not a complete source prefix')
        if any(e['order'] != [e['rank']] for e in entries):
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
    for key in ('generation_request', 'generation_result', 'generation_preparation'):
        if case.get(key):
            verify(case[key])


def _context(case):
    manifest = read(case['review_projection']['path'])
    return read(manifest['corpus']['path']), read(manifest['frontend']['path'])


def _entrypoints():
    return {name: frozen(path) for name, path in {
        'driver': __file__, 'constructor': relation.__file__, 'semantic_reviewer': review.__file__,
        'native_adapter': sys.modules[one_run.__module__].__file__,
        'provider_adapter': sys.modules[dispatch.__module__].__file__,
    }.items()}


def prepare(args):
    if read(args.source_cohort/'seal.json') != frozen(args.source_cohort/'prepared.json'):
        raise ValueError('Source cohort seal points to another protocol')
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
    deadline = admission._deadline(args.deadline_utc)
    if deadline is None:
        raise ValueError('Deadline required')
    admission._preload_local_imports(sys.modules[__name__])
    algorithm = admission._loaded_sources()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for case, source_name in sorted(sources.items()):
        source = Path(source_name)
        inputs = {name: frozen(source/name) for name in
                  ('corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md')}
        original = read(source/'corpus.json'); frontend = read(source/'frontend.json')
        corpus, frontend, projection = repository_projection(original, frontend)
        selected = sorted(corpus['tests'].items(), key=relation._order)[:relation.MAX_SEEDS]
        identities = {identifier: dict(id=identifier, base_test_id=identifier,
            source_test_ids=[identifier], imports=[], edits=[]) for identifier, _ in selected}
        corpus, enriched = admission._enrich(corpus, frontend, identities,
            source/'corpus.json', args.output, len(cases))
        corpus, frontend, enriched_projection = repository_projection(corpus,
            dict(frontend, sources=corpus['sources']))
        for path, row in original['sources'].items():
            if path in corpus['sources'] and 'complete_file' in row:
                corpus['sources'][path]['complete_file'] = row['complete_file']
        directory = args.output/'cases'/case
        context_dir = directory/'review_projection'
        write(context_dir/'corpus.json', corpus); write(context_dir/'frontend.json', frontend)
        projection.update(original_inputs={key: inputs[key] for key in ('corpus.json', 'frontend.json')},
            enriched_source_sha256=enriched_projection['source_sha256'], source_context=enriched,
            corpus=frozen(context_dir/'corpus.json'), frontend=frozen(context_dir/'frontend.json'))
        write(context_dir/'manifest.json', projection)
        generated = relation.prepare(corpus, frontend, (source/'issue.md').read_text(),
                                     max_prompt_bytes=96000, max_output_tokens=16384)
        target = directory/'generation'
        write(target/'preparation.json', generated)
        if generated['request'] is not None:
            write(target/'request.json', generated['request'])
        cases.append(dict(case=case, source=str(source.resolve()), inputs=inputs,
            generation=frozen(target/'preparation.json'),
            generation_request=frozen(target/'request.json') if generated['request'] else None,
            source_context=enriched, review_projection=frozen(context_dir/'manifest.json'),
            status=generated['status'], candidates=[]))
        print(json.dumps(dict(case=case, status=generated['status'], anchors=len(generated['seeds']),
                              omitted=len(generated['omitted']), prompt_bytes=generated.get('prompt_bytes'))), flush=True)
    record = dict(version=VERSION, phase='generation', policy=relation.POLICY,
        algorithm=algorithm, algorithm_entrypoints=_entrypoints(), cases=cases,
        trial_denominator=len(cases), source_cohort=frozen(args.source_cohort/'prepared.json'),
        source_cohort_use='Original snapshot paths and full trial list only; no old candidates, labels or outcomes.',
        max_candidates_per_trial=3, deadline_utc=deadline.isoformat(), timeout=180,
        generation_policy=dict(max_calls=17, max_total_tokens=1000000, max_calls_per_trial=1,
            max_prompt_bytes=96000, max_output_tokens=16384, thinking='enabled', reasoning_effort='high',
            ordering='sorted trial names; one non-retriable request per prepared trial'),
        semantic_policy=dict(max_calls=51, max_total_tokens=1500000, max_prompt_bytes=96000,
            max_output_tokens=16384, thinking='enabled', reasoning_effort='high',
            ordering='original proposal ranks round robin over sorted trial names',
            unknown='not executed; not an invalid-test judgment',
            native_outcomes_sent=False, generation_basis_sent=False),
        max_native_executions=4*len(cases),
        stop='First admitted controlled failure then one repeat; stop even if unconfirmed. No audit-driven fallback.',
        comparative_limits=['At most four editable original anchors per trial; complete contexts can contain extra original control tests.',
            'The 24000-byte issue API catalog shares the 96000-byte budget with complete seed contexts.',
            'Body-only generation retains registration, signatures, decorators and imports.',
            'Original issue descriptions already contain rich semantic targets; these contracts are also available to this direct baseline.',
            'Python requires complete AST value transport; Go and TypeScript retain the existing syntax transport and its documented limits.',
            'Source selection, budget omissions and missing contracts limit a negative result. It cannot establish superiority over unrestricted direct models.'],
        provider_calls=0, native_executions=0, evaluation_labels_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    _verify_protocol(record, 'generation'); _verify_algorithm(record)
    write(args.output/'prepared.json', record); write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(trials=len(cases), requests=sum(bool(case['generation_request']) for case in cases),
                prepared=frozen(args.output/'prepared.json'), provider_calls=0, native_executions=0)


def _read_sealed(path):
    seal = read(path.with_name(path.stem+'_seal.json'))
    if seal != frozen(path):
        raise ValueError('Completed artifact seal differs: '+str(path))
    verify(seal)
    return read(path)


def _unknown_generation(reason):
    return dict(status='unknown', reason=reason, candidates=[], rejected=[],
                alarm_eligible=False, semantic_validity='unconfirmed')


def _generation_evidence(case, directory):
    """Recompute decoding and accounting from the original provider bytes."""
    _verify_case_inputs(case)
    prepared = read(case['generation']['path'])
    zero = dict(provider_calls=0, reserved_calls=0, measured_tokens=0, reserved_tokens=0, usage_missing=0)
    if not case['generation_request']:
        if prepared['request'] is not None:
            raise ValueError('Missing generation request receipt')
        return _unknown_generation('generation_not_prepared'), zero
    request = read(case['generation_request']['path'])
    if request != prepared['request'] or request['id'] != admission._request_identity(request):
        raise ValueError('Frozen generation request identity differs')
    claim = directory/'dispatch_claim.json'; manifest = directory/'completion/manifest.json'
    if not claim.exists():
        if manifest.exists():
            raise ValueError('Generation provider receipt without dispatch claim')
        return _unknown_generation('not_dispatched'), zero
    reservation = _reservation(request)
    recorded = read(claim)
    if (recorded['request'] != case['generation_request'] or recorded['reserved_calls'] != 1
            or recorded['reserved_tokens'] != reservation):
        raise ValueError('Generation dispatch claim differs')
    if not manifest.exists():
        return _unknown_generation('interrupted_or_failed_dispatch'), dict(zero,
            reserved_calls=1, reserved_tokens=reservation, usage_missing=1)
    receipt = read(manifest)
    if (receipt.get('request_id') != request['id']
            or receipt.get('request_sha256') != admission.digest(directory/'completion/request.json')):
        raise ValueError('Generation provider request receipt differs')
    cost = _cost(receipt, reservation)
    if receipt['status'] != 'complete':
        return _unknown_generation('provider_' + receipt['status']), cost
    completion = verified_completion(request, directory/'completion', receipt)
    corpus, frontend = _context(case)
    decoded = relation.decide(corpus, frontend, prepared, completion,
                              finish_reason=receipt.get('finish_reason'))
    return decoded, cost


def _generation_case_result(root, case):
    directory = root/'cases'/case['case']/'generation'
    row = read(directory/'result.json')
    if (row['case'] != case['case'] or row['preparation'] != case['generation']
            or row['artifacts'] != _artifacts(directory)
            or row['decoded'] != frozen(directory/'decoded.json')):
        raise ValueError('Completed generation artifacts changed')
    decoded, cost = _generation_evidence(case, directory)
    if read(row['decoded']['path']) != decoded or any(row[key] != value for key, value in cost.items()):
        raise ValueError('Generation decoding or accounting differs from raw evidence')
    if (row['status'] != decoded['status'] or row['candidates'] != len(decoded['candidates'])
            or row['refusals'] != len(decoded['rejected'])):
        raise ValueError('Generation proposal/refusal inventory differs')
    return row


def _verified_generation(root, protocol):
    _verify_protocol(protocol, 'generation'); _verify_algorithm(protocol)
    if read(root/'seal.json') != frozen(root/'prepared.json'):
        raise ValueError('Generation protocol seal differs')
    verify(protocol['source_cohort'])
    summary = _read_sealed(root/'generation_summary.json')
    if (summary.get('version') != VERSION or summary.get('stage') != 'complete'
            or summary['prepared'] != frozen(root/'prepared.json')
            or summary['trial_denominator'] != protocol['trial_denominator']
            or summary['native_executions'] != 0):
        raise ValueError('Generation summary does not cover the frozen cohort')
    rows = [_generation_case_result(root, case) for case in protocol['cases']]
    receipts = [frozen(root/'cases'/case['case']/'generation/result.json') for case in protocol['cases']]
    if summary['results'] != rows or summary['result_receipts'] != receipts:
        raise ValueError('Generation summary result inventory differs')
    if any(summary[key] != value for key, value in _totals(rows).items()):
        raise ValueError('Generation total accounting differs')
    return summary


def generate(args):
    root = args.input
    with (root/'.generation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        protocol = read(root/'prepared.json')
        if read(root/'seal.json') != frozen(root/'prepared.json'):
            raise ValueError('Generation protocol seal differs')
        _verify_protocol(protocol, 'generation'); _verify_algorithm(protocol)
        verify(protocol['source_cohort'])
        if (root/'generation_summary.json').exists():
            summary = _verified_generation(root, protocol)
            return _expand(root, protocol, summary)
        rows = []; policy = protocol['generation_policy']
        deadline = admission._deadline(protocol['deadline_utc'])
        for case in protocol['cases']:
            directory = root/'cases'/case['case']/'generation'
            _verify_case_inputs(case)
            if (directory/'result.json').exists():
                rows.append(_generation_case_result(root, case)); continue
            reason = None
            if case['generation_request']:
                request = read(case['generation_request']['path'])
                prepared = read(case['generation']['path'])
                if request != prepared['request'] or request['id'] != admission._request_identity(request):
                    raise ValueError('Frozen generation request identity differs')
                claim = directory/'dispatch_claim.json'
                if not claim.exists():
                    if (directory/'completion/manifest.json').exists():
                        raise ValueError('Generation receipt without dispatch claim')
                    totals = _totals(rows); reservation = _reservation(request)
                    if (totals['accounted_calls'] >= policy['max_calls']
                            or totals['accounted_tokens']+reservation > policy['max_total_tokens']):
                        reason = 'generation_budget'
                    elif (deadline-datetime.now(timezone.utc)).total_seconds() < 300:
                        reason = 'deadline'
                    else:
                        write(claim, dict(request=case['generation_request'], reserved_tokens=reservation,
                            reserved_calls=1, created_utc=datetime.now(timezone.utc).isoformat()))
                        try:
                            dispatch(request, directory/'completion', root=ROOT)
                        except Exception as exc:
                            write(directory/'dispatch_exception.json', dict(exception_type=type(exc).__name__))
            decoded, cost = _generation_evidence(case, directory)
            write(directory/'decoded.json', decoded)
            row = dict(case=case['case'], preparation=case['generation'],
                decoded=frozen(directory/'decoded.json'), status=decoded['status'],
                candidates=len(decoded['candidates']), refusals=len(decoded['rejected']),
                dispatch_withheld_reason=reason, artifacts=_artifacts(directory), **cost)
            write(directory/'result.json', row); rows.append(row)
            print(json.dumps(dict(case=case['case'], status=row['status'], candidates=row['candidates'],
                                  refusals=row['refusals'], **_totals(rows))), flush=True)
        _verify_algorithm(protocol)
        summary = dict(version=VERSION, stage='complete', prepared=frozen(root/'prepared.json'),
            trial_denominator=protocol['trial_denominator'], results=rows,
            result_receipts=[frozen(root/'cases'/row['case']/'generation/result.json') for row in rows],
            native_executions=0, **_totals(rows))
        write(root/'generation_summary.json', summary)
        write(root/'generation_summary_seal.json', frozen(root/'generation_summary.json'))
        return _expand(root, protocol, _verified_generation(root, protocol))


def _expand(root, protocol, summary):
    """Freeze fresh semantic requests after all generation receipts are complete."""
    target = root/'native'; target.mkdir(exist_ok=True)
    if (target/'prepared.json').exists():
        expanded = read(target/'prepared.json')
        if read(target/'seal.json') != frozen(target/'prepared.json'):
            raise ValueError('Expanded native protocol seal differs')
        _verify_generation_origin(expanded)
        return dict(generation_model_calls=summary['provider_calls'],
                    candidates=sum(len(c['candidates']) for c in expanded['cases']),
                    native_prepared=frozen(target/'prepared.json'))
    cases = []
    for old in protocol['cases']:
        source = Path(old['source']); directory = target/'cases'/old['case']
        generation_result = root/'cases'/old['case']/'generation/result.json'
        decoded_receipt = read(generation_result)['decoded']; decoded = read(decoded_receipt['path'])
        corpus, frontend = _context(old); programs = decoded['candidates']
        projection_receipt = old['review_projection']; enriched = old['source_context']
        if programs:
            corpus, enriched = admission._enrich(corpus, frontend, {p['id']:p for p in programs},
                source/'corpus.json', target, len(cases))
            corpus, frontend, projection = repository_projection(corpus, dict(frontend, sources=corpus['sources']))
            context_dir = directory/'review_projection'
            write(context_dir/'corpus.json', corpus); write(context_dir/'frontend.json', frontend)
            projection.update(original_inputs={key:old['inputs'][key] for key in ('corpus.json','frontend.json')},
                source_context=enriched, corpus=frozen(context_dir/'corpus.json'), frontend=frozen(context_dir/'frontend.json'))
            write(context_dir/'manifest.json', projection); projection_receipt = frozen(context_dir/'manifest.json')
        entries = []
        for program in programs:
            rank = program['order'][0]; candidate_dir = directory/f'candidate_{rank:04d}'
            write(candidate_dir/'program.json', program)
            result = review.prepare(corpus, frontend, program, (source/'issue.md').read_text(),
                                    max_prompt_bytes=96000, max_output_tokens=16384)
            request = result.pop('request'); review_dir = candidate_dir/'review'
            write(review_dir/'analysis.json', result)
            if request is not None:
                request = admission._configure_request(request, SimpleNamespace(
                    thinking='enabled', output_token_limit=16384, reasoning_effort='high'))
                write(review_dir/'request.json', request)
            entries.append(dict(rank=rank, order=program['order'], program=frozen(candidate_dir/'program.json'),
                analysis=frozen(review_dir/'analysis.json'), request=frozen(review_dir/'request.json') if request else None))
        cases.append(dict(old, generation=decoded_receipt, generation_preparation=old['generation'],
            generation_result=frozen(generation_result), review_projection=projection_receipt,
            source_context=enriched, candidates=entries, status=decoded['status']))
    expanded = dict(protocol, phase='semantic_native', cases=cases,
        generation_root=str(root.resolve()), generation_protocol=frozen(root/'prepared.json'),
        generation_summary=frozen(root/'generation_summary.json'), generation_model_calls=summary['provider_calls'])
    _verify_protocol(expanded); _verify_algorithm(expanded)
    write(target/'prepared.json', expanded); write(target/'seal.json', frozen(target/'prepared.json'))
    return dict(generation_model_calls=summary['provider_calls'],
                candidates=sum(len(c['candidates']) for c in cases), native_prepared=frozen(target/'prepared.json'))


def _verify_generation_origin(protocol):
    root = Path(protocol['generation_root'])
    if protocol['generation_protocol'] != frozen(root/'prepared.json'):
        raise ValueError('Native generation protocol origin differs')
    original = read(root/'prepared.json'); summary = _verified_generation(root, original)
    inherited = ('algorithm', 'algorithm_entrypoints', 'deadline_utc', 'semantic_policy',
                 'generation_policy', 'source_cohort', 'max_native_executions', 'timeout',
                 'max_candidates_per_trial', 'comparative_limits')
    if any(protocol[key] != original[key] for key in inherited):
        raise ValueError('Derived protocol changed a predeclared policy or algorithm')
    if (protocol['generation_summary'] != frozen(root/'generation_summary.json')
            or protocol['generation_model_calls'] != summary['provider_calls']
            or protocol['trial_denominator'] != original['trial_denominator']
            or [c['case'] for c in protocol['cases']] != [c['case'] for c in original['cases']]):
        raise ValueError('Native generation summary or cohort origin differs')
    for case, old in zip(protocol['cases'], original['cases']):
        result_path = root/'cases'/old['case']/'generation/result.json'
        row = read(result_path); decoded = read(row['decoded']['path'])
        if (case['generation_result'] != frozen(result_path) or case['generation'] != row['decoded']
                or case['generation_preparation'] != old['generation'] or case['inputs'] != old['inputs']
                or case['generation_request'] != old['generation_request']
                or case['source'] != old['source']):
            raise ValueError('Candidate original source or generation receipt differs')
        if len(case['candidates']) != len(decoded['candidates']):
            raise ValueError('Native candidate inventory omitted a decoded proposal')
        for entry, candidate in zip(case['candidates'], decoded['candidates']):
            verify(entry['program'])
            if (read(entry['program']['path']) != candidate or entry['rank'] != candidate['order'][0]
                    or entry['order'] != candidate['order']):
                raise ValueError('Native program differs from decoded model proposal')
    return summary


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
    generation = _verify_generation_origin(protocol)
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
                        result['stop_reason'] = 'repeated_admitted_direct_generation_failure'
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
        generation_model_calls=generation['provider_calls'], semantic_review_model_calls=semantic['provider_calls'],
        external_model_calls=generation['provider_calls']+semantic['provider_calls'],
        generation_summary=protocol['generation_summary'], semantic_summary=frozen(root/'semantic_summary.json'),
        detector_alerts=sum(bool(row['alert']) for row in results),
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json', summary)
    write(root/'summary_seal.json', frozen(root/'summary.json'))
    return {key:value for key,value in summary.items() if key != 'results'}


def _review_entries(protocol):
    cases = protocol['cases']
    for rank in range(1, 4):
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
        _verify_generation_origin(protocol)
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
    parser.add_argument('stage', choices=['prepare', 'generate', 'review', 'run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--deadline-utc')
    args = parser.parse_args()
    if args.stage == 'prepare':
        if args.source_cohort is None or args.output is None or not args.deadline_utc:
            parser.error('prepare requires --source-cohort, --output and --deadline-utc')
        result = prepare(args)
    else:
        if args.input is None:
            parser.error('--input is required')
        if args.stage in {'review', 'run'} and read(args.input/'prepared.json').get('phase') == 'generation':
            args.input = args.input/'native'
        result = generate(args) if args.stage == 'generate' else review_all(args) if args.stage == 'review' else run(args)
    print(json.dumps(result))
