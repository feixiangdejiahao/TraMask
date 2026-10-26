"""Source-only census of assertion-helper expected slots in fixed Go corpora."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experimental.go_assertion_helper import HelperIndex
from relation_search.checkpoint import digest, read, write


def run(inputs, output):
    output.mkdir(parents=True, exist_ok=False)
    inventory = []
    for path in sorted(inputs.glob('*/corpus.json')):
        corpus = read(path)
        inventory.append(dict(case=path.parent.name, path=str(path.resolve()),
            sha256=digest(path), language=corpus['language']))
    selected = [row for row in inventory if row['language'] == 'go']
    sources = ['experimental/go_assertion_helper.py', 'experimental/go_arity_guard.py',
               'anchor_retrieval/syntax.py', 'scripts/analyze_go_assertion_helpers.py']
    code = {}
    for relative in sources:
        destination = output / 'algorithm_snapshot' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
        code[relative] = digest(ROOT / relative)
    protocol = dict(created_at=datetime.now(timezone.utc).isoformat(),
        inputs=inventory, selection='all corpus files with language == go',
        model_calls=0, docker_calls=0, outcomes_or_target_labels=False,
        code_sha256=code,
        denominator='direct calls inside registered tests whose same package contains '
            'a function of that name with an explicitly imported *testing.T parameter; '
            'unresolved/ambiguous calls are retained as unknown')
    write(output / 'protocol.json', protocol)
    write(output / 'protocol.seal.json', dict(sha256=digest(output / 'protocol.json')))
    totals, cases, reasons = Counter(), [], Counter()
    for item in selected:
        path = Path(item['path'])
        if digest(path) != item['sha256']:
            raise ValueError('Source corpus changed')
        start = time.monotonic()
        index = HelperIndex(read(path))
        report = index.census()
        report.update(case=item['case'], corpus_sha256=item['sha256'], seconds=time.monotonic() - start)
        write(output / item['case'] / 'census.json', report)
        total_helpers = len(report['helper_definitions'])
        supported_helpers = sum(row['status'] == 'supported' for row in report['helper_definitions'])
        counts = report['counts']
        denominator = counts.get('same_package_testing_helper_name_calls', 0)
        row = dict(case=item['case'], helper_definitions=total_helpers,
            supported_helper_definitions=supported_helpers, **counts,
            supported_call_rate=counts.get('supported', 0) / denominator if denominator else None,
            seconds=report['seconds'], report_sha256=digest(output / item['case'] / 'census.json'))
        cases.append(row)
        totals.update(counts)
        reasons.update(report['unknown_reasons'])
        write(output / 'summary.json', dict(finished=False, cases=cases,
            totals=dict(totals), unknown_reasons=dict(reasons)))
        print(json.dumps(row, sort_keys=True), flush=True)
    result = dict(finished=True, input_corpora=len(inventory), go_corpora=len(selected),
        cases=cases, totals=dict(totals), unknown_reasons=dict(reasons),
        protocol_sha256=digest(output / 'protocol.json'), correctness_evaluated=False)
    write(output / 'summary.json', result)
    write(output / 'summary.seal.json', dict(sha256=digest(output / 'summary.json')))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    run(args.inputs, args.output)
