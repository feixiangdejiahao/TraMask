"""Freeze source-only applicability questions and dispatch bounded judgments.

This is an incremental filter experiment over immutable native executions, not
a fresh test-synthesis run. Evaluation labels select evaluation strata only;
they never enter questions or admission decisions. No hidden/reference code.
"""
from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT/'scripts'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from relation_search import admission
from relational_gap.provider import dispatch
from scripts.evaluate_test_validity import (
    digest, frozen, loaded_local_sources, read, selected_records, verify_seal, write_new,
)


METHODS = {'legacy': 'relation_search.admission', 'guarded': 'relation_search.guarded_admission',
           'compact': 'relation_search.compact_admission',
           'compact_contract_guarded': 'relation_search.compact_contract_guarded'}
REQUEST_IDENTITY_VERSION = 'actual-admission-dispatch-fields-v1'
PROVIDER_TIMEOUT_SECONDS = 300


def _method(name):
    if name not in METHODS.values():
        raise ValueError('Unsupported sealed admission module: ' + str(name))
    return importlib.import_module(name)


def _local_module(name):
    path = ROOT.joinpath(*name.split('.'))
    return path.with_suffix('.py').is_file() or (path/'__init__.py').is_file()


def _loaded_sources():
    # Installed packages in the workspace venv are environment dependencies,
    # rather than repository algorithm modules. Their lazy network imports
    # must not invalidate a local algorithm seal after a provider receipt.
    return {name: row for name, row in loaded_local_sources().items()
            if not any(part in {'.venv', 'venv', 'site-packages', 'node_modules'}
                       for part in Path(row['path']).relative_to(ROOT).parts)}


def _preload_local_imports(module):
    """Preload literal local imports, including imports inside helper functions.

    Dynamic module names are not guessed. A new local import discovered during
    preparation causes the seal check to fail instead of silently expanding it.
    """
    queue = [module, sys.modules[__name__], sys.modules['relational_gap.provider']]
    visited = set()
    while queue:
        current = queue.pop()
        name, file = getattr(current, '__name__', ''), getattr(current, '__file__', None)
        if name in visited or not file:
            continue
        visited.add(name)
        path = Path(file).resolve()
        if path.suffix != '.py' or not path.is_relative_to(ROOT):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        package = name if path.name == '__init__.py' else name.rpartition('.')[0]
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if node.level:
                    if not package:
                        raise ValueError('Relative import has no package: ' + str(path))
                    base = importlib.util.resolve_name('.'*node.level + base, package)
                if base:
                    imports.add(base)
                    imports.update(base + '.' + alias.name for alias in node.names if alias.name != '*')
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                target = ast.unparse(node.func)
                if target in {'importlib.import_module', '__import__'}:
                    imports.add(node.args[0].value)
        for imported in sorted(imports):
            parts = imported.split('.')
            for end in range(1, len(parts)+1):
                prefix = '.'.join(parts[:end])
                if _local_module(prefix):
                    queue.append(importlib.import_module(prefix))


def _verify_sources(entry, imported):
    verify_seal(entry)
    verify_seal(imported)
    newly_loaded = set(_loaded_sources()) - set(imported)
    if newly_loaded:
        raise ValueError('Local source imported after the seal; preload it: ' + ', '.join(sorted(newly_loaded)))


def identity():
    """All currently loaded repository sources, rather than a hand-picked list."""
    return {str(Path(row['path']).relative_to(ROOT)): row['sha256'] for row in _loaded_sources().values()}


def _dispatch_fields(request):
    result = dict(system=request['system'], prompt=request['prompt'],
                  thinking=request.get('thinking', 'disabled'),
                  max_tokens=request.get('max_tokens', 16384))
    if 'reasoning_effort' in request:
        result['reasoning_effort'] = request['reasoning_effort']
    return result


