"""Present the same retrieved source declarations without dependence graphs.

This is a prompt-presentation ablation, not a retrieval or generation algorithm.
The original structured analysis evidence is retained unchanged in each request.
"""
from __future__ import annotations

import copy
import hashlib
import json

POLICY = 'same-source-declarations-presentation-v1'
CHANGED_FIELDS = ['dependency_evidence.rendered', 'dependency_evidence.rendered_bytes',
                  'dependency_evidence.status (derived from the original byte limit)']


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _key(row):
    span = row['span']
    return row['source_sha256'], span['path'], span['start_byte'], span['end_byte']


def render_declarations(evidence):
    """Deduplicate only byte-identical spans or proven source containment."""
    unique = {}
    for raw in evidence['declarations']:
        span, code = raw['span'], raw['code']
        if not 0 <= span['start_byte'] <= span['end_byte']:
            raise ValueError('Invalid declaration span')
        if len(code.encode()) != span['end_byte']-span['start_byte']:
            raise ValueError('Declaration code is not the complete UTF-8 source span')
        key = _key(raw)
        if key in unique and unique[key]['code'] != code:
            raise ValueError('Identical declaration source span has conflicting code')
        row = unique.setdefault(key, dict(span=copy.deepcopy(span), code=code,
            source_sha256=raw['source_sha256'], roles=[]))
        row['roles'].extend(role for role in raw['roles'] if role not in row['roles'])
    kept, coverage = [], []
    # Match the original renderer's declaration order exactly. Source hashes
    # distinguish coordinate spaces for deduplication, not presentation order.
    ordered = sorted(unique.values(), key=lambda row:(row['span']['path'],
                     row['span']['start_byte'], -row['span']['end_byte']))
    for row in ordered:
        span = row['span']
        owner = next((item for item in kept if item['source_sha256'] == row['source_sha256']
                      and item['span']['path'] == span['path']
                      and item['span']['start_byte'] <= span['start_byte']
                      and span['end_byte'] <= item['span']['end_byte']), None)
        provenance = dict(span=copy.deepcopy(span), roles=row['roles'])
        if owner is None:
            row['included_sources'] = []
            kept.append(row)
            owner = row
        else:
            start = span['start_byte']-owner['span']['start_byte']
            end = span['end_byte']-owner['span']['start_byte']
            if owner['code'].encode()[start:end] != row['code'].encode():
                raise ValueError('Contained declaration disagrees with its complete source owner')
            owner['included_sources'].append(provenance)
        coverage.append(dict(source_sha256=row['source_sha256'], span=copy.deepcopy(span),
            code_sha256=sha(row['code']), roles=row['roles'], represented_by=copy.deepcopy(owner['span'])))
    lines = []
    for row in kept:
        header = dict(span=row['span'], roles=row['roles'], sha256=row['source_sha256'])
        if row['included_sources']:
            header['included_sources'] = row['included_sources']
        lines.extend(['SOURCE '+json.dumps(header, sort_keys=True, ensure_ascii=False), row['code']])
    rendered = '\n'.join(lines)+'\n' if lines else 'No source declarations were retrieved for this candidate.\n'
    return rendered, dict(input_declarations=len(evidence['declarations']), unique_spans=len(unique),
                          emitted_declarations=len(kept), emitted_code_bytes=sum(len(row['code'].encode()) for row in kept),
                          coverage=coverage, no_code_truncation=True, original_graph_text_included=False)


def transform(request):
    clone = copy.deepcopy(request)
    payload = json.loads(clone['prompt'])
    audits = {}
    for candidate in payload['candidates']:
        alias = candidate['candidate']
        evidence = request['analysis_evidence'][alias]
        rendered, audit = render_declarations(evidence)
        old = candidate['dependency_evidence']
        if old['rendered'] != evidence['rendered']:
            raise ValueError('Prompt evidence differs from preserved local analysis evidence')
        budget = evidence.get('limits', {}).get('max_bytes')
        status = 'over_budget' if budget is not None and len(rendered.encode()) > budget else 'ready'
        candidate['dependency_evidence'] = {**old, 'rendered': rendered,
                                           'rendered_bytes':len(rendered.encode()), 'status':status}
        audits[alias] = {**audit, 'original_rendered_bytes':len(old['rendered'].encode()),
                        'rendered_bytes':len(rendered.encode()), 'status':status}
    clone['prompt'] = json.dumps(payload, ensure_ascii=False)
    clone['id'] = sha(clone['prompt'])
    clone['source_declarations_ablation'] = dict(policy=POLICY, treatment_request_id=request['id'],
                                                changed_prompt_fields=CHANGED_FIELDS)
    assert clone['analysis_evidence'] == request['analysis_evidence']
    return clone, dict(candidates=audits, original_prompt_bytes=len(request['prompt'].encode()),
                       prompt_bytes=len(clone['prompt'].encode()), changed_prompt_fields=CHANGED_FIELDS)


def verify_declaration_sources(request, corpus):
    """Check every declaration against an entire original or modified source."""
    from relation_search.instrument import _program_edits
    versions = {}
    for path, source in corpus['sources'].items():
        versions[(path, sha(source['code']))] = source['code'].encode()
    for offered in request['offered'].values():
        candidate = offered['candidate']
        owner = corpus['tests'][candidate['base_test_id']]['span']['path']
        original = corpus['sources'][owner]['code'].encode()
        data = original
        edits = sorted(_program_edits(candidate), key=lambda row:(row['span']['start_byte'], row['span']['end_byte']))
        previous = -1
        for edit in edits:
            span = edit['span']
            if span['path'] != owner or span['start_byte'] < previous:
                raise ValueError('Invalid source edit ownership or overlap')
            if original[span['start_byte']:span['end_byte']].decode() != edit['before']:
                raise ValueError('Input edit does not match original source')
            previous = span['end_byte']
        for edit in reversed(edits):
            span = edit['span']
            data = data[:span['start_byte']]+edit['after'].encode()+data[span['end_byte']:]
        versions[(owner, hashlib.sha256(data).hexdigest())] = data
    checked = []
    for alias, evidence in request['analysis_evidence'].items():
        for row in evidence['declarations']:
            span = row['span']
            data = versions.get((span['path'], row['source_sha256']))
            if data is None or data[span['start_byte']:span['end_byte']] != row['code'].encode():
                raise ValueError('Declaration is not identical to its frozen complete source')
            checked.append(dict(alias=alias, source_sha256=row['source_sha256'], span=span,
                                code_sha256=sha(row['code']), verified=True))
    return checked
