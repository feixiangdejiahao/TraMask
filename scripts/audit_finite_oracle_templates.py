"""Independent source-identity audit; no provider or subject execution.

For an uninstrumented source pool, reconstruct every program directly from
the original UTF-8 bytes and original edit intervals. Do not reuse the
generator's preview, edit filtering, assertion inventory, or grouping helper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prototypes.finite_oracle_templates import build_catalogue, expand


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)+'\n')


def extent(span):
    return span['path'], span['start_byte'], span['end_byte']


def verify_case(corpus, frontend, candidates, *, check_reordering=False):
    before = sha([corpus, frontend, candidates])
    if any(c.get('instrumentation', {}).get('status') == 'instrumented' for c in candidates):
        raise ValueError('This independent v1 audit requires uninstrumented source inputs')
    catalogue = build_catalogue(corpus, frontend, candidates)
    if before != sha([corpus, frontend, candidates]):
        raise ValueError('Generator modified input evidence')
    if check_reordering and canonical(catalogue) != canonical(build_catalogue(corpus, frontend, list(reversed(candidates)))):
        raise ValueError('Candidate input order changed stable catalogue contents')
    by_id = {c['id']: c for c in candidates}
    actual_ids = [v['candidate_id'] for f in catalogue['families'] for v in f['variants']]
    if len(by_id) != len(candidates) or Counter(actual_ids) != Counter(by_id.keys()):
        raise ValueError('Candidate membership is not one-to-one')
    unique_assertions = {}
    for observation in frontend.get('observations', []):
        if observation.get('kind') != 'assertion':
            continue
        span = observation.get('assertion_span', observation.get('span'))
        unique_assertions.setdefault(observation['test_id'], {}).setdefault(extent(span), observation)
    assertion_count = unchanged = readonly = unavailable = 0
    metadata_fields = {'id', 'base_test_id', 'edits', 'program_edits', 'imports', 'source_test_ids', 'source_contexts'}
    descriptor_ids = set()
    family_rows = []
    for family in catalogue['families']:
        base = family['base_test_id']
        owner = corpus['tests'][base]['span']
        source = corpus['sources'][owner['path']]['code'].encode()
        original = source[owner['start_byte']:owner['end_byte']]
        coordinates = None
        if family['owner_span'] != owner:
            raise ValueError('Source owner mismatch')
        if family['status'] == 'factorized':
            if family['source_sha256'] != sha(source) or family['original_test_sha256'] != sha(original):
                raise ValueError('Source hash mismatch')
            cursor = owner['start_byte']
            segments = []
            for hole in family['holes']:
                path, start, end = extent(hole['span'])
                if path != owner['path'] or not cursor <= start <= end <= owner['end_byte']:
                    raise ValueError('Invalid independently checked hole coordinates')
                if hole['before'].encode() != source[start:end]:
                    raise ValueError('Hole before bytes mismatch')
                segments.append(source[cursor:start].decode())
                cursor = end
            segments.append(source[cursor:owner['end_byte']].decode())
            if segments != family['segments']:
                raise ValueError('Skeleton changed original source outside holes')
            coordinates = sorted(extent(hole['span']) for hole in family['holes'])
        descriptor = {'base_test_id':base, 'owner_span':owner, 'source_sha256':sha(source),
                      'coordinates':coordinates, 'unknown_singleton':family['variants'][0]['candidate_id']
                      if family['status'] != 'factorized' else None}
        descriptor_sha = sha(descriptor)
        if descriptor_sha in descriptor_ids:
            raise ValueError('Identical family descriptor split without explanation')
        descriptor_ids.add(descriptor_sha)
        for variant in family['variants']:
            candidate = by_id[variant['candidate_id']]
            if candidate['base_test_id'] != base or variant['program_edits'] != candidate['edits']:
                raise ValueError('Variant source input identity mismatch')
            independent = original
            expected_error = False
            for edit in sorted(candidate['edits'], key=lambda e:e['span']['start_byte'], reverse=True):
                a = edit['span']['start_byte']-owner['start_byte']
                b = edit['span']['end_byte']-owner['start_byte']
                if not 0 <= a <= b <= len(original):
                    expected_error = True
                    break
                independent = independent[:a]+edit['after'].encode()+independent[b:]
            if expected_error:
                if variant['preview_sha256'] is not None:
                    raise ValueError('Unavailable original preview claimed available')
                unavailable += 1
            else:
                actual = expand(family, variant).encode()
                if actual != independent or sha(actual) != variant['preview_sha256'] or len(actual) != variant['preview_bytes']:
                    raise ValueError('Template expansion differs from independent raw byte edits')
            if family['status'] == 'factorized':
                current_coords = sorted(extent(e['span']) for e in candidate['edits'])
                if current_coords != coordinates:
                    raise ValueError('Family members have different original edit footprints')
            for name in ['imports', 'source_test_ids', 'source_contexts']:
                if variant[name] != candidate.get(name, []):
                    raise ValueError('Per-member premise metadata was lost: '+name)
            context = {k:v for k,v in candidate.items() if k not in metadata_fields}
            if variant['context'] != context:
                raise ValueError('Per-member contextual metadata mismatch')
            expected = unique_assertions.get(base, {})
            if Counter(extent(a['original_span']) for a in variant['assertions']) != Counter(expected.keys()):
                raise ValueError('Complete source assertion inventory was not preserved')
            for assertion in variant['assertions']:
                assertion_count += 1
                path, start, end = extent(assertion['original_span'])
                observation = expected[(path, start, end)]
                if assertion['span'] != assertion['original_span'] or assertion['code'].encode() != source[start:end]:
                    raise ValueError('Original assertion/source identity mismatch')
                if assertion['observed'] != observation.get('observed', {}).get('text', ''):
                    raise ValueError('Observed expression identity mismatch')
                readonly += not assertion['editable']
                intersects = any(e['span']['path'] == path and
                    ((e['span']['start_byte'] < end and start < e['span']['end_byte']) or
                     (e['span']['start_byte'] == e['span']['end_byte'] and start < e['span']['start_byte'] < end))
                    for e in candidate['edits'])
                current = assertion['modified_span']
                if current is not None:
                    if intersects or expected_error:
                        raise ValueError('Overlapped/unavailable assertion claimed unchanged')
                    delta = sum(len(e['after'].encode())-(e['span']['end_byte']-e['span']['start_byte'])
                                for e in candidate['edits'] if e['span']['path'] == path and e['span']['end_byte'] <= start)
                    if current != {'path':path,'start_byte':start+delta,'end_byte':end+delta}:
                        raise ValueError('Assertion relocation is not the original-byte edit displacement')
                    a, b = current['start_byte']-owner['start_byte'], current['end_byte']-owner['start_byte']
                    if independent[a:b] != assertion['code'].encode():
                        raise ValueError('Assertion relocation does not address exact emitted bytes')
                    unchanged += 1
        family_rows.append({'family_id':family['id'],'descriptor_sha256':descriptor_sha,
                            'status':family['status'],'members':len(family['variants']),
                            'member_ids':[v['candidate_id'] for v in family['variants']]})
    return {'status':'verified','input_candidates':len(candidates),'catalogue_sha256':sha(catalogue),
            'families':len(family_rows),'multi_member_families':sum(r['members']>1 for r in family_rows),
            'singleton_families':sum(r['members']==1 for r in family_rows),
            'unknown_families':sum(r['status']=='unknown' for r in family_rows),
            'assertion_instances':assertion_count,'exact_relocated_assertions':unchanged,
            'readonly_assertion_instances':readonly,'preview_unavailable':unavailable,
            'reordering_invariance_verified':check_reordering,
            'family_rows':family_rows}


def run(source, output, *, sealed_census=None, check_reordering=False):
    output.mkdir(parents=True, exist_ok=False)
    cases = sorted(p for p in source.iterdir() if (p/'source_pool.json').exists())
    census_protocol = None
    if sealed_census:
        census_protocol = read(sealed_census/'protocol.json')
        for name, expected in census_protocol['code_sha256'].items():
            if sha((ROOT/name).read_bytes()) != expected or sha((sealed_census/'code_snapshot'/name).read_bytes()) != expected:
                raise ValueError('Sealed generator/current code identity mismatch: '+name)
        for name, expected in read(sealed_census/'seal.json')['files_sha256'].items():
            if sha((sealed_census/name).read_bytes()) != expected:
                raise ValueError('Sealed census file changed: '+name)
        if [case.name for case in cases] != census_protocol['cases']:
            raise ValueError('Sealed census cases differ from independently audited input')
    write(output/'protocol.json', {'source':str(source.resolve()),'case_ids':[p.name for p in cases],
        'code_sha256':{str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in
                       [Path(__file__),ROOT/'prototypes/finite_oracle_templates.py']},
        'generator_under_test':'build_catalogue and expand only',
        'independent_checks':'raw UTF-8 edits, whole assertion frontend inventory, metadata, original/modified spans and source hashes',
        'sealed_census':str(sealed_census.resolve()) if sealed_census else None,
        'sealed_census_protocol_sha256':sha((sealed_census/'protocol.json').read_bytes()) if sealed_census else None,
        'check_reordering':check_reordering,
        'model_calls':0,'subject_executions':0,'target_labels_opened':False})
    summaries = {}
    for case in cases:
        inputs = {name:sha((case/name).read_bytes()) for name in ['corpus.json','frontend.json','source_pool.json']}
        result = verify_case(read(case/'corpus.json'),read(case/'frontend.json'),read(case/'source_pool.json')['candidates'],
                             check_reordering=check_reordering)
        if sealed_census:
            if result['catalogue_sha256'] != sha(read(sealed_census/case.name/'catalogue.json')):
                raise ValueError('Independent build differs from sealed catalogue: '+case.name)
            for name, expected in census_protocol['input_sha256'][case.name].items():
                if inputs[name] != expected['sha256']:
                    raise ValueError('Source inputs differ from sealed census: '+case.name+'/'+name)
        result['input_sha256'] = inputs
        write(output/case.name/'review.json',result)
        summaries[case.name] = {k:v for k,v in result.items() if k!='family_rows'}
        print(json.dumps({'case':case.name,**summaries[case.name]}),flush=True)
    write(output/'summary.json',summaries)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--sealed-census',type=Path)
    parser.add_argument('--check-reordering',action='store_true')
    args=parser.parse_args()
    run(args.source,args.output,sealed_census=args.sealed_census,check_reordering=args.check_reordering)
