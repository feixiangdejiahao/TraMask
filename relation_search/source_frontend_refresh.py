"""Recompute static metadata from exactly the supplied frozen source bytes."""
from __future__ import annotations

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend

VERSION = 'same-source-frontend-refresh.v1'


def refresh(corpus, previous):
    sources = []
    for path, row in sorted(corpus['sources'].items()):
        if previous.get('sources', {}).get(path, {}).get('code') != row['code']:
            raise ValueError('frontend_source_mismatch:' + path)
        sources.append(Source(path, row['code'], row.get('language', corpus['language']),
                              row.get('origin', 'repository'), row.get('step'), row.get('written_path')))
    config = previous.get('module_resolution', {})
    result = extract_frontend(sources, test_ids=corpus['tests'],
        max_production_depth=3, max_production_units=256,
        module_aliases=config.get('aliases'), module_base_url=config.get('base_url'),
        go_modules=config.get('go_modules'))
    found = {row['id']: row for row in result['tests']}
    missing = sorted(set(corpus['tests']) - set(found))
    if missing:
        raise ValueError('source_tests_not_recovered:' + ','.join(missing))
    for identifier, row in corpus['tests'].items():
        before, after = row['span'], found[identifier]['span']
        if any(before[key] != after[key] for key in ('path', 'start_byte', 'end_byte')):
            raise ValueError('source_test_span_changed:' + identifier)
    return result
