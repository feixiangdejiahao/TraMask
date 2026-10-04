"""Freeze uniform source-bound input repairs, then review before native testing.

Construction consumes all frozen historical source attempts. It never reads
old semantic decisions, native outcomes or independent validity labels. The
unchanged table-search harness supplies review/cost/transport/native handling
through an isolated function namespace; its module globals are never changed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from types import FunctionType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import csi_domain_repair as relation
from relation_search import csi_domain_repair_review as review
from relation_search import csi_repair_transport
from relation_search.checkpoint import read
from relational_gap.provider import dispatch
from scripts import run_table_column_rotation_search as harness
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import execute, frozen, verify, write
from scripts.resume_test_prefix_probe import try_emit

VERSION = 'controlled-csi-domain-repair-search.v1'
EXPECTED_TRIALS = 17


def one_run(candidate, source, corpus, directory, protocol):
    """Use the existing native adapter after the additional value-sensitive check."""
    artifact, refusal = try_emit(candidate, source, directory/'native', protocol)
    transport = (csi_repair_transport.verify(corpus, candidate, artifact) if artifact else
                 dict(status='not_emitted', reason=refusal))
    native = (execute(candidate, source, corpus, directory/'native', protocol)
              if transport['status'] == 'matched' else None)
    outcome = dict(transport=transport, native=native, emission_refusal=refusal)
    write(directory/'outcome.json', outcome)
    return outcome


def _verify_protocol(protocol):
    if protocol.get('version') != VERSION or protocol.get('policy') != relation.POLICY:
        raise ValueError('Unsupported repair protocol')
    names = [case['case'] for case in protocol['cases']]
    if names != sorted(set(names)) or len(names) != protocol['trial_denominator']:
        raise ValueError('Protocol cohort order or denominator differs')
    if protocol['max_candidates_per_trial'] != 16:
        raise ValueError('Unexpected candidate budget')
    for case in protocol['cases']:
        entries = case['candidates']
        if len(entries) > 16 or [e['rank'] for e in entries] != list(range(1, len(entries)+1)):
            raise ValueError('Candidate ranks must be a complete source prefix')
        if [e['order'] for e in entries] != sorted(e['order'] for e in entries):
            raise ValueError('Frozen repair order differs')
    if protocol['semantic_policy']['max_calls'] != 3 or protocol['max_native_executions'] != 6:
        raise ValueError('Repair experiment budget differs')
    for receipt in protocol['construction_receipts']:
        verify(receipt)
    if protocol['reused_harness'] != frozen(harness.__file__):
        raise ValueError('Reused full-test review/native harness differs')


def _review_entries(protocol):
    return iter(sorted(((case, entry) for case in protocol['cases'] for entry in case['candidates']),
                       key=lambda pair: pair[1]['order']))


def _engine():
    """Bind the unchanged harness code to this experiment's explicit adapters.

    Function code remains in the sealed harness file. A private globals mapping
    prevents changes to R12's imported module or any concurrent experiment.
    Every called review/native helper uses this same private mapping.
    """
    namespace = dict(vars(harness))
    overrides = dict(__name__=__name__, __file__=__file__, VERSION=VERSION,
                     relation=relation, review=review, dispatch=dispatch, one_run=one_run,
                     _verify_protocol=_verify_protocol, _review_entries=_review_entries)
    namespace.update(overrides)
    for name, function in vars(harness).items():
        if name not in overrides and isinstance(function, FunctionType) and function.__module__ == harness.__name__:
            bound = FunctionType(function.__code__, namespace, name, function.__defaults__, function.__closure__)
            bound.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = bound
    return namespace


def review_all(args):
    return _engine()['review_all'](args)


def run(args):
    return _engine()['run'](args)


def _source_inputs(args):
    """Verify only source preparation/selection/request artifacts, not outcomes."""
    root = args.source_queue.resolve()
    previous = read(root/'prepared.json')
    if read(root/'seal.json') != dict(prepared=frozen(root/'prepared.json')):
        raise ValueError('Historical source queue seal differs')
    names = [case['case'] for case in previous['cases']]
    if len(names) != EXPECTED_TRIALS or names != sorted(set(names)):
        raise ValueError('Complete original seventeen-trial cohort required')
    census = read(args.census)
    gate_freeze = read(args.guard_freeze)
    frozen_files = {row['path']: row for row in gate_freeze['files']}
    receipts = [frozen(root/'prepared.json'), frozen(root/'seal.json'), frozen(args.census), frozen(args.guard_freeze)]
    for receipt in [frozen(args.census), census['guard_source_receipt'], census['guard_test_receipt']]:
        if frozen_files.get(receipt['path'], {}).get('sha256') != receipt['sha256']:
            raise ValueError('Source gate census is not in its freeze')
        verify(receipt)
        receipts.append(receipt)
    directories = sorted((root/'attempts').iterdir())
    if ([p.name for p in directories] != [f'attempt_{i:06d}' for i in range(len(directories))]
            or [r['attempt'] for r in census['rows']] != [p.name for p in directories]):
        raise ValueError('Census must contain the complete historical source prefix')
    cases, rows, cached_hashes = {}, [], {}
    def checked(receipt):
        old = cached_hashes.setdefault(receipt['path'], receipt['sha256'])
        if old != receipt['sha256']:
            raise ValueError('Conflicting source hashes')
        if receipt not in receipts:
            verify(receipt); receipts.append(receipt)
    for directory, row in zip(directories, census['rows']):
        selection = read(directory/'selection.json')
        if selection != row['selection'] or selection['case'] not in names:
            raise ValueError('Source census selection differs')
        ranking = next(case['ranking'] for case in previous['cases'] if case['case'] == selection['case'])
        if not 1 <= selection['rank'] <= len(ranking) or dict(case=selection['case'], **ranking[selection['rank']-1]) != selection:
            raise ValueError('Source census candidate differs from original ranking')
        prepared = read(directory/'admission/prepared.json')
        if len(prepared['items']) != 1:
            raise ValueError('One complete source test per historical attempt required')
        item = prepared['items'][0]
        if any(item[k] != selection[k] for k in ('case', 'candidate_id', 'key')):
            raise ValueError('Prepared source candidate differs')
        for receipt in [frozen(directory/'selection.json'), frozen(directory/'admission/prepared.json'),
                        row['analysis_receipt'], row['source_corpus_receipt'], item['issue'],
                        *[item['source_inputs'][k] for k in ('corpus', 'frontend', 'candidates')]]:
            checked(receipt)
        if (item['source_inputs']['corpus'] != row['source_corpus_receipt']
                or item['analysis_path'] != row['analysis_receipt']['path']):
            raise ValueError('Frozen guard source inputs differ')
        source = Path(item['source_inputs']['corpus']['path']).parent
        pair = dict(source=str(source), corpus=item['source_inputs']['corpus'], frontend=item['source_inputs']['frontend'])
        if cases.setdefault(selection['case'], pair) != pair:
            raise ValueError('One source snapshot per trial required')
        if row['request_exists']:
            checked(row['request_receipt'])
            if (item['request_path'] != row['request_receipt']['path']
                    or item['request_sha256'] != row['request_receipt']['sha256']):
                raise ValueError('Historical source request differs')
            request = read(row['request_receipt']['path'])
            payload = json.loads(request['prompt'])
            if request['candidate_id'] != selection['candidate_id']:
                raise ValueError('Historical request candidate differs')
            if any(relation.sha(payload[key]) != row['guard'][key+'_sha256'] for key in ('original_test', 'modified_test')):
                raise ValueError('Historical full test differs from frozen guard')
        else:
            if item['request_path'] is not None:
                raise ValueError('Unrequested source candidate has a request')
            # No unrequested attempt is silently dropped from the census.
            # Reconstruct its full test from source edits if a bound-input
            # check could supply a repair premise.
            payload = None
            if row['guard'].get('checks'):
                corpus = read(item['source_inputs']['corpus']['path'])
                candidate = next(c for c in read(item['source_inputs']['candidates']['path']) if c['id'] == selection['candidate_id'])
                base = corpus['tests'][candidate['base_test_id']]['span']
                original = corpus['sources'][base['path']]['code'].encode()[base['start_byte']:base['end_byte']].decode()
                payload = dict(language=corpus['language'], original_test=original,
                               modified_test=relation.preview(corpus, candidate), issue=Path(item['issue']['path']).read_text())
        rows.append(dict(index=len(rows), census=row, item=item, payload=payload))
    if set(cases) != set(names):
        raise ValueError('Source attempt census does not retain the full cohort')
    return names, cases, rows, receipts


def collect(args, *, freeze):
    names, source_cases, rows, receipts = _source_inputs(args)
    deadline = admission._deadline(args.deadline_utc) if freeze else None
    if freeze and deadline is None:
        raise ValueError('Frozen deadline required')
    args.output.mkdir(parents=True, exist_ok=False)
    admission._preload_local_imports(sys.modules[__name__])
    algorithm = admission._loaded_sources()
    generated = {name: [] for name in names}
    census_rows = []
    for row in rows:
        source = row['census']; selection = source['selection']
        result = (relation.opportunities(row['payload'], source['guard']) if row['payload'] is not None else
                  dict(status='unrequested_without_bound_input_site', opportunities=[], unknowns=[]))
        census_rows.append(dict(attempt=source['attempt'], selection=selection, status=result['status'],
                               proposals=len(result['opportunities']), unknowns=result['unknowns'],
                               request=source['request_receipt'], source_gate_modified_sha256=source['guard']['modified_test_sha256']))
        if not result['opportunities']:
            continue
        corpus = read(row['item']['source_inputs']['corpus']['path'])
        previous = next(c for c in read(row['item']['source_inputs']['candidates']['path']) if c['id'] == selection['candidate_id'])
        for proposal in result['opportunities']:
            candidate = relation.construct(corpus, previous, row['payload'], proposal)
            candidate['order'] = [row['index'], proposal['start_byte'], proposal['end_byte']]
            candidate['source_provenance'] = dict(algorithm=relation.VERSION,
                historical_source_request=source['request_receipt'], historical_candidate_inputs=row['item']['source_inputs']['candidates'],
                seed_snapshot=row['item']['source_inputs']['corpus']['path'], seed=candidate['base_test_id'])
            generated[selection['case']].append(candidate)
    write(args.output/'source_census.json', dict(version=VERSION, rows=census_rows,
        trial_denominator=len(names), historical_source_attempts=len(rows),
        selected_without_semantic_or_native_or_audit_labels=True,
        source_pool='Historical full candidates, not a new original-repository-only constructor.'))
    cases = []
    for name in names:
        source = Path(source_cases[name]['source'])
        inputs = {key: frozen(source/key) for key in ('corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md')}
        programs = sorted(generated[name], key=lambda c: c['order'])
        if len(programs) > 16:
            raise ValueError('Source repair pool exceeds registered per-trial cap; no silent truncation')
        directory = args.output/'cases'/name
        corpus = read(source/'corpus.json'); frontend = read(source/'frontend.json')
        issue = (source/'issue.md').read_text()
        enriched = None
        if freeze and programs:
            corpus, enriched = admission._enrich(corpus, frontend, {c['id']: c for c in programs},
                                                source/'corpus.json', args.output, len(cases))
        entries = []
        for rank, candidate in enumerate(programs, 1):
            path = directory/f'candidate_{rank:04d}'/'program.json'
            write(path, candidate)
            entry = dict(rank=rank, order=candidate['order'], program=frozen(path))
            if freeze:
                result = review.prepare(corpus, frontend, candidate, issue,
                                        max_prompt_bytes=96000, max_output_tokens=16384)
                request = result.pop('request')
                target = path.parent/'review'
                write(target/'analysis.json', result)
                if request is not None:
                    request = admission._configure_request(request, SimpleNamespace(
                        thinking='enabled', output_token_limit=16384, reasoning_effort='high'))
                    write(target/'request.json', request)
                entry.update(analysis=frozen(target/'analysis.json'),
                             request=frozen(target/'request.json') if request is not None else None)
            entries.append(entry)
        write(directory/'generation.json', dict(version=relation.VERSION,
            status='source_hypotheses' if entries else 'no_bound_repair_opportunity',
            total_candidates=len(entries), historical_source_attempts=sum(r['selection']['case'] == name for r in census_rows)))
        cases.append(dict(case=name, source=str(source.resolve()), inputs=inputs,
                          candidates=entries, generation=frozen(directory/'generation.json'),
                          status='source_hypotheses' if entries else 'no_bound_repair_opportunity',
                          source_context=enriched, review_projection=None))
        print(json.dumps(dict(case=name, selected=len(entries))), flush=True)
    admission.verify_seal(algorithm)
    if set(admission._loaded_sources()) - set(algorithm):
        raise ValueError('Unrecorded source imported during preparation')
    record = dict(version=VERSION, policy=relation.POLICY, algorithm=algorithm,
        algorithm_entrypoints={name: frozen(path) for name, path in dict(
            driver=__file__, constructor=relation.__file__, semantic_reviewer=review.__file__,
            native_adapter=sys.modules[one_run.__module__].__file__, provider_adapter=sys.modules[dispatch.__module__].__file__).items()},
        reused_harness=frozen(harness.__file__), construction_receipts=receipts,
        source_census=frozen(args.output/'source_census.json'), cases=cases, trial_denominator=len(cases),
        max_candidates_per_trial=16, max_native_executions=6, timeout=180,
        external_model_calls=0, evaluator_labels_used=False, retrospective_development=True,
        source_pool='All frozen historical source attempts; rules do not use old decisions or native/audit outcomes.',
        original_oracle_assumption='Retained historical assertions need fresh complete-test review; input repair does not establish them.',
        created_utc=datetime.now(timezone.utc).isoformat())
    if freeze:
        record.update(deadline_utc=deadline.isoformat(),
            semantic_policy=dict(method=review.VERSION, max_calls=3, max_total_tokens=400000,
                max_prompt_bytes=96000, max_output_tokens=16384, thinking='enabled', reasoning_effort='high',
                ordering=relation.POLICY['ordering'], interrupted_dispatch='unknown with reserved cost; no retry',
                native_outcomes_sent=False, evaluation_labels_sent=False,
                unknown_domain='not executed, including when the full-test model judgment supports'),
            stop='First admitted controlled failure within a trial, then one repeat; no posthoc oracle repair or refill.')
        _verify_protocol(record); _engine()['_verify_algorithm'](record)
        write(args.output/'prepared.json', record)
        write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    else:
        record.update(stage='source_census_only_not_execution_protocol', native_executions=0)
        write(args.output/'census.json', record)
    return dict(trials=len(cases), source_attempts=len(rows), selected=sum(len(c['candidates']) for c in cases),
                requests=sum(bool(e.get('request')) for c in cases for e in c['candidates']),
                record=frozen(args.output/('prepared.json' if freeze else 'census.json')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['census', 'prepare', 'review', 'run'])
    parser.add_argument('--source-queue', type=Path)
    parser.add_argument('--census', type=Path)
    parser.add_argument('--guard-freeze', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--deadline-utc')
    args = parser.parse_args()
    required = ('source_queue', 'census', 'guard_freeze', 'output') if args.stage in {'census', 'prepare'} else ('input',)
    if args.stage == 'prepare':
        required += ('deadline_utc',)
    if any(getattr(args, key) is None for key in required):
        parser.error('Missing arguments: ' + ', '.join('--'+key.replace('_', '-') for key in required))
    result = (review_all(args) if args.stage == 'review' else run(args) if args.stage == 'run'
              else collect(args, freeze=args.stage == 'prepare'))
    print(json.dumps(result))
