#!/usr/bin/env python3
"""Check manual provenance and enumerate the explicitly reviewed source packages."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_bytes())


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


def reference_texts(ref, steps, documents):
    channel = ref['channel']
    if channel in {'repo', 'issue'}:
        path = Path(ref['path'])
        if path not in documents:
            documents[path] = path.read_bytes().decode('utf-8')
        return [documents[path]]
    step = steps[ref['step']]
    if channel == 'command':
        return list(strings(step['tool_calls'][ref['call']]['arguments']))
    if channel in {'reasoning', 'message'}:
        return [step['reasoning_content' if channel == 'reasoning' else 'message']]
    assert channel == 'output', channel
    result = step['observation']['results'][ref['call']]['content']
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        return [result]
    return list(strings(parsed))


def verify_case(directory):
    case = read(directory / 'case.json')
    review = read(directory / 'manual_review.json')
    assert review['case_id'] == case['screen_id']
    original = read(case['trajectory'])
    steps = {s['step_id']: s for s in original['steps']}
    errors = []
    cursor = 1
    for start, end in sorted(review['full_read']['line_ranges']):
        assert 1 <= start <= end <= case['fulltext_lines']
        if start > cursor:
            errors.append({'kind': 'unread_lines', 'start': cursor, 'end': start - 1})
        cursor = max(cursor, end + 1)
    if cursor <= case['fulltext_lines']:
        errors.append({'kind': 'unread_lines', 'start': cursor, 'end': case['fulltext_lines']})
    assert review['full_read']['steps'] == case['steps']
    assert review['full_read']['metadata_read'] is True
    assert not review['full_read']['unread']
    materials = {m['id']: m for m in review['materials']}
    assert len(materials) == len(review['materials'])
    gaps = {g['id']: g for g in review['evaluation_families']}
    assert len(gaps) == len(review['evaluation_families'])
    actual = {t['name'] for t in read(directory / 'evaluation_failures.json')['failed_tests']}
    reviewed = {name for gap in gaps.values() for name in gap['failed_tests']}
    if actual != reviewed:
        errors.append({'kind': 'evaluation_coverage', 'missing': sorted(actual - reviewed),
                       'extra': sorted(reviewed - actual)})
    documents = {}
    checked = 0
    for owner, refs in [(m['id'], m['refs']) for m in materials.values()] + [
            ('process:' + str(i), row['refs']) for i, row in enumerate(review['agent_process']['explanations'])]:
        for ref in refs:
            text = reference_texts(ref, steps, documents)
            checked += 1
            if not ref['quote'] or not any(ref['quote'] in part for part in text):
                errors.append({'kind': 'quote_not_found', 'owner': owner, 'reference': ref})
    packages = defaultdict(lambda: defaultdict(set))
    for recipe in review['recipes']:
        assert recipe['gap'] in gaps
        assert recipe['qualification'] in {'direct', 'requires_transfer', 'requires_oracle_inference', 'incomplete'}
        for slot in recipe['slots']:
            assert slot['alternatives'], recipe['id']
            for alternative in slot['alternatives']:
                assert alternative and set(alternative) <= materials.keys(), recipe['id']
        forbidden = [frozenset(pair) for pair in recipe['forbidden_pairs']]
        frontier = {frozenset()}
        for slot in recipe['slots']:
            frontier = {left | frozenset(right) for left in frontier for right in slot['alternatives']
                        if not any(pair <= left | frozenset(right) for pair in forbidden)}
        for units in frontier:
            packages[recipe['gap']][units].add((recipe['id'], recipe['qualification']))
    rows = []
    reviewed_rows = []
    for gap, candidates in packages.items():
        kept = []
        for units in sorted(candidates, key=lambda u: (len(u), sorted(u))):
            # Only compare equivalent availability classes; an inferred oracle
            # cannot remove a larger directly reusable source package.
            qualifications = {q for _, q in candidates[units]}
            dominated = any(old < units and {q for _, q in candidates[old]} >= qualifications for old in kept)
            if not dominated:
                kept.append(units)
        for units in sorted(candidates, key=lambda u: (len(u), sorted(u))):
            kinds = Counter(materials[u]['kind'] for u in units)
            origins = Counter(materials[u]['origin'] for u in units)
            row = {'gap': gap, 'materials': sorted(units),
                   'recipes': sorted(candidates[units]), 'source_kinds': dict(kinds),
                   'origins': dict(origins)}
            reviewed_rows.append({**row, 'minimal_in_qualification': units in kept})
            if units in kept:
                rows.append(row)
    result = {'case': review['case_id'], 'checked_quotes': checked, 'errors': errors,
              'evaluation_families': len(gaps), 'materials': len(materials),
              'recipes': len(review['recipes']), 'reviewed_source_packages': len(reviewed_rows),
              'minimal_source_packages': len(rows),
              'packages_per_gap': dict(Counter(r['gap'] for r in rows))}
    (directory / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with gzip.open(directory / 'source_packages.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump(rows, stream, ensure_ascii=False, separators=(',', ':'))
    with gzip.open(directory / 'reviewed_source_packages.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump(reviewed_rows, stream, ensure_ascii=False, separators=(',', ':'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', required=True)
    args = parser.parse_args()
    rows = [verify_case(args.run / 'cases' / sid) for sid in args.cases]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    raise SystemExit(1 if any(row['errors'] for row in rows) else 0)


if __name__ == '__main__':
    main()
