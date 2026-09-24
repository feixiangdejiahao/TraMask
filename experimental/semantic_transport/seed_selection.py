"""Select executable-source parents in the frozen retrieval's existing order.

The full anchor ranking retains parents beyond the corpus builder's top-k rank
annotations. No new relevance signals are inferred here. Source completeness,
language and parser status determine whether a parent can consume a seed slot.
"""
from __future__ import annotations

from collections import Counter, defaultdict


def _parent_order(retrieval):
    anchors = {row['id']: row for row in retrieval.get('anchors', [])}
    seen, ordered = set(), []
    for anchor_rank, anchor_id in enumerate(retrieval.get('rankings', {}).get('full', []), 1):
        anchor = anchors.get(anchor_id)
        if anchor is None:
            raise ValueError('full_ranking_anchor_missing')
        parent_id = anchor['test_id']
        if parent_id in seen:
            continue
        seen.add(parent_id)
        ordered.append({'retrieval_test_id': parent_id, 'retrieval_parent_rank': len(ordered) + 1,
                        'retrieval_anchor_rank': anchor_rank, 'retrieval_anchor_id': anchor_id,
                        'path': anchor['path'], 'name': anchor['name'], 'line': anchor['test_line']})
    if not ordered:
        for row in sorted(retrieval.get('selected_tests', []), key=lambda row: row['rank']):
            parent_id = row.get('test_id')
            key = parent_id or (row['path'], row['name'], row['line'])
            if key in seen:
                continue
            seen.add(key)
            ordered.append({'retrieval_test_id': parent_id, 'retrieval_parent_rank': row['rank'],
                            'retrieval_anchor_rank': None, 'retrieval_anchor_id': row.get('anchor_id'),
                            'path': row['path'], 'name': row['name'], 'line': row['line']})
    return ordered


def select(corpus, retrieval=None, *, top_k=10):
    """Return a shallow generation view and an auditable seed-selection record.

    Only copied rank-bearing records change. Original source bytes, spans, IDs
    and the caller's corpus/retrieval objects remain untouched. Nonmaterializable
    source parents cannot become seeds or donors through a generator fallback.
    """
    if type(top_k) is not int or top_k < 1:
        raise ValueError('Seed budget must be a positive integer')
    tests, sources = corpus['tests'], corpus['sources']
    excluded_sources = {}
    for path, source in sources.items():
        if not source.get('complete_file', True):
            excluded_sources[path] = 'incomplete_source'
        elif source.get('language', corpus['language']) != corpus['language']:
            excluded_sources[path] = 'different_language'
        elif source.get('parse_error'):
            excluded_sources[path] = 'source_parse_error'
    eligible = {tid for tid, test in tests.items() if test['span']['path'] not in excluded_sources}
    by_location = defaultdict(list)
    for tid, test in tests.items():
        path = test['span']['path']
        origin = sources[path].get('retrieval_excerpt')
        if origin:
            key = origin['path'], origin['name'], origin['line']
        else:
            key = path, test['name'], test.get('definition_span', test['span'])['line']
        by_location[key].append(tid)

    order, provenance, skipped = [], {}, Counter()
    retrieval = retrieval or {}
    ranked_parents = _parent_order(retrieval)
    anchor_ranks = {aid: rank for rank, aid in enumerate(retrieval.get('rankings', {}).get('full', []), 1)}
    anchors_by_id = {anchor['id']: anchor for anchor in retrieval.get('anchors', [])}
    anchors_by_line = defaultdict(list)
    for anchor in retrieval.get('anchors', []):
        if anchor['id'] in anchor_ranks and 'line' in anchor:
            anchors_by_line[anchor['path'], anchor['name'], anchor['line']].append(anchor['id'])
    for parent in ranked_parents:
        tid = parent['retrieval_test_id']
        if tid not in tests:
            matches = by_location[parent['path'], parent['name'], parent['line']]
            tid = matches[0] if len(matches) == 1 else None
        if tid is None:
            skipped['parent_absent_from_corpus'] += 1
            continue
        if tid not in eligible:
            skipped[excluded_sources[tests[tid]['span']['path']]] += 1
            continue
        if tid in provenance:
            continue
        order.append(tid)
        provenance[tid] = dict(parent, ordering='frozen_retrieval')

    # Standalone miniature corpora and parents without retrieval anchors have a
    # deterministic fallback, after every matched frozen-ranking parent.
    for test in sorted(tests.values(), key=lambda row: (row.get('retrieval_rank') or float('inf'), row['id'])):
        tid = test['id']
        if tid not in eligible or tid in provenance:
            continue
        order.append(tid)
        provenance[tid] = {'retrieval_test_id': tid, 'retrieval_parent_rank': test.get('retrieval_rank'),
                           'retrieval_anchor_rank': None, 'retrieval_anchor_id': None,
                           'ordering': 'corpus_rank_then_test_id'}
    ranks = {tid: rank for rank, tid in enumerate(order, 1)}

    def ranked(record):
        tid = record.get('test_id', record.get('id'))
        return dict(record, retrieval_rank=ranks[tid],
                    original_retrieval_rank=record.get('retrieval_rank'))

    def ranked_capsule(record):
        result = ranked(record)
        parent = tests[record['test_id']]
        span = record.get('assertion_span', {})
        ids = list(record.get('retrieval_anchor_ids', []))
        ids.extend(anchors_by_line[parent['span']['path'], parent['name'], span.get('line')])
        # Corpus anchor IDs historically use a line-only join. Two assertions
        # separated by a semicolon must not inherit one another's priority.
        exact = []
        for aid in set(ids):
            anchor = anchors_by_id.get(aid, {})
            if (aid in anchor_ranks and anchor.get('path') == parent['span']['path']
                    and anchor.get('name') == parent['name']
                    and anchor.get('test_line') == parent.get('definition_span', parent['span'])['line']
                    and anchor.get('line') == span.get('line')
                    and 'assertion' in anchor and anchor['assertion'] == record.get('assertion')):
                exact.append((anchor_ranks[aid], aid))
        # Identical assertions at the same source position have no unique
        # anchor identity in the frozen schema; retain source-order fallback.
        best = exact[0] if len(exact) == 1 else (None, None)
        return dict(result, retrieval_anchor_rank=best[0], best_retrieval_anchor_id=best[1])

    view = dict(corpus, tests={tid: dict(ranked(tests[tid]), retrieval_provenance=provenance[tid]) for tid in order},
                sources={path: source for path, source in sources.items() if path not in excluded_sources},
                capsules=[ranked_capsule(row) for row in corpus['capsules'] if row['test_id'] in eligible],
                donors=[ranked(row) for row in corpus['donors'] if row['test_id'] in eligible])
    report = {'policy': 'frozen_parent_order_then_complete_same_language_parseable_source',
              'top_k': top_k, 'retrieval_parent_count': len(ranked_parents),
              'eligible_parent_count': len(order), 'excluded_source_counts': dict(Counter(excluded_sources.values())),
              'skipped_retrieval_parents': dict(skipped),
              'selected': [dict(provenance[tid], test_id=tid, effective_rank=ranks[tid],
                                original_corpus_rank=tests[tid].get('retrieval_rank')) for tid in order[:top_k]]}
    return view, report
