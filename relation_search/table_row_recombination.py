"""Construct one new table pairing while retaining the complete test kernel.

The original source-control test retains every original row. A generated test
has one recombined row. This is a new test hypothesis, not a proof that deleting
the other iterations preserves the original test's meaning or state.
"""
from __future__ import annotations

import hashlib

from anchor_retrieval.syntax import Source, child, walk
from relation_search import table_column_rotation as columns

VERSION = 'source-go-single-row-recombination.v1'
MAX_CANDIDATES = 16
POLICY = dict(
    version=VERSION,
    construction='From the first16 source-column hypotheses, project each changed recipient row into a one-row table. Keep all statements, helpers, assertions and table fields outside the table data unchanged.',
    ordering='Original source table order, shift, recipient row, column. Deduplicate identical complete programs. Keep first16.',
    source_scope=columns.POLICY['domain'],
    source_controls='The complete unmodified original test, including every original row.',
    new_test_scope='One recombined row and the complete existing test kernel. This changes the generated test data, not the original control.',
    novelty='No novelty claim for row projection or combinatorial input generation. Test whether a smaller semantic obligation avoids coupling validity and reasoning cost across unrelated pairings.',
    proof_obligations='Row-history effects, input-domain constraints, column coupling, setup and the complete retained oracle require fresh semantic review.',
    oracle_preservation_proved=False,
    limitations=['Only tables admitted by the existing bounded Go source binder.',
                 'Only the first16 source-column hypotheses are projected; this is not the full Cartesian product.',
                 'Exact source tuples already in the original table are skipped. Different literal spellings can still denote equal runtime values.',
                 'A computed expected value may still observe a stronger representation equivalence than the public contract guarantees.'],
    forbidden_inputs=['case identities', 'historical candidates', 'provider decisions', 'native outcomes', 'audit labels', 'hidden tests', 'reference implementations'],
)


def generate(corpus, frontend, issue='', *, limit=MAX_CANDIDATES):
    if type(limit) is not int or not 0 <= limit <= MAX_CANDIDATES:
        raise ValueError('limit must be an integer from0 through16')
    base = columns.generate(corpus, frontend, issue, limit=columns.MAX_CANDIDATES)
    candidates, sources = [], {}
    for original in base['candidates']:
        evidence = original['source_evidence']; extent = evidence['table']; path = extent['path']
        if path not in sources:
            sources[path] = Source(path, corpus['sources'][path]['code'], 'go', 'repository')
        source = sources[path]
        tables = [n for n in walk(source.root) if n.type == 'composite_literal'
                  and n.start_byte == extent['start_byte'] and n.end_byte == extent['end_byte']]
        if len(tables) != 1 or source.text(tables[0]) != extent['text']:
            raise ValueError('source table receipt differs')
        table = tables[0]; body = child(table, 'body')
        rows = [columns._unwrap(n) for n in columns._parts(body)]
        tuples = [tuple(source.text(columns._unwrap(n)) for n in columns._parts(row)) for row in rows]
        for recipient, row in enumerate(rows):
            changed = [e for e in original['edits']
                       if row.start_byte <= e['span']['start_byte'] < e['span']['end_byte'] <= row.end_byte]
            if not changed:
                continue
            if len(changed) != 1:
                raise ValueError('source column hypothesis changes multiple cells in a row')
            edit = changed[0]
            new_tuple = list(tuples[recipient]); new_tuple[evidence['column']] = edit['after']
            if tuple(new_tuple) in tuples:
                continue
            row_bytes = source.data[row.start_byte:row.end_byte]
            start, end = edit['span']['start_byte']-row.start_byte, edit['span']['end_byte']-row.start_byte
            if row_bytes[start:end] != edit['before'].encode():
                raise ValueError('changed cell receipt differs')
            row_bytes = row_bytes[:start]+edit['after'].encode()+row_bytes[end:]
            table_after = (source.data[table.start_byte:body.start_byte]+b'{'+row_bytes+b',}').decode()
            replacement = dict(span=columns._span(source, table), before=source.text(table),
                               after=table_after, role='input')
            key = 'rowpair_'+columns.digest([VERSION, original['base_test_id'], replacement])[:24]
            candidate = dict(id=key, base_test_id=original['base_test_id'],
                source_test_ids=original['source_test_ids'], imports=[], edits=[replacement],
                generator=VERSION, operator='project_one_recombined_source_row',
                kind='source_table_pairing_hypothesis', oracle_status='requires_fresh_complete_test_review',
                source_evidence=dict(table=extent, original_test=evidence['original_test'],
                    source_column_hypothesis_id=original['id'], source_column_order=original['order'],
                    recipient_row=recipient, donor_row=(recipient+evidence['shift']) % len(rows),
                    column=evidence['column'], original_row_count=len(rows), generated_row_count=1,
                    input_consumers=evidence['input_consumers'],
                    unchanged='Complete original test bytes outside the table literal.',
                    source_sha256=hashlib.sha256(source.data).hexdigest(),
                    oracle_preservation_proved=False, row_independence_proved=False),
                order=[*original['order'][:-2], evidence['shift'], recipient, evidence['column']])
            candidates.append(candidate)
    unique = {}
    for candidate in sorted(candidates, key=lambda c: c['order']):
        unique.setdefault(candidate['id'], candidate)
    values = list(unique.values())
    return dict(version=VERSION, status=base['status'], candidates=values[:limit],
                total_candidates=len(values), selected=min(limit, len(values)),
                source_column_candidates=len(base['candidates']),
                source_column_candidates_before_limit=base['total_candidates'], skipped=base['skipped'])
