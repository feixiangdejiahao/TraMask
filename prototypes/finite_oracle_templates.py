"""Lossless source factorization of an existing, finite candidate catalogue.

A family shares only its original test and edited byte coordinates. Its variants
need not have equivalent behavior, premises, or expected outputs. No candidates
or replacement values are generated here, and no model answers are read.
"""
from __future__ import annotations

import copy
import hashlib
import json

from prototypes.singleton_oracle_slots import assertion_inventory
from relation_search.instrument import _program_edits
from relation_search.oracle import preview, program_candidate, text

VERSION = 'finite-oracle-templates-v2'


def _sha(value):
    data = value if isinstance(value, bytes) else value.encode() if isinstance(value, str) else _json(value).encode()
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _position(edit):
    span = edit['span']
    return span['path'], span['start_byte'], span['end_byte']


def _supported_edits(corpus, candidate, edits):
    owner = corpus['tests'][candidate['base_test_id']]['span']
    data = corpus['sources'][owner['path']]['code'].encode()
    ordered = sorted(edits, key=_position)
    previous = None
    for edit in ordered:
        path, start, end = _position(edit)
        if path != owner['path'] or not owner['start_byte'] <= start <= end <= owner['end_byte']:
            raise ValueError('edit_outside_source_test')
        if previous and (previous[2] > start or previous[1] == start):
            # Same-start edits depend on edit ordering, including duplicate
            # insertions. They cannot be represented by independent holes.
            raise ValueError('overlapping_or_ambiguous_edits')
        if data[start:end].decode() != edit['before']:
            raise ValueError('original_edit_before_mismatch')
        if not isinstance(edit['after'], str):
            raise ValueError('nontext_replacement')
        previous = (path, start, end)
    return owner, ordered


def _assertions(corpus, frontend, clean, code):
    """Keep every original observation, including read-only/overlapped checks."""
    rows = assertion_inventory(corpus, frontend, clean)
    owner = corpus['tests'][clean['base_test_id']]['span']
    data = code.encode() if code is not None else None
    for row in rows:
        span = row['span']
        row['original_span'] = copy.deepcopy(span)
        intersects = any(edit['span']['path'] == span['path'] and
            ((edit['span']['start_byte'] < span['end_byte'] and span['start_byte'] < edit['span']['end_byte'])
             or (edit['span']['start_byte'] == edit['span']['end_byte'] and
                 span['start_byte'] < edit['span']['start_byte'] < span['end_byte']))
            for edit in clean['edits'])
        if intersects or data is None:
            row['modified_span'] = None
            row['modified_location_status'] = 'program_edit_overlap' if intersects else 'preview_unavailable'
            continue
        shift = sum(len(edit['after'].encode()) - (edit['span']['end_byte'] - edit['span']['start_byte'])
            for edit in clean['edits'] if edit['span']['path'] == span['path'] and
            edit['span']['end_byte'] <= span['start_byte'])
        current = dict(path=span['path'], start_byte=span['start_byte']+shift, end_byte=span['end_byte']+shift)
        start, end = current['start_byte']-owner['start_byte'], current['end_byte']-owner['start_byte']
        if data[start:end] == row['code'].encode():
            row['modified_span'] = current
            row['modified_location_status'] = 'exact_unchanged_assertion'
        else:
            row['modified_span'] = None
            row['modified_location_status'] = 'not_exact_after_edits'
    return rows


def expand(family, variant):
    """Return exactly the existing candidate's source-only test preview.

    Unknown singleton families retain a mechanical preview if it exists. An
    unavailable preview raises explicitly; unknown never means silently drop.
    """
    if family['status'] == 'unknown':
        if variant.get('mechanical_preview') is None:
            raise ValueError(variant.get('preview_error', 'preview_unavailable'))
        return variant['mechanical_preview']
    replacements = variant['replacements']
    holes = family['holes']
    if len(replacements) != len(holes) or len(family['segments']) != len(holes)+1:
        raise ValueError('incomplete_template_variant')
    pieces = []
    for segment, hole, replacement in zip(family['segments'], holes, replacements):
        if replacement['hole_id'] != hole['id']:
            raise ValueError('hole_identity_mismatch')
        pieces.extend((segment, replacement['after']))
    pieces.append(family['segments'][-1])
    return ''.join(pieces)


