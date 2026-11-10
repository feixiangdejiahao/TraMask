#!/usr/bin/env python3
"""Export the cited audit inputs, or verify the exported evidence in a fresh clone."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from verify_combination_alternatives_audit import read, verify_case


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def export(audit, bundle):
    bundle.mkdir(parents=True)
    index = read(audit / 'case_index.json')
    inputs = defaultdict(set)
    records = []
    for entry in index:
        directory = audit / 'cases' / entry['case']
        case = read(directory / 'case.json')
        review = read(directory / 'manual_review.json')
        evaluation = read(directory / 'evaluation_failures.json')
        for key in ['trajectory', 'issue', 'patch', 'verifier_patch']:
            inputs[case[key]].add(key)
        inputs[evaluation['source']].add('ctrf')
        for owner in review['materials'] + review['agent_process']['explanations']:
            for ref in owner['refs']:
                if ref['channel'] in {'repo', 'issue'}:
                    inputs[ref['path']].add('quoted_reference')
        records.append((entry['case'], case, review, evaluation))
    manifest = []
    paths = {}
    for original, roles in sorted(inputs.items()):
        data = Path(original).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = bundle / 'sources' / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        paths[original] = str(target)
        manifest.append({'original': original, 'path': str(target), 'sha256': digest,
                         'bytes': len(data), 'roles': sorted(roles)})
    for sid, case, review, evaluation in records:
        directory = bundle / 'cases' / sid
        directory.mkdir(parents=True)
        for key in ['trajectory', 'issue', 'patch', 'verifier_patch']:
            case[key] = paths[case[key]]
        for owner in review['materials'] + review['agent_process']['explanations']:
            for ref in owner['refs']:
                if ref['channel'] in {'repo', 'issue'}:
                    ref['path'] = paths[ref['path']]
        evaluation['source'] = paths[evaluation['source']]
        save(directory / 'case.json', case)
        save(directory / 'manual_review.json', review)
        save(directory / 'evaluation_failures.json', evaluation)
    save(bundle / 'case_index.json', index)
    save(bundle / 'manifest.json', {'audit': str(audit), 'files': manifest,
                                  'change': 'Portable copies change loader paths only; frozen originals remain in audit.'})


def verify(bundle):
    manifest = read(bundle / 'manifest.json')
    for file in manifest['files']:
        data = Path(file['path']).read_bytes()
        assert len(data) == file['bytes']
        assert hashlib.sha256(data).hexdigest() == file['sha256']
    cases = []
    for entry in read(bundle / 'case_index.json'):
        directory = bundle / 'cases' / entry['case']
        projection = read(directory / 'evaluation_failures.json')
        tests = read(projection['source'])['results']['tests']
        failed = [test for test in tests if test['status'] == 'failed']
        assert failed == projection['failed_tests'], entry['case']
        assert dict(Counter(test['status'] for test in tests)) == projection['status_counts']
        result = verify_case(directory)
        assert not result['errors'], result
        cases.append(result)
    result = {'status': 'passed', 'cases': len(cases), 'exact_quotes': sum(c['checked_quotes'] for c in cases),
              'source_paths': len(manifest['files']),
              'source_contents': len({f['sha256'] for f in manifest['files']}),
              'unique_source_bytes': sum(f.stat().st_size for f in (bundle / 'sources').glob('*/*')),
              'evaluation_records': sum(len(read(bundle / 'cases' / e['case'] / 'evaluation_failures.json')['failed_tests'])
                                        for e in read(bundle / 'case_index.json'))}
    save(bundle / 'verification.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'verify'])
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--audit', type=Path)
    args = parser.parse_args()
    if args.action == 'export':
        assert args.audit is not None
        export(args.audit, args.bundle)
    print(json.dumps(verify(args.bundle), indent=2))


if __name__ == '__main__':
    main()
