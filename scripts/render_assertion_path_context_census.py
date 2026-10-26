"""Render all supported original assertions in supplied Python source corpora."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prototypes.assertion_write_origin import Index
from prototypes.assertion_path_context import render_context
from relation_search.checkpoint import digest, read, write
from scripts.analyze_assertion_write_origin_census import analyze_corpus


def run(source, cases, output):
    output.mkdir(parents=True, exist_ok=False)
    code = [Path(__file__), ROOT / 'prototypes/assertion_path_context.py',
            ROOT / 'prototypes/assertion_write_origin.py', ROOT / 'scripts/analyze_assertion_write_origin_census.py']
    write(output / 'protocol.json', dict(source=str(source.resolve()), cases=cases,
        corpus_sha256={case:digest(source / case / 'corpus.json') for case in cases},
        code_sha256={str(p.relative_to(ROOT)):digest(p) for p in code},
        order='all registered assertions and referenced helpers/capsules; deterministic source span order',
        support='existing statically_bound_partial_slice facts only; unsupported observations stay in denominator',
        target_labels_used=False, provider_calls=0, subject_executions=0,
        purpose='deterministic input-side source evidence, not coverage feedback or oracle inference'))
    for path in code:
        destination = output / 'code_snapshot' / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    summary = {}
    for case in cases:
        corpus = read(source / case / 'corpus.json')
        analysis = analyze_corpus(corpus)
        index = Index(corpus['sources'])
        records, sizes = [], []
        for row in analysis['assertions']:
            supported = [r for r in row['analysis'].get('reads', [])
                         if r['status'] == 'statically_bound_partial_slice']
            record = dict(assertion_id=row['assertion_id'], span=row['span'],
                          status=row['status'], supported_reads=len(supported))
            if supported:
                text = render_context(None, row['analysis'], index=index)
                path = output / case / (row['assertion_id'] + '.md')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                paths = [p for r in supported for p in r['writer_paths']]
                record.update(context=str(path.relative_to(output)), context_sha256=digest(path),
                    context_bytes=len(text.encode()), writer_paths=len(paths),
                    test_operation_paths=sum(p['root']['kind'] == 'test_operation' for p in paths),
                    possible_exit_sites=sum(len(t.get('possible_bypass_sites', [])) for r in supported
                        for p in r['writer_paths'] for t in [*p['calls'], *[w for w in r['writers'] if w['method'] == p['writer_method']]]))
                sizes.append(len(text.encode()))
            records.append(record)
        write(output / case / 'analysis.json', analysis)
        write(output / case / 'rendered.json', records)
        summary[case] = dict(assertions=analysis['summary']['unique_assertions'], rendered=len(sizes),
            unsupported=analysis['summary']['unsupported_assertions'],
            supported_reads=sum(r['supported_reads'] for r in records),
            contexts_with_operation_path=sum(r.get('test_operation_paths', 0) > 0 for r in records),
            contexts_with_possible_exit=sum(r.get('possible_exit_sites', 0) > 0 for r in records),
            context_bytes=dict(min=min(sizes, default=0), max=max(sizes, default=0), total=sum(sizes),
                               median=sorted(sizes)[len(sizes)//2] if sizes else 0),
            unsupported_reasons=analysis['summary']['unsupported_reason_occurrences'])
        print(json.dumps(dict(case=case, rendered=len(sizes), assertions=len(records))), flush=True)
    write(output / 'summary.json', summary)
    write(output / 'seal.json', dict(files_sha256={str(p.relative_to(output)):digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--cases', required=True, nargs='+')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    run(args.source, args.cases, args.output)