def _request_identity(request):
    return hashlib.sha256(json.dumps(_dispatch_fields(request), sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _configure_request(request, args):
    request = copy.deepcopy(request)
    request['thinking'] = getattr(args, 'thinking', 'disabled')
    if request['thinking'] not in {'enabled', 'disabled'}:
        raise ValueError('Unsupported thinking mode')
    request['max_tokens'] = args.output_token_limit
    effort = getattr(args, 'reasoning_effort', None)
    if effort is None:
        request.pop('reasoning_effort', None)
    elif effort in {'low', 'high', 'max'}:
        request['reasoning_effort'] = effort
    else:
        raise ValueError('Unsupported reasoning effort')
    request['id'] = _request_identity(request)
    if 'query_sha256' in request:
        request['query_sha256'] = request['id']
    request['request_identity_version'] = REQUEST_IDENTITY_VERSION
    return request


def _utc_now():
    return datetime.now(timezone.utc)


def _deadline(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).removesuffix(' UTC').replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _run_deadline(args, prepared):
    deadlines = [_deadline(value) for value in (getattr(args, 'deadline_utc', None), prepared.get('deadline_utc')) if value]
    return min(deadlines) if deadlines else None


def _enrich(corpus, frontend, candidates, corpus_path, output, index):
    from relation_search.source_dependencies import enrich_sources
    metadata = Path(corpus_path).parent/'case.json'
    receipt = frozen(metadata)
    case = read(metadata)
    originals = copy.deepcopy(corpus['sources'])
    enriched, provenance = enrich_sources(corpus, frontend, case['repository'],
        candidates=list(candidates.values()), max_added_files=256, max_depth=8)
    if corpus['sources'] != originals or any(enriched['sources'].get(path) != row for path, row in originals.items()):
        raise ValueError('Source enrichment replaced a frozen original source')
    if digest(metadata) != receipt['sha256']:
        raise ValueError('Source case metadata changed during enrichment')
    artifact = dict(case_metadata=receipt, repository=case['repository'],
        added_sources={path: row for path, row in enriched['sources'].items() if path not in originals},
        original_source_sha256={path: hashlib.sha256(row['code'].encode()).hexdigest()
                               for path, row in originals.items()},
        provenance=provenance, local_only_artifact=True)
    path = output/'source_context'/('context_'+str(index).zfill(4)+'.json')
    write_new(path, artifact)
    return enriched, frozen(path)


def prepare(args):
    if isinstance(args.output_token_limit, bool) or not isinstance(args.output_token_limit, int) or not 1 <= args.output_token_limit <= 16384:
        raise ValueError('Unsupported output token budget')
    baseline = read(args.input)
    method_name = getattr(args, 'method', 'legacy')
    if method_name not in METHODS:
        raise ValueError('Unsupported admission method')
    module_name = METHODS[method_name]
    module = _method(module_name)
    _preload_local_imports(module)
    entry = {module_name: frozen(module.__file__)}
    imported = _loaded_sources()
    versions = identity()
    records, seen, cache, items = selected_records(baseline, args.scope), set(), {}, []
    enrichment = {}
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
            if getattr(args, 'enrich_repository_sources', False):
                corpus, frontend, candidates = cache[paths]
                corpus, artifact = _enrich(corpus, frontend, candidates, paths[0], output, len(enrichment))
                cache[paths] = corpus, frontend, candidates
                enrichment[paths] = artifact
        corpus, frontend, candidates = cache[paths]
        candidate = candidates[row['candidate_id']]
        issue_path = Path(row['inputs']['corpus']['path']).parent/'issue.md'
        issue = issue_path.read_text()
        _verify_sources(entry, imported)
        result = module.prepare(corpus, frontend, candidate, issue,
            max_prompt_bytes=args.max_prompt_bytes, max_output_tokens=args.output_token_limit)
        name = 'item_'+str(len(items)).zfill(4)
        directory = output/name
        directory.mkdir()
        request = result.pop('request')
        if request is not None:
            request = _configure_request(request, args)
            size = len(request['system'].encode()) + len(request['prompt'].encode())
            if size > args.max_prompt_bytes:
                result.update(status='unknown_prompt_budget', alarm_eligible=False,
                    required_bytes=size, max_prompt_bytes=args.max_prompt_bytes, truncated=False)
                request = None
            else:
                request['prompt_bytes'] = size
        write_new(directory/'analysis.json', result)
        if request is not None:
            write_new(directory/'request.json', request)
        item = dict(name=name, key=row['key'], case=row['case'], candidate_id=row['candidate_id'],
            source_inputs=row['inputs'], issue=dict(path=str(issue_path), sha256=digest(issue_path)),
            analysis_path=str((directory/'analysis.json').resolve()),
            request_path=str((directory/'request.json').resolve()) if request else None,
            request_sha256=digest(directory/'request.json') if request else None)
        if paths in enrichment:
            item['source_context'] = enrichment[paths]
        items.append(item)
        print(json.dumps(dict(phase='prepared', completed=len(items), case=row['case'],
                              status=result['status'], prompt_bytes=result.get('prompt_bytes'))), flush=True)
    _verify_sources(entry, imported)
    if versions != identity():
        raise ValueError('Algorithm changed while preparing frozen requests')
    summary = dict(stage='prepared', created_utc=datetime.now(timezone.utc).isoformat(),
        baseline=dict(path=str(args.input.resolve()), sha256=digest(args.input)), scope=args.scope,
        algorithm=versions, algorithm_entry_modules=entry, imported_source_modules=imported,
        method=method_name, method_module=module_name, request_identity_version=REQUEST_IDENTITY_VERSION,
        thinking=getattr(args, 'thinking', 'disabled'), reasoning_effort=getattr(args, 'reasoning_effort', None),
        enrich_repository_sources=getattr(args, 'enrich_repository_sources', False),
        source_context_artifacts=list(enrichment.values()),
        deadline_utc=_deadline(getattr(args, 'deadline_utc', None)).isoformat() if getattr(args, 'deadline_utc', None) else None,
        items=items, max_model_calls=args.max_model_calls,
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
    module_name = prepared.get('method_module', METHODS['legacy'])
    module = _method(module_name)
    if prepared.get('algorithm_entry_modules'):
        sealed = prepared['algorithm_entry_modules'].get(module_name)
        if sealed is None or Path(module.__file__).resolve() != Path(sealed['path']).resolve():
            raise ValueError('Sealed admission module binding changed')
        _preload_local_imports(module)
        _verify_sources(prepared['algorithm_entry_modules'], prepared['imported_source_modules'])
    deadline = _run_deadline(args, prepared)
    rows, calls, accounted_tokens, usage_missing = [], 0, 0, 0
    for item in prepared['items']:
        directory = args.input/item['name']
        if item.get('source_context') and digest(item['source_context']['path']) != item['source_context']['sha256']:
            raise ValueError('Frozen source enrichment artifact changed')
        decision_path = directory/'decision.json'
        request_path = item['request_path']
        if request_path:
            if digest(request_path) != item['request_sha256']:
                raise ValueError('Frozen semantic request changed')
            request = read(request_path)
            if request.get('request_identity_version') == REQUEST_IDENTITY_VERSION and request['id'] != _request_identity(request):
                raise ValueError('Frozen dispatch identity does not match actual request fields')
            completion = directory/'completion'
            manifest = completion/'manifest.json'
            if not manifest.exists():
                if decision_path.exists():
                    decision = read(decision_path)  # A prior no-dispatch unknown is immutable too.
                elif calls >= prepared['max_model_calls'] or accounted_tokens + _token_upper_bound(request) > prepared['max_total_tokens']:
                    decision = dict(status='unknown', alarm_eligible=False, reason='model_budget',
                                    semantic_validity='unconfirmed')
                else:
                    remaining = (deadline - _utc_now()).total_seconds() if deadline else None
                    if remaining is not None and remaining < PROVIDER_TIMEOUT_SECONDS:
                        decision = dict(status='unknown', alarm_eligible=False, reason='deadline',
                            semantic_validity='unconfirmed', deadline_utc=deadline.isoformat(),
                            required_seconds=PROVIDER_TIMEOUT_SECONDS, remaining_seconds=remaining)
                    else:
                        dispatch(request, completion, root=ROOT)
                        decision = None
            else:
                decision = None  # Resume reads the fixed receipt; never retries.
            if manifest.exists():
                receipt = read(manifest)
                if receipt.get('request_id') is not None and receipt['request_id'] != request['id']:
                    raise ValueError('Provider receipt belongs to a different frozen request')
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
                    decision = module.decide(request, (completion/'completion.txt').read_text(),
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
    if 'method_module' in prepared:
        summary['method_module'] = module_name
    if prepared.get('algorithm_entry_modules'):
        _verify_sources(prepared['algorithm_entry_modules'], prepared['imported_source_modules'])
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
    parser.add_argument('--method', choices=sorted(METHODS), default='legacy')
    parser.add_argument('--thinking', choices=['disabled', 'enabled'], default='disabled')
    parser.add_argument('--reasoning-effort', choices=['low', 'high', 'max'])
    parser.add_argument('--deadline-utc', help='UTC ISO timestamp; dispatch requires at least 300 seconds remaining')
    parser.add_argument('--enrich-repository-sources', action='store_true',
        help='Recover bounded explicit source dependencies; seal additions locally without attaching the full corpus to a request')
    args = parser.parse_args()
    if args.stage == 'prepare' and args.output is None:
        parser.error('prepare requires --output')
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
