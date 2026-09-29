"""Enumerate registered Python test assertions; no target-label inputs.

Static retrieval only. All cases use one source index each. Supported reads
receive a boolean evidence tier; ties retain deterministic source order.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experimental.assertion_write_origin import Index, analyze_assertion

CASES = ('P1', 'P2', 'P3', 'P4', 'N01', 'N02', 'N03', 'N04')
TIERS = ('multiple_writers_and_prior_operation', 'prior_operation_only',
         'multiple_writers_only', 'bound_writer_only')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def span_key(span):
    return span['path'], span['start_byte'], span['end_byte']


def contains(outer, inner):
    return outer['path'] == inner['path'] and outer['start_byte'] <= inner['start_byte'] and inner['end_byte'] <= outer['end_byte']


def enumerate_assertions(corpus, index):
    ranges = defaultdict(list)
    missing_scopes = []
    tests = corpus['tests']
    for test_id, test in sorted(tests.items()):
        definitions = [('registered_test', test.get('definition_span', test.get('span')))]
        definitions += [('referenced_helper', helper.get('span')) for helper in test.get('support', {}).get('helpers', [])]
        for kind, span in definitions:
            if not span or span['path'] not in index.paths:
                missing_scopes.append(dict(test_id=test_id, kind=kind, span=span))
                continue
            ranges[span['path']].append((span, test_id, kind))
    records = {}
    ast_by_span = {}
    for path, module in sorted(index.paths.items()):
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Assert):
                continue
            span = module.span(node)
            key = span_key(span)
            ast_by_span[key] = node
            owners = [(test_id, kind) for scope, test_id, kind in ranges[path] if contains(scope, span)]
            if owners:
                records[key] = dict(span=span, form='python_assert', assertion=module.text(node),
                    test_ids=sorted({owner[0] for owner in owners}),
                    enumerated_from=sorted({owner[1] for owner in owners}), capsule_ids=[])
    # Preserve framework assertions already extracted by the corpus frontend.
    # Unsupported syntax remains in the denominator, rather than disappearing.
    for capsule in corpus.get('capsules', []):
        span = capsule.get('assertion_span')
        if not span:
            continue
        key = span_key(span)
        owner = capsule.get('test_id')
        if key not in records:
            module = index.paths.get(span['path'])
            text = module.code_bytes[span['start_byte']:span['end_byte']].decode() if module else capsule.get('assertion', '')
            form = 'python_assert' if key in ast_by_span else 'unparseable_source_assertion' if module is None and text.lstrip().startswith('assert ') else 'framework_or_non_assert_observation'
            records[key] = dict(span=span, form=form, assertion=text,
                                test_ids=[], enumerated_from=[], capsule_ids=[])
        row = records[key]
        if owner in tests and owner not in row['test_ids']:
            row['test_ids'].append(owner)
            row['test_ids'].sort()
        if 'corpus_capsule' not in row['enumerated_from']:
            row['enumerated_from'].append('corpus_capsule')
        row['capsule_ids'].append(capsule['id'])
    for row in records.values():
        row['assertion_id'] = hashlib.sha256(json.dumps(row['span'], sort_keys=True).encode()).hexdigest()[:24]
    return [records[key] for key in sorted(records)], missing_scopes


def retrieval_evidence(analysis):
    evidence = []
    for read in analysis.get('reads', []):
        if read['status'] != 'statically_bound_partial_slice':
            continue
        reachable_methods = {path['writer_method'] for path in read['writer_paths']}
        writers = [writer for writer in read['writers'] if writer['method'] in reachable_methods]
        multiple = len({span_key(writer['span']) for writer in writers}) >= 2
        operation = any(path['root']['kind']=='test_operation' for path in read['writer_paths'])
        tier = TIERS[0] if multiple and operation else TIERS[1] if operation else TIERS[2] if multiple else TIERS[3]
        evidence.append(dict(read_span=read['read_span'], object_binding=read['binding']['object_binding'],
                             class_id=read['binding']['class_id'], storage_field=read['storage_field'],
                             multiple_reachable_writer_sites=multiple,
                             prior_same_binding_operation_has_syntactic_writer_path=operation,
                             reachable_writer_spans=[writer['span'] for writer in writers], tier=tier))
    tier = min((row['tier'] for row in evidence), key=TIERS.index) if evidence else None
    return dict(tier=tier, reads=evidence)


def assign_ranks(rows, source_key):
    supported = sorted((row for row in rows if row['retrieval']['tier'] is not None),
                       key=lambda row: (TIERS.index(row['retrieval']['tier']), source_key(row)))
    grouped = defaultdict(list)
    for rank, row in enumerate(supported, 1):
        row['supported_rank'] = rank
        grouped[row['retrieval']['tier']].append(rank)
    for row in rows:
        row.setdefault('supported_rank', None)
        ranks = grouped.get(row['retrieval']['tier'], [])
        row['evidence_tie_rank_range'] = [min(ranks), max(ranks)] if ranks else None


def analyze_corpus(corpus):
    started = time.monotonic()
    index = Index(corpus['sources'])
    indexed = time.monotonic()
    rows, missing_scopes = enumerate_assertions(corpus, index)
    enumerated = time.monotonic()
    reason_counts, mixed_read_reasons = Counter(), Counter()
    for row in rows:
        if row['form'] == 'unparseable_source_assertion':
            analysis = dict(status='unsupported', reason='source_missing_or_unparseable', reads=[])
        elif row['form'] != 'python_assert':
            analysis = dict(status='unsupported', reason='framework_assertion_not_supported', reads=[])
        else:
            span = row['span']
            analysis = analyze_assertion(None, span['path'], span['line'], index=index,
                assertion_start_byte=span['start_byte'], include_source_hashes=False)
            analysis.pop('source_sha256', None)
            analysis.pop('parse_errors', None)
        row['analysis'] = analysis
        row['retrieval'] = retrieval_evidence(analysis)
        supported = row['retrieval']['tier'] is not None
        row['status'] = 'supported_partial' if supported else 'unsupported'
        reasons = {read['reason'] for read in analysis.get('reads', []) if read['status']=='unsupported'}
        if not supported:
            reasons.add(analysis.get('reason') or analysis.get('unsupported_reason') or 'no_supported_field_read')
            # Per-assertion reasons may overlap; never sum them as a count of q.
            reason_counts.update(reasons)
        else:
            mixed_read_reasons.update(reasons)
    assign_ranks(rows, lambda row: span_key(row['span']))
    tests = []
    for test_id, record in sorted(corpus['tests'].items()):
        owned = [row for row in rows if test_id in row['test_ids']]
        supported = [row for row in owned if row['retrieval']['tier'] is not None]
        best = min((row['retrieval']['tier'] for row in supported), key=TIERS.index) if supported else None
        tests.append(dict(test_id=test_id, span=record.get('definition_span', record.get('span')),
                          assertion_count=len(owned), supported_assertion_count=len(supported),
                          assertion_ids=[row['assertion_id'] for row in owned],
                          retrieval=dict(tier=best),
                          status='supported_partial' if supported else 'no_supported_assertion' if owned else 'no_enumerated_assertion'))
    assign_ranks(tests, lambda row: (*span_key(row['span']), row['test_id']))
    return dict(scope='all registered corpus tests, their explicitly referenced helpers, and all corpus assertion capsules',
        ranking='boolean source evidence only; ties use source path/byte order, no learned or weighted score',
        tier_order=list(TIERS), index_builds=1,
        summary=dict(registered_tests=len(tests), tests_with_supported_assertion=sum(t['status']=='supported_partial' for t in tests),
            tests_without_enumerated_assertion=sum(t['status']=='no_enumerated_assertion' for t in tests),
            unique_assertions=len(rows), python_assert_statements=sum(r['form']=='python_assert' for r in rows),
            framework_or_non_assert_observations=sum(r['form']=='framework_or_non_assert_observation' for r in rows),
            unparseable_source_assertions=sum(r['form']=='unparseable_source_assertion' for r in rows),
            supported_partial_assertions=sum(r['status']=='supported_partial' for r in rows),
            unsupported_assertions=sum(r['status']=='unsupported' for r in rows),
            supported_tiers=dict(Counter(r['retrieval']['tier'] for r in rows if r['retrieval']['tier'])),
            unsupported_reason_occurrences=dict(sorted(reason_counts.items())),
            unsupported_reads_inside_partially_supported_assertions=dict(sorted(mixed_read_reasons.items())),
            assertions_without_capsule=sum(not r['capsule_ids'] for r in rows)),
        timings_seconds=dict(index=round(indexed-started, 3), enumeration=round(enumerated-indexed, 3),
                             total=round(time.monotonic()-started, 3)),
        source_sha256={path: hashlib.sha256(module.code_bytes).hexdigest() for path, module in sorted(index.paths.items())},
        parse_errors=index.parse_errors, missing_scopes=missing_scopes, assertions=rows, tests=tests,
        interpretation='Static retrieval support only. No target labels were read, no subjects or models executed. Syntactic paths do not prove execution, oracle validity, or bug detection.')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new output directory; do not overwrite the first census')
    args.output.mkdir(parents=True)
    implementation = [Path(__file__).resolve(), ROOT/'experimental/assertion_write_origin.py']
    protocol = dict(created_utc=datetime.now(timezone.utc).isoformat(), cases=list(CASES),
        source=str(args.source.resolve()), corpus_sha256={case:digest(args.source/case/'corpus.json') for case in CASES},
        code_sha256={str(path):digest(path) for path in implementation},
        entrypoint=[sys.executable, *sys.argv], tier_order=list(TIERS),
        source_order='path, start_byte, end_byte; no corpus retrieval rank',
        scope='registered tests + explicitly referenced helper spans + corpus assertion capsules',
        targets_used=False, provider_calls=0, subject_executions=0)
    (args.output/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    for path in implementation:
        shutil.copyfile(path, args.output/path.name)
    summary = {}
    for case in CASES:
        corpus = json.loads((args.source/case/'corpus.json').read_text())
        result = analyze_corpus(corpus)
        result.update(case=case, protocol_sha256=digest(args.output/'protocol.json'))
        output = args.output/(case+'.json')
        output.write_text(json.dumps(result, indent=2)+'\n')
        summary[case] = dict(**result['summary'], timings_seconds=result['timings_seconds'], output_sha256=digest(output))
        print(json.dumps(dict(case=case, **result['summary'], timings_seconds=result['timings_seconds'])), flush=True)
    (args.output/'summary.json').write_text(json.dumps(dict(protocol_sha256=digest(args.output/'protocol.json'), cases=summary), indent=2)+'\n')


if __name__ == '__main__':
    main()
