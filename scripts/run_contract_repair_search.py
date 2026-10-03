"""Search fixed source-ranked candidates with review, oracle repair and execution.

Each case stops at its first supported, natively failing complete program.
Evaluator labels never select, repair, stop or replace a reported candidate.
The initial pool reuses historical generated programs; this is an incremental
search experiment, not a new cold-start generation claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT/'scripts'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from relation_search import compact_admission, ledger_admission, review_repair
from relation_search.admission import program_candidate
from relation_search import checkpoint
from relational_gap.provider import dispatch
from scripts import execute_relation_search as native_runner
from scripts import run_test_admission as admission_runner
from scripts.audit_requested_source_controls import inspect_controls, native
from scripts.evaluate_relational_gap import matches_runtime


VERSION = 'source-ranked-contract-repair-search.v1'
read, sha = checkpoint.read, checkpoint.digest


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read(path) != value:
            raise ValueError('Immutable artifact differs: ' + str(path))
        return
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def now():
    return datetime.now(timezone.utc)


def frozen(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))


def verify(receipt):
    if sha(receipt['path']) != receipt['sha256']:
        raise ValueError('Changed input: ' + receipt['path'])


def prepare(args):
    baseline = read(args.inventory)
    frontier = read(args.frontier/'manifest.json')
    if frontier['protocol']['source_inventory'] != frozen(args.inventory):
        raise ValueError('Source frontier belongs to a different inventory')
    records = {(row['case'], row['candidate_id']): row for row in reversed(baseline['controlled_failures'])}
    cases = []
    for entry in sorted(frontier['cases'], key=lambda row: row['case']):
        ranking = read(args.frontier/(entry['case']+'.json'))
        selected = ranking['ranking'][:args.max_per_case]
        rows = []
        for candidate in selected:
            record = records[entry['case'], candidate['id']]
            # Retain only source receipts. The experiment executes its reports
            # again and does not forward old native failure messages anywhere.
            rows.append(dict(rank=candidate['rank'], candidate_id=candidate['id'],
                source_inputs={key: record['inputs'][key] for key in ('corpus', 'frontend', 'candidates')}))
        cases.append(dict(case=entry['case'], candidates=rows, ranking=frozen(args.frontier/(entry['case']+'.json'))))
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    for module in (compact_admission, ledger_admission, review_repair, native_runner):
        admission_runner._preload_local_imports(module)
    algorithm = admission_runner._loaded_sources()
    protocol = dict(version=VERSION, cases=cases, source_inventory=frozen(args.inventory),
        source_frontier=frozen(args.frontier/'manifest.json'), algorithm=algorithm,
        gate=args.gate, thinking='disabled', max_prompt_bytes=96000,
        review_output_tokens=8192 if args.gate == 'ledger' else 2048,
        repair_output_tokens=4096, max_model_calls=args.max_model_calls,
        max_total_tokens=args.max_total_tokens, max_per_case=args.max_per_case,
        deadline_utc=args.deadline_utc, timeout=args.timeout,
        source_enrichment=args.enrich_sources, stop='first_supported_controlled_native_failure',
        order='source_case_order_then_source_rank', repairs_per_candidate=1,
        forbidden_selection_inputs=['evaluation labels', 'known witnesses', 'reference code', 'hidden tests'],
        native_feedback_sent_to_provider=False, created_utc=now().isoformat())
    write(output/'prepared.json', protocol)
    write(output/'seal.json', frozen(output/'prepared.json'))
    return dict(cases=len(cases), candidates=sum(len(row['candidates']) for row in cases))


class Budget:
    def __init__(self, root, protocol):
        self.root, self.protocol = root, protocol
        self.deadline = datetime.fromisoformat(protocol['deadline_utc'].replace('Z', '+00:00'))

    def totals(self):
        calls = measured = reserved = 0
        for path in self.root.glob('cases/*/candidate_*/**/completion/manifest.json'):
            row = read(path)
            calls += row.get('external_model_calls', 0)
            tokens = (row.get('usage') or {}).get('total_tokens')
            if type(tokens) is int and tokens >= 0:
                measured += tokens
            elif row.get('external_model_calls'):
                reserved += read(path.parent.parent/'budget_reservation.json')['tokens']
        return dict(calls=calls, measured_tokens=measured, reserved_tokens=reserved,
                    accounted_tokens=measured+reserved)

    def enough_time(self, seconds=300):
        return (self.deadline-now()).total_seconds() >= seconds

    def call(self, request, directory):
        directory.mkdir(parents=True, exist_ok=True)
        write(directory/'request.json', request)
        receipt_path = directory/'completion/manifest.json'
        if receipt_path.exists():
            receipt = read(receipt_path)
            if receipt['status'] in {'prepared', 'dispatching'}:
                raise ValueError('Interrupted provider dispatch requires process audit')
        else:
            total = self.totals()
            reservation = len(request['system'].encode()) + len(request['prompt'].encode()) + request['max_tokens'] + 1024
            if (total['calls'] >= self.protocol['max_model_calls']
                    or total['accounted_tokens']+reservation > self.protocol['max_total_tokens']
                    or not self.enough_time()):
                return None, dict(status='budget_exhausted')
            write(directory/'budget_reservation.json', dict(tokens=reservation, calls=1))
            receipt = dispatch(request, directory/'completion', root=ROOT)
        content = (directory/'completion/completion.txt').read_text() if receipt['status'] == 'complete' else None
        return content, receipt


def review(corpus, frontend, candidate, issue, directory, protocol, budget):
    method = compact_admission if protocol['gate'] == 'compact' else ledger_admission
    if (directory/'analysis.json').exists():
        result = read(directory/'analysis.json')
        request = read(directory/'request.json') if (directory/'request.json').exists() else None
    else:
        result = method.prepare(corpus, frontend, candidate, issue,
            max_prompt_bytes=protocol['max_prompt_bytes'], max_output_tokens=protocol['review_output_tokens'])
        request = result.pop('request')
        write(directory/'analysis.json', result)
        if request is not None:
            request = admission_runner._configure_request(request, SimpleNamespace(
                thinking=protocol['thinking'], output_token_limit=protocol['review_output_tokens'],
                reasoning_effort=None))
            write(directory/'request.json', request)
    if request is None:
        decision = dict(status=result['status'], alarm_eligible=False)
    else:
        content, receipt = budget.call(request, directory)
        decision = (method.decide(request, content, finish_reason=receipt.get('finish_reason'))
                    if content is not None else dict(status='unknown', alarm_eligible=False,
                                                     reason=receipt['status']))
    write(directory/'decision.json', decision)
    return request, decision


def execute(candidate, case_source, corpus, directory, protocol):
    prepared = directory/'prepared'
    if not (prepared/'checkpoint.json').exists():
        prepared.mkdir(parents=True, exist_ok=True)
        for name in ('corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md'):
            target = prepared/name
            if not target.exists():
                target.symlink_to((case_source/name).resolve())
        checkpoint.write(prepared/'candidates.json', dict(candidates=[candidate]))
        checkpoint.write(prepared/'prepare.json', dict(files_sha256={
            path.name: sha(path) for path in prepared.iterdir()
            if path.is_file() and path.name not in {'prepare.json','checkpoint.json'}}))
        checkpoint.seal(prepared, dict(status='single_fixed_reviewed_program'))
    options = SimpleNamespace(input=prepared, output=directory/'emitted', timeout=protocol['timeout'],
        group_size=1, isolate_go_compilation=True,
        dependency_packages_root=ROOT/'data/relational_gap_v1_dependency_packages')
    native_runner.emit_batch(options)
    native_runner.run(SimpleNamespace(input=options.output, output=directory/'executed', workers=1,
        registry=ROOT/'data/relational_gap_v1/registry.json'))
    runs = read(directory/'executed/runs.json')
    generated = [row for row in runs if row['role'] == 'generated' and row['candidate_id'] == candidate['id']]
    controls = inspect_controls(generated, runs)
    tests, errors = [], []
    for row in generated:
        found, issues, _ = native(row['result'])
        tests.extend(test for test in found if any(matches_runtime(test['id'], name) for name in row['test_ids']))
        errors.extend(issues)
    failure = any(test['status'] in {'fail', 'error'} for test in tests)
    outcome = dict(candidate_id=candidate['id'], controls=controls, tests=tests,
        parser_errors=errors, runs=frozen(directory/'executed/runs.json'),
        controlled_failure=bool(tests and failure and not errors and controls['status']=='all_source_controls_passed'))
    write(directory/'native_outcome.json', outcome)
    return outcome


def run(args):
    root = args.input
    with (root/'.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify(read(root/'seal.json'))
        protocol = read(root/'prepared.json')
        admission_runner.verify_seal(protocol['algorithm'])
        budget, case_results = Budget(root, protocol), []
        for case in protocol['cases']:
            case_dir = root/'cases'/case['case']
            if (case_dir/'result.json').exists():
                case_results.append(read(case_dir/'result.json'))
                continue
            corpus = frontend = candidates = None
            cached = None
            attempts, alert = [], None
            for row in case['candidates']:
                if not budget.enough_time():
                    break
                directory = case_dir/f'candidate_{row["rank"]:04d}'
                if (directory/'outcome.json').exists():
                    outcome = read(directory/'outcome.json')
                    attempts.append(outcome)
                    if outcome.get('alert'):
                        alert = outcome['alert']; break
                    continue
                inputs = row['source_inputs']
                identity = tuple(inputs[key]['path'] for key in ('corpus', 'frontend', 'candidates'))
                if cached != identity:
                    for receipt in inputs.values():
                        verify(receipt)
                    corpus, frontend = read(identity[0]), read(identity[1])
                    candidates = {value['id']: value for value in read(identity[2])}
                    if protocol['source_enrichment']:
                        corpus, _ = admission_runner._enrich(corpus, frontend, candidates, identity[0], directory, 0)
                    cached = identity
                candidate = program_candidate(candidates[row['candidate_id']])
                case_source = Path(identity[0]).parent
                issue = (case_source/'issue.md').read_text()
                request, decision = review(corpus, frontend, candidate, issue, directory/'initial_review', protocol, budget)
                chosen = candidate if decision.get('alarm_eligible') else None
                if chosen is None and request is not None and decision['status']=='semantic_rejected':
                    proposal = review_repair.prepare(corpus, frontend, candidate, issue, request, decision,
                        max_prompt_bytes=protocol['max_prompt_bytes'], max_output_tokens=protocol['repair_output_tokens'])
                    repair_request = proposal.pop('request')
                    write(directory/'repair/analysis.json', proposal)
                    if repair_request:
                        content, receipt = budget.call(repair_request, directory/'repair')
                        proposals = (review_repair.validate(repair_request, content, corpus,
                            finish_reason=receipt.get('finish_reason')) if content is not None else dict(revisions=[]))
                        write(directory/'repair/validation.json', proposals)
                        if proposals['revisions']:
                            if len(proposals['revisions']) != 1:
                                raise ValueError('Exactly one program was offered for repair')
                            repaired = proposals['revisions'][0]
                            _, repaired_decision = review(corpus, frontend, repaired, issue,
                                directory/'repaired_review', protocol, budget)
                            if repaired_decision.get('alarm_eligible'):
                                chosen = repaired
                outcome = dict(rank=row['rank'], candidate_id=candidate['id'], initial_decision=decision['status'], alert=None)
                if chosen is not None and budget.enough_time(protocol['timeout']+120):
                    write(directory/'selected_program.json', chosen)
                    result = execute(chosen, case_source, corpus, directory/'native', protocol)
                    outcome['native'] = {key: result[key] for key in ('candidate_id', 'controlled_failure', 'runs')}
                    if result['controlled_failure']:
                        outcome['alert'] = dict(case=case['case'], rank=row['rank'], candidate_id=chosen['id'],
                            repaired=chosen['id']!=candidate['id'], program=frozen(directory/'selected_program.json'),
                            native=frozen(directory/'native/native_outcome.json'), validity='model_hypothesis_pending_independent_audit')
                write(directory/'outcome.json', outcome)
                attempts.append(outcome)
                print(json.dumps(dict(case=case['case'], rank=row['rank'], alert=bool(outcome['alert']), **budget.totals())), flush=True)
                if outcome['alert']:
                    alert = outcome['alert']; break
                if budget.totals()['calls'] >= protocol['max_model_calls']:
                    break
            result = dict(case=case['case'], attempts=attempts, alert=alert)
            write(case_dir/'result.json', result)
            case_results.append(result)
        admission_runner.verify_seal(protocol['algorithm'])
        summary = dict(version=VERSION, denominator=len(protocol['cases']), cases=case_results,
            alerts=[row['alert'] for row in case_results if row['alert']], **budget.totals(),
            independent_audit_complete=False, completed_utc=now().isoformat())
        write(root/'summary.json', summary)
        return {key: value for key, value in summary.items() if key not in {'cases','alerts'}} | {'reported_alerts':len(summary['alerts'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--inventory', type=Path, default=ROOT/'research/false_positive_baseline_20261001.json')
    parser.add_argument('--frontier', type=Path, default=ROOT/'results/fp_reduction_20261002/edited_contract_call_frontier_v1')
    parser.add_argument('--gate', choices=['compact','ledger'], default='ledger')
    parser.add_argument('--max-per-case', type=int, default=2)
    parser.add_argument('--max-model-calls', type=int, default=102)
    parser.add_argument('--max-total-tokens', type=int, default=1200000)
    parser.add_argument('--deadline-utc', default='2026-10-04T01:51:21Z')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--enrich-sources', action='store_true')
    options = parser.parse_args()
    print(json.dumps(prepare(options) if options.stage=='prepare' else run(options)))
