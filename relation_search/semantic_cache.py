"""Replay recorded local oracle judgments with exact source/input identities.

No evaluation verdict is read. This is historical semantic replay, not a fresh
provider measurement. Failed/empty completions remain in the audit inventory.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .oracle import validate


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def program_key(corpus, candidate, issue, *, corpus_identity=None):
    base = candidate['base_test_id']
    source_path = corpus['tests'][base]['span']['path']
    edits = [{key: row[key] for key in ('span', 'before', 'after')}
             for row in candidate['edits'] if row.get('role') != 'semantic_expected']
    # Line annotations are not part of the edited byte range.
    for edit in edits:
        edit['span'] = {key: edit['span'][key] for key in ('path', 'start_byte', 'end_byte')}
    return digest(dict(corpus=corpus_identity or digest(corpus), source_file=corpus['sources'][source_path],
                       issue=issue, base_test_id=base, edits=edits,
                       imports=candidate.get('imports', [])))


def build_cache(request_paths, completion_dirs):
    index = {}
    for path in sorted(map(Path, request_paths)):
        request = read(path)
        if 'offered' in request and 'source_prepared' in request:
            index.setdefault(request['id'], []).append((path, request))
    records, entries, loaded = [], [], {}
    validator_sha = file_digest(Path(__file__).with_name('oracle.py'))
    for directory in sorted(map(Path, completion_dirs)):
        manifest = read(directory/'manifest.json')
        record = dict(completion=str(directory.resolve()), provider_status=manifest['status'],
                      manifest_sha256=file_digest(directory/'manifest.json'),
                      validator_sha256=validator_sha, request_id=manifest.get('request_id'),
                      cache_status='unmatched_request', revisions=0)
        records.append(record)
        if not (directory/'request.json').exists():
            continue
        sent = read(directory/'request.json')
        if file_digest(directory/'request.json') != manifest.get('request_sha256'):
            record['cache_status'] = 'changed_provider_request'
            continue
        messages = sent.get('messages', [])
        matches = [(path, request) for path, request in index.get(manifest.get('request_id'), [])
                   if messages == [{'role': 'system', 'content': request['system']},
                                   {'role': 'user', 'content': request['prompt']}]
                   and sent.get('thinking', {}).get('type', 'disabled') == request.get('thinking', 'disabled')]
        if not matches:
            continue
        path, request = matches[0]
        record.update(request=str(path.resolve()), request_sha256=file_digest(path),
                      sent_request_sha256=file_digest(directory/'request.json'),
                      cache_status='provider_not_complete')
        if manifest['status'] != 'complete' or not (directory/'completion.txt').exists():
            continue
        source = Path(request['source_prepared'])
        source_manifest = read(source/'prepare.json')
        if source_manifest.get('files_sha256', {}).get('corpus.json') != file_digest(source/'corpus.json'):
            record['cache_status'] = 'changed_source_corpus'
            continue
        if source_manifest.get('files_sha256', {}).get('issue.md') != file_digest(source/'issue.md'):
            record['cache_status'] = 'changed_source_issue'
            continue
        if str(source) not in loaded:
            corpus = read(source/'corpus.json')
            loaded[str(source)] = corpus, (source/'issue.md').read_text(), digest(corpus)
        corpus, issue, identity = loaded[str(source)]
        completion = (directory/'completion.txt').read_text()
        try:
            body = (directory/'response.body').read_bytes()
            raw = json.loads(body)
            if (hashlib.sha256(body).hexdigest() != manifest.get('response_sha256')
                    or raw['choices'][0]['message']['content'] != completion):
                raise ValueError('completion mismatch')
        except (OSError, ValueError, KeyError, IndexError):
            record['cache_status'] = 'changed_provider_response'
            continue
        record['completion_sha256'] = file_digest(directory/'completion.txt')
        record['source_corpus_sha256'] = file_digest(source/'corpus.json')
        record['source_issue_sha256'] = file_digest(source/'issue.md')
        try:
            result = validate(request, completion, corpus)
        except (ValueError, TypeError, KeyError, AttributeError):
            record['cache_status'] = 'invalid_completion'
            continue
        parents = {row['candidate']['id']: row['candidate'] for row in request['offered'].values()}
        record.update(cache_status='revalidated', revisions=len(result['revisions']),
                      decisions=result['decisions'])
        for revision in result['revisions']:
            parent = parents[revision['semantic_revision']['parent']]
            key = program_key(corpus, parent, issue, corpus_identity=identity)
            if program_key(corpus, revision, issue, corpus_identity=identity) != key:
                raise ValueError('Oracle revision changed program inputs')
            entries.append(dict(program_key=key, candidate=revision,
                                request=str(path.resolve()), completion=str(directory.resolve()),
                                request_sha256=record['request_sha256'],
                                completion_sha256=record['completion_sha256'],
                                validator_sha256=validator_sha,
                                source_corpus_sha256=record['source_corpus_sha256'],
                                source_issue_sha256=record['source_issue_sha256']))
    return dict(mode='historical_local_oracle_replay', records=records, entries=entries,
                evaluation_inputs=False, ordering_independent_of_cache=True)


def apply_cache(corpus, candidates, cache, issue):
    indexed = {}
    for row in cache['entries']:
        indexed.setdefault(row['program_key'], []).append(row)
    result, records, seen = copy.deepcopy(candidates), [], {row['id'] for row in candidates}
    identity = digest(corpus)
    for candidate in candidates:
        matches = indexed.get(program_key(corpus, candidate, issue, corpus_identity=identity), [])
        for entry in matches:
            revision = copy.deepcopy(entry['candidate'])
            if revision['id'] in seen:
                continue
            # The exact source and program key match. Retain the current seed's
            # control/provenance metadata, adding only recorded expected edits.
            expected = [row for row in revision['edits'] if row.get('role') == 'semantic_expected']
            merged = {**copy.deepcopy(candidate), 'id': revision['id'],
                      'edits': [*copy.deepcopy(candidate['edits']), *expected],
                      'semantic_revision': {**revision['semantic_revision'], 'parent': candidate['id']},
                      'static_parent_id': candidate['id'], 'execution_lane': 'relation_search_oracle',
                      'semantic_replay': {k: v for k, v in entry.items() if k != 'candidate'}}
            result.append(merged); seen.add(merged['id'])
            records.append(dict(parent=candidate['id'], revision=merged['id'],
                                program_key=entry['program_key'], request=entry['request'],
                                completion=entry['completion']))
    return dict(candidates=result, records=records,
                counts=dict(originals=len(candidates), replayed=len(records),
                            provider_calls=0, correctness_filtering=False))
