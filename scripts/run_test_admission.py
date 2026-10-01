"""Freeze source-only applicability questions and dispatch bounded judgments.

This is an incremental filter experiment over immutable native executions, not
a fresh test-synthesis run. Evaluation labels select evaluation strata only;
they never enter questions or admission decisions. No hidden/reference code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT/'scripts'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from relation_search import admission
from relational_gap.provider import dispatch
from scripts.evaluate_test_validity import digest, read, selected_records, write_new


def identity():
    paths = ['relation_search/admission.py', 'relation_search/test_roles.py',
             'relation_search/test_preconditions.py', 'relation_search/oracle_evidence.py',
             'relation_search/instrument.py', 'relational_gap/provider.py',
             'scripts/run_test_admission.py']
    return {path: digest(ROOT/path) for path in paths}


def prepare(args):
    baseline = read(args.input)
    versions = identity()
    records, seen, cache, items = selected_records(baseline, args.scope), set(), {}, []
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    for row in records:
        logical_id = (row['case'], row['candidate_id'])
        if logical_id in seen:
            continue
        seen.add(logical_id)
        paths = tuple(row['inputs'][name]['path'] for name in ('corpus', 'frontend', 'candidates'))
        if paths not in cache:
            for name in ('corpus', 'frontend', 'candidates'):
                receipt = row['inputs'][name]
                if digest(receipt['path']) != receipt['sha256']:
                    raise ValueError('Source input changed')
            cache[paths] = (read(paths[0]), read(paths[1]),
                           {c['id']: c for c in read(paths[2])})
        corpus, frontend, candidates = cache[paths]
        candidate = candidates[row['candidate_id']]
        issue_path = Path(row['inputs']['corpus']['path']).parent/'issue.md'
        issue = issue_path.read_text()
        result = admission.prepare(corpus, frontend, candidate, issue,
            max_prompt_bytes=args.max_prompt_bytes, max_output_tokens=args.output_token_limit)
        name = 'item_'+str(len(items)).zfill(4)
        directory = output/name
        directory.mkdir()
        request = result.pop('request')
        write_new(directory/'analysis.json', result)
        if request is not None:
            write_new(directory/'request.json', request)
        item = dict(name=name, key=row['key'], case=row['case'], candidate_id=row['candidate_id'],
            source_inputs=row['inputs'], issue=dict(path=str(issue_path), sha256=digest(issue_path)),
            analysis_path=str((directory/'analysis.json').resolve()),
            request_path=str((directory/'request.json').resolve()) if request else None,
            request_sha256=digest(directory/'request.json') if request else None)
        items.append(item)
        print(json.dumps(dict(phase='prepared', completed=len(items), case=row['case'],
                              status=result['status'], prompt_bytes=result.get('prompt_bytes'))), flush=True)
    if versions != identity():
        raise ValueError('Algorithm changed while preparing frozen requests')
    summary = dict(stage='prepared', created_utc=datetime.now(timezone.utc).isoformat(),
        baseline=dict(path=str(args.input.resolve()), sha256=digest(args.input)), scope=args.scope,
        algorithm=versions, items=items, max_model_calls=args.max_model_calls,
        max_total_tokens=args.max_total_tokens, max_prompt_bytes=args.max_prompt_bytes,
        output_token_limit=args.output_token_limit, provider_calls=0,
        experiment='incremental_admission_of_frozen_generated_tests',
        validity_labels_not_used_in_admission=True, native_executions_reused=True)
    write_new(output/'prepared.json', summary)
    return dict(items=len(items), requests=sum(bool(row['request_path']) for row in items))


def _token_upper_bound(request):
    # A UTF-8 byte is a conservative bound for supported text tokenizers. The
    # fixed allowance covers JSON/chat framing. This is a dispatch reservation,
    # not a substitute for reporting measured provider usage.
    return len(request['system'].encode()) + len(request['prompt'].encode()) + request['max_tokens'] + 256


def run(args):
    prepared = read(args.input/'prepared.json')
    rows, calls, accounted_tokens, usage_missing = [], 0, 0, 0
    for item in prepared['items']:
        directory = args.input/item['name']
        decision_path = directory/'decision.json'
        request_path = item['request_path']
        if request_path:
            if digest(request_path) != item['request_sha256']:
                raise ValueError('Frozen semantic request changed')
            request = read(request_path)
            completion = directory/'completion'
            manifest = completion/'manifest.json'
            if not manifest.exists():
                if calls >= prepared['max_model_calls'] or accounted_tokens + _token_upper_bound(request) > prepared['max_total_tokens']:
                    decision = dict(status='unknown', alarm_eligible=False, reason='model_budget',
                                    semantic_validity='unconfirmed')
                else:
                    dispatch(request, completion, root=ROOT)
                    decision = None
            else:
                decision = None  # Resume reads the fixed receipt; never retries.
            if manifest.exists():
                receipt = read(manifest)
                calls += receipt.get('external_model_calls', 0)
                usage = receipt.get('usage') or {}
                if usage.get('total_tokens') is not None:
                    accounted_tokens += usage['total_tokens']
                elif usage.get('prompt_tokens') is not None and usage.get('completion_tokens') is not None:
                    accounted_tokens += usage['prompt_tokens'] + usage['completion_tokens']
                elif receipt.get('external_model_calls'):
                    accounted_tokens += _token_upper_bound(request)
                    usage_missing += 1
                if receipt['status'] == 'complete':
                    decision = admission.decide(request, (completion/'completion.txt').read_text(),
                                                finish_reason=receipt.get('finish_reason'))
                else:
                    decision = dict(status='unknown', alarm_eligible=False, reason='provider_incomplete',
                                    semantic_validity='unconfirmed')
        else:
            analysis = read(item['analysis_path'])
            decision = dict(status=analysis['status'], alarm_eligible=False,
                            semantic_validity='static_contradiction' if analysis['status'] == 'static_invalid' else 'unconfirmed')
        if decision_path.exists():
            if read(decision_path) != decision:
                raise ValueError('Frozen admission decision changed')
        else:
            write_new(decision_path, decision)
        rows.append(dict(key=item['key'], case=item['case'], candidate_id=item['candidate_id'],
                         decision=decision, decision_path=str(decision_path.resolve())))
        print(json.dumps(dict(phase='decided', completed=len(rows), status=decision['status'],
                              calls=calls, accounted_tokens=accounted_tokens)), flush=True)
    summary = dict(stage='complete', experiment=prepared['experiment'], decisions=rows,
        provider_calls=calls, accounted_tokens=accounted_tokens, usage_missing=usage_missing,
        max_total_tokens=prepared['max_total_tokens'],
        tokens_are_measured_usage_unless_missing=usage_missing == 0,
        reused_native_executions=True, fresh_semantic_requests=True,
        prepared=dict(path=str((args.input/'prepared.json').resolve()), sha256=digest(args.input/'prepared.json')))
    final_path = args.input/'summary.json'
    if final_path.exists():
        if read(final_path) != summary:
            raise ValueError('Frozen summary changed')
    else:
        write_new(final_path, summary)
    return {key: value for key, value in summary.items() if key != 'decisions'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--scope', choices=['all', 'positive', 'development', 'holdout'], default='positive')
    parser.add_argument('--max-prompt-bytes', type=int, default=64000)
    parser.add_argument('--output-token-limit', type=int, default=1024)
    parser.add_argument('--max-model-calls', type=int, default=64)
    parser.add_argument('--max-total-tokens', type=int, default=500000)
    args = parser.parse_args()
    if args.stage == 'prepare' and args.output is None:
        parser.error('prepare requires --output')
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