def build_catalogue(corpus, frontend, candidates):
    """Factor every candidate by base test + original edit coordinate set.

    Kind, shape, profile and edit role do not split a family. Per-variant source
    controls, imports, contexts, other candidate metadata and full original
    assertion inventories are retained instead of asserting semantic equality.
    The catalogue has no budget or truncation parameter.
    """
    families, by_key, info = [], {}, {}
    for candidate in candidates:
        cid = candidate['id']
        if cid in info:
            raise ValueError('duplicate_candidate_id')
        clean = program_candidate(candidate)
        edits = _program_edits(candidate)
        try:
            code = preview(corpus, clean)
            preview_error = None
        except (ValueError, KeyError, TypeError, UnicodeError) as error:
            code, preview_error = None, str(error)
        try:
            owner, ordered = _supported_edits(corpus, candidate, edits)
            if preview_error is not None:
                raise ValueError(preview_error)
            footprint = [_position(edit) for edit in ordered]
            key = _json([corpus['language'], _sha(corpus['sources'][owner['path']]['code']),
                         candidate['base_test_id'], footprint])
            status, reason = 'factorized', None
        except (ValueError, KeyError, TypeError, UnicodeError) as error:
            owner = corpus.get('tests', {}).get(candidate.get('base_test_id'), {}).get('span')
            source_sha = (_sha(corpus['sources'][owner['path']]['code'])
                          if owner and owner['path'] in corpus.get('sources', {}) else None)
            ordered, key, status, reason = edits, _json(['unknown', corpus.get('language'),
                source_sha, cid, _sha(candidate)]), 'unknown', str(error)
        if key not in by_key:
            family = dict(id='F'+_sha(key), base_test_id=candidate['base_test_id'],
                          status=status, reason=reason, owner_span=copy.deepcopy(owner),
                          segments=[], holes=[], variants=[])
            if status == 'factorized':
                data = text(corpus, owner).encode()
                cursor = 0
                for index, edit in enumerate(ordered):
                    start = edit['span']['start_byte']-owner['start_byte']
                    end = edit['span']['end_byte']-owner['start_byte']
                    family['segments'].append(data[cursor:start].decode())
                    family['holes'].append(dict(id='H'+str(index),
                        span={name:edit['span'][name] for name in ('path','start_byte','end_byte')}, before=edit['before']))
                    cursor = end
                family['segments'].append(data[cursor:].decode())
                family['source_sha256'] = _sha(corpus['sources'][owner['path']]['code'])
                family['original_test_sha256'] = _sha(data)
            by_key[key] = family
            families.append(family)
        family = by_key[key]
        assertions = _assertions(corpus, frontend, clean, code) if owner is not None else []
        context_fields = {'id', 'base_test_id', 'edits', 'program_edits', 'imports', 'source_test_ids', 'source_contexts'}
        variant = dict(id='V'+_sha([family['id'], cid]), candidate_id=cid,
            replacements=[dict(hole_id='H'+str(index), after=edit['after'])
                      for index, edit in enumerate(ordered)] if status == 'factorized' else [],
            program_edits=copy.deepcopy(edits), imports=copy.deepcopy(candidate.get('imports', [])),
            source_test_ids=copy.deepcopy(candidate.get('source_test_ids', [])),
            source_contexts=copy.deepcopy(candidate.get('source_contexts', [])),
            context={key:copy.deepcopy(value) for key,value in candidate.items() if key not in context_fields},
            assertions=assertions, preview_sha256=_sha(code) if code is not None else None,
            preview_bytes=len(code.encode()) if code is not None else None)
        if status == 'unknown':
            variant.update(mechanical_preview=code, preview_error=preview_error)
        family['variants'].append(variant)
        if code is not None and expand(family, variant) != code:
            raise ValueError('source_roundtrip_mismatch')
        info[cid] = dict(family_id=family['id'], variant_index=len(family['variants'])-1,
                        status=status, reason=reason, preview_available=code is not None)
    families.sort(key=lambda family: family['id'])
    stable_info = {}
    for family in families:
        family['variants'].sort(key=lambda variant: variant['candidate_id'])
        for index, variant in enumerate(family['variants']):
            cid = variant['candidate_id']
            stable_info[cid] = {**info[cid], 'variant_index':index}
    info = {cid:stable_info[cid] for cid in sorted(stable_info)}
    return dict(version=VERSION, families=families, candidate_info=info,
                input_count=len(info), family_count=len(families))


def source_size_summary(catalogue):
    """UTF-8 JSON bytes, not token usage or semantic inference savings."""
    expanded, factorized = [], []
    for family in catalogue['families']:
        if family['status'] != 'factorized':
            continue
        expanded.extend(dict(candidate_id=variant['candidate_id'], modified_test=expand(family, variant))
                        for variant in family['variants'])
        factorized.append(dict(base_test_id=family['base_test_id'], segments=family['segments'], holes=family['holes'],
            variants=[dict(candidate_id=v['candidate_id'], replacements=v['replacements']) for v in family['variants']]))
    before, after = len(_json(expanded).encode()), len(_json(factorized).encode())
    return dict(expanded_source_json_bytes=before, factorized_source_json_bytes=after,
                source_bytes_saved=before-after, full_catalogue_json_bytes=len(_json(catalogue).encode()),
                interpretation='source representation only; unchanged per-variant premises/assertions excluded from both source-only sizes')
