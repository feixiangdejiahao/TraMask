"""Source-selected helper-slot generation, recorded provider calls and native emission.

This capability experiment does not consult target labels or earlier oracle
answers. Its fixed cohort is the candidates that gain an editable helper port
but have no editable ordinary assertion. The original benchmark run is unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from relation_search.checkpoint import digest, read, seal, write
from relation_search.oracle import program_candidate
from relation_search.semantic_selection import select


ALGORITHM_FILES = [
    'experimental/helper_expected_slots.py', 'experimental/go_assertion_helper.py',
    'experimental/go_arity_guard.py', 'experimental/local_helper_evidence.py',
    'experimental/source_failure_evidence.py',
    'experimental/singleton_oracle_slots.py', 'experimental/assertion_operand_guard.py',
    'experimental/finite_oracle_templates.py', 'generic_composition/corpus.py',
    'anchor_retrieval/syntax.py', 'relation_search/semantic_selection.py',
    'relation_search/oracle.py', 'relation_search/oracle_evidence.py', 'relation_search/instrument.py',
    'relational_gap/provider.py', 'scripts/run_helper_expected_slots.py',
]


def prepare(inventory, output, *, budget=8, max_bytes=64000):
    from experimental.helper_expected_slots import inventory as slots, prepare_request
    from experimental.go_assertion_helper import HelperIndex
    from experimental.singleton_oracle_slots import assertion_inventory
    if budget < 1:
        raise ValueError('The per-case budget must be positive')
    inventory, output = Path(inventory).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = sorted(p for p in inventory.iterdir() if (p/'source_pool.json').is_file())
    inputs = {p.name: {name: digest(p/name) for name in
              ['corpus.json', 'frontend.json', 'source_pool.json', 'issue.md', 'case.json', 'selection.json']}
              for p in cases}
    code = {name: digest(ROOT/name) for name in ALGORITHM_FILES}
    for name in code:
        target = output/'code_snapshot'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    protocol = dict(version='helper-expected-slot-generation-v1',
        created_at=datetime.now(timezone.utc).isoformat(), inventory=str(inventory),
        cases=[p.name for p in cases], input_sha256=inputs, code_sha256=code,
        cohort='all fixed source-pool candidates with new helper literal ports and zero ordinary editable slots',
        selection='unchanged semantic_selection.select within that source-only cohort',
        per_case_budget=budget, max_bytes=max_bytes,
        provider='authorized .env destination', model='deepseek-v4-flash',
        thinking='enabled', provider_calls=0, subject_executions=0,
        prior_timebox_score_frozen=True, semantic_correctness='unreviewed',
        forbidden_selection_inputs=['target labels', 'prior oracle answers', 'runtime outcomes',
                                    'reference patch', 'hidden verifier'])
    write(output/'protocol.json', protocol)
    records, requests = [], []
    for case in cases:
        corpus, frontend = read(case/'corpus.json'), read(case/'frontend.json')
        candidates = read(case/'source_pool.json')['candidates']
        helper_index = HelperIndex(corpus) if corpus['language'] == 'go' else None
        qualified, counts, unknowns = [], Counter(), []
        for original in candidates:
            candidate = program_candidate(original)
            baseline_rows = assertion_inventory(corpus, frontend, candidate)
            try:
                rows = slots(corpus, frontend, candidate, index=helper_index) if helper_index is not None else []
            except (ValueError, KeyError, TypeError, UnicodeError) as error:
                rows = []
                counts['unknown_inventory_candidates'] += 1
                unknowns.append(dict(candidate_id=candidate['id'], reason=str(error)))
            ordinary = sum(r.get('slot') is not None for r in baseline_rows)
            helpers = sum(r.get('kind') == 'helper_expected_call' and r.get('slot') is not None for r in rows)
            counts['candidates'] += 1
            counts['ordinary_editable_candidates'] += ordinary > 0
            counts['helper_editable_candidates'] += helpers > 0
            if helpers and not ordinary:
                qualified.append(candidate)
        selection = select(corpus, qualified, budget=budget)
        write(output/case.name/'unknowns.json', unknowns)
        write(output/case.name/'selection.json', selection)
        prepared, skips = [], []
        for number, candidate in enumerate(selection['selected']):
            result = prepare_request(corpus, frontend, candidate, (case/'issue.md').read_text(),
                                     max_bytes=max_bytes, index=helper_index)
            request = result['request']
            if request is None:
                skips.append(result['record'])
                continue
            request['source_prepared'] = str(case)
            path = output/case.name/'requests'/f'{number:03d}.json'
            write(path, request)
            row = dict(case=case.name, candidate_id=candidate['id'], request=str(path),
                       request_sha256=digest(path), request_id=request['id'],
                       prepared_record=result['record'])
            prepared.append(row)
            requests.append(row)
        record = dict(case=case.name, language=corpus['language'], **dict(counts),
                      newly_offerable_candidates=len(qualified), selected=len(selection['selected']),
                      requests=len(prepared), skips=skips)
        records.append(record)
        print(json.dumps(record, sort_keys=True), flush=True)
    ready = dict(cases=records, requests=requests, protocol_sha256=digest(output/'protocol.json'),
                 total_candidates=sum(r['candidates'] for r in records),
                 maximum_new_requests=len(requests), provider_calls=0)
    write(output/'ready.json', ready)
    seal(output, ready, name='input_seal.json')
    return ready


def verified(directory):
    directory = Path(directory).resolve()
    frozen = read(directory/'input_seal.json')
    for name, checksum in frozen['files_sha256'].items():
        if digest(directory/name) != checksum:
            raise ValueError('Prepared file changed: '+name)
    protocol, ready = read(directory/'protocol.json'), read(directory/'ready.json')
    if digest(directory/'protocol.json') != ready['protocol_sha256']:
        raise ValueError('Prepared protocol changed')
    for name, checksum in protocol['code_sha256'].items():
        if digest(ROOT/name) != checksum:
            raise ValueError('Algorithm changed after source selection: '+name)
    for case, files in protocol['input_sha256'].items():
        for name, checksum in files.items():
            if digest(Path(protocol['inventory'])/case/name) != checksum:
                raise ValueError('Fixed source input changed')
    return protocol, ready


def run(directory, *, workers=2):
    from experimental.helper_expected_slots import apply_response
    from relational_gap.provider import dispatch
    directory = Path(directory).resolve()
    if workers not in {1, 2}:
        raise ValueError('Use one or two workers')
    protocol, ready = verified(directory)
    result_root = directory/'execution'
    result_root.mkdir(exist_ok=True)
    receipt = dict(workers=workers, maximum_new_requests=len(ready['requests']), retries=0,
                   protocol_sha256=digest(directory/'protocol.json'),
                   ready_sha256=digest(directory/'ready.json'))
    if (result_root/'protocol.json').exists() and read(result_root/'protocol.json') != receipt:
        raise ValueError('Execution settings changed')
    write(result_root/'protocol.json', receipt)

    def worker(row):
        request = read(row['request'])
        output = result_root/row['case']/row['candidate_id']
        if output.exists():
            path = output/'manifest.json'
            if not path.exists() or read(path).get('status') not in {'complete', 'error', 'configuration_error'}:
                raise ValueError('Inspect the live or interrupted attempt; do not restart it')
            manifest = read(path)
            if manifest['request_id'] != row['request_id']:
                raise ValueError('Completion belongs to another request')
        else:
            manifest = dispatch(request, output, root=ROOT)
        result = dict(case=row['case'], candidate_id=row['candidate_id'],
                      provider_status=manifest['status'], usage=manifest.get('usage'),
                      finish_reason=manifest.get('finish_reason'), seconds=manifest.get('seconds'),
                      completion=str(output), semantic_correctness='unreviewed')
        if manifest['status'] == 'complete':
            source = Path(request['source_prepared'])
            validation = apply_response(request, (output/'completion.txt').read_text(),
                                        read(source/'corpus.json'), read(source/'frontend.json'))
            write(output/'validation.json', validation)
            result.update(validation_status=validation['status'], reason=validation.get('reason'),
                          candidate_accepted=validation.get('candidate') is not None)
        write(output/'outcome.json', result)
        return result

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker, row) for row in ready['requests']]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            results.sort(key=lambda r: (r['case'], r['candidate_id']))
            write(result_root/'results.json', results)
            print(json.dumps(result, sort_keys=True), flush=True)
    summary = dict(requests=len(results),
        provider_statuses=dict(Counter(r['provider_status'] for r in results)),
        validation_statuses=dict(Counter(r.get('validation_status', 'unavailable') for r in results)),
        accepted=sum(r.get('candidate_accepted', False) for r in results),
        semantic_correctness='unreviewed', subject_executions=0,
        completed_at=datetime.now(timezone.utc).isoformat())
    write(result_root/'summary.json', summary)
    return summary


def emit(directory, output, *, timeout=120):
    from scripts.execute_relation_search import emit_batch
    directory, output = Path(directory).resolve(), Path(output).resolve()
    protocol, ready = verified(directory)
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for case in protocol['cases']:
        candidates, revised, offered = {}, 0, 0
        for row in ready['requests']:
            if row['case'] != case:
                continue
            # Execute the same fixed combination with its source expectations,
            # even when the model is uncertain. A revision cannot hide that arm.
            original = read(row['request'])['candidate']
            candidates[original['id']] = original
            offered += 1
            validation = directory/'execution'/case/row['candidate_id']/'validation.json'
            if validation.exists() and read(validation).get('candidate') is not None:
                candidate = read(validation)['candidate']
                candidates[candidate['id']] = candidate
                revised += candidate['id'] != original['id']
        if not candidates:
            records.append(dict(case=case, offered=0, revisions=0, status='no_offered_candidate'))
            continue
        source, prepared = Path(protocol['inventory'])/case, output/case/'prepared'
        prepared.mkdir(parents=True)
        for name in ['corpus.json', 'frontend.json', 'selection.json', 'case.json', 'issue.md']:
            shutil.copyfile(source/name, prepared/name)
        write(prepared/'candidates.json', dict(candidates=list(candidates.values())))
        write(prepared/'prepare.json', dict(files_sha256={p.name: digest(p) for p in prepared.iterdir()},
              source_prepare=str(source/'prepare.json'), model_calls=offered))
        result = emit_batch(SimpleNamespace(input=prepared, output=output/case/'emitted',
            group_size=1, isolate_go_compilation=True, timeout=timeout,
            dependency_packages_root=ROOT/'data/relational_gap_v1_dependency_packages'))
        records.append(dict(case=case, offered=offered, revisions=revised, candidates=len(candidates), emission=result,
                            emitted=str(output/case/'emitted')))
    write(output/'summary.json', records)
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run', 'emit'])
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--budget', type=int, default=8)
    parser.add_argument('--max-bytes', type=int, default=64000)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    if args.stage != 'run' and args.output is None:
        parser.error('--output is required for prepare and emit')
    if args.stage == 'prepare':
        result = prepare(args.input, args.output, budget=args.budget, max_bytes=args.max_bytes)
    elif args.stage == 'run':
        result = run(args.input, workers=args.workers)
    else:
        result = emit(args.input, args.output, timeout=args.timeout)
    print(json.dumps(result, sort_keys=True))
