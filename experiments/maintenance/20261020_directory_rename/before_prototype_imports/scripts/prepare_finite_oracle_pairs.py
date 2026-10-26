"""Freeze outcome-blind paired finite-family requests; never call a provider.

This structural sample measures representation amortization, not coverage of
all 17 combination gaps. Every chosen member is identical in both joint arms.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experimental.finite_oracle_questions import build_question, restore_evidence

CASES = ['N01','N02','N03','N04','N05','N06','N07','N08','N09','N10','P1','P2','P3','P4','P5','P6','P7']
FILES = ['scripts/prepare_finite_oracle_pairs.py','experimental/finite_oracle_questions.py',
         'experimental/finite_oracle_templates.py','experimental/singleton_oracle_slots.py',
         'experimental/assertion_operand_guard.py','relation_search/oracle.py',
         'relation_search/oracle_evidence.py','relation_search/instrument.py',
         'experimental/call_dependency_evidence.py','anchor_retrieval/syntax.py',
         'anchor_retrieval/graph.py','anchor_retrieval/index.py','relational_gap/provider.py']


def read(path):
    return json.loads(path.read_text())


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()


def provider_encoded(value):
    return (json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'))+'\n').encode()


def choose_family(catalogue,maximum_members=4):
    eligible=[]
    for family in catalogue['families']:
        if family['status']=='factorized' and any(
            any(a['editable'] for a in v['assertions']) for v in family['variants']):
            eligible.append(family)
    multiple=[f for f in eligible if len(f['variants'])>1]
    choices=multiple or eligible
    summary=dict(eligible_families=len(eligible),eligible_multi_member_families=len(multiple),
                 selection='sha_first_eligible_multi_member' if multiple else 'sha_first_eligible_singleton_fallback')
    if not choices:
        return None,[],{**summary,'selection':'no_eligible_family'}
    chosen=min(choices,key=lambda f:(sha_text(f['id']),f['id']))
    variants=sorted(chosen['variants'],key=lambda v:(sha_text(v['candidate_id']),v['candidate_id']))[:maximum_members]
    summary.update(family_id=chosen['id'],family_hash_order=sha_text(chosen['id']),
                   full_family_members=len(chosen['variants']),selected_members=len(variants),
                   member_hash_order=[dict(candidate_id=v['candidate_id'],sha256=sha_text(v['candidate_id'])) for v in variants])
    return chosen,variants,summary


def wire_preview(request):
    wire=dict(model='deepseek-v4-flash',temperature=0,max_tokens=16384,
              messages=[dict(role='system',content=request['system']),dict(role='user',content=request['prompt'])],
              response_format=dict(type='json_object'),stream=False,
              thinking=dict(type=request.get('thinking','disabled')))
    if 'reasoning_effort' in request:
        wire['reasoning_effort']=request['reasoning_effort']
    return wire


def verify_pair(template,expanded):
    if template['system']!=expanded['system']:
        raise ValueError('Paired system instructions differ')
    a,b=json.loads(template['prompt']),json.loads(expanded['prompt'])
    if a['representation']!='template' or b['representation']!='expanded':
        raise ValueError('Paired representations are mislabeled')
    skeleton=a.pop('test_source');full=b.pop('test_source')
    a.pop('representation');b.pop('representation')
    if canonical(a)!=canonical(b):
        raise ValueError('Paired common prompt fields differ')
    for key in ['offered','analysis_evidence','finite_members','family_id','candidate_source_hash','source_prepared']:
        if template[key]!=expanded[key]:
            raise ValueError('Paired local source records differ: '+key)
    expanded_map={row['candidate']:row['modified_test'] for row in full}
    restored=[]
    if len(expanded_map)!=len(full) or len(skeleton['variants'])!=len(full):
        raise ValueError('Member source inventory mismatch')
    for row in skeleton['variants']:
        if len(row['replacements'])!=len(skeleton['holes']):
            raise ValueError('Incomplete member input tuple')
        pieces=[]
        for segment,hole,replacement in zip(skeleton['segments'],skeleton['holes'],row['replacements']):
            if replacement['hole_id']!=hole['id']:
                raise ValueError('Wrong member hole identity')
            pieces.extend([segment,replacement['after']])
        pieces.append(skeleton['segments'][-1])
        program=''.join(pieces)
        if program!=expanded_map[row['candidate']]:
            raise ValueError('Template and expanded members differ')
        restored.append(dict(alias=row['candidate'],program_sha256=sha_text(program),utf8_bytes=len(program.encode())))
    for member in a['variants']:
        alias=member['candidate']
        if restore_evidence(member['dependency_evidence']['rendered'],a['shared_code'])!=template['analysis_evidence'][alias]['rendered']:
            raise ValueError('Shared code did not restore exact member evidence')
    wa,wb=wire_preview(template),wire_preview(expanded)
    wa.pop('messages');wb.pop('messages')
    if wa!=wb:
        raise ValueError('Paired model settings differ')
    return a,dict(common_payload_sha256=hashlib.sha256(canonical(a)).hexdigest(),
                  member_roundtrips=restored,all_common_fields_equal=True,
                  offered_and_analysis_equal=True,model_settings=wa)


def verify_census(census,inventory):
    protocol=read(census/'protocol.json')
    if protocol['cases']!=CASES or protocol['expected_candidates']!=4502:
        raise ValueError('This preregistered comparison requires the fixed 17-case/4502 cohort')
    for name,expected in protocol['code_sha256'].items():
        if digest(ROOT/name)!=expected or digest(census/'code_snapshot'/name)!=expected:
            raise ValueError('Sealed census code changed: '+name)
    for name,expected in read(census/'seal.json')['files_sha256'].items():
        if digest(census/name)!=expected:
            raise ValueError('Sealed census evidence changed: '+name)
    for case in CASES:
        for name,expected in protocol['input_sha256'][case].items():
            if digest(inventory/case/name)!=expected['sha256']:
                raise ValueError('Cohort input changed: '+case+'/'+name)
    return protocol


def prepare(inventory,census,output):
    output.mkdir(parents=True,exist_ok=False)
    census_protocol=verify_census(census,inventory)
    inputs={case:{name:digest(inventory/case/name) for name in ['corpus.json','frontend.json','source_pool.json','case.json','issue.md']} for case in CASES}
    code={name:digest(ROOT/name) for name in FILES}
    protocol=dict(version='finite-oracle-paired-inputs-v2',cases=CASES,expected_candidates=4502,
        inventory=str(inventory.resolve()),census=str(census.resolve()),census_protocol_sha256=digest(census/'protocol.json'),
        input_sha256=inputs,code_sha256=code,provider_calls=0,subject_executions=0,
        sample='Per case SHA256(stable family.id) first factorized eligible multi-member family; if none, first eligible singleton. Eligibility uses original editable assertion inventory only. Members SHA256(candidate.id) first four.',
        selection_frozen_before_provider=True,maximum_members_per_question=4,
        no_retry_or_silent_family_replacement=True,
        sample_purpose='Structural amortization comparison; not the all-trial target-detection queue.',
        change_from_initial_draft='Choose eligible multi-member families before singleton fallback; fixed on source structure before any model answers, execution outcomes or target labels.',
        arms=['template','expanded'],joint_requests_per_family_per_arm=1,
        intervention='Only representation and test_source fields differ in common prompt payload; all members, contracts, imports, assertions, source evidence, system and model settings identical.',
        historical_result='Original v3 16/17 remains frozen; these results cannot fill its missing witness.',
        forbidden_selection_inputs=['provider answers','runtime outcomes','oracle correctness','target labels or ranks','reference patch','hidden verifier'],
        model_settings=dict(model='deepseek-v4-flash',temperature=0,max_tokens=16384,
                            response_format=dict(type='json_object'),stream=False,thinking=dict(type='enabled')),
        interpretation='UTF-8 prompt/wire bytes are not tokens or semantic correctness. A model row is not an independently valid complete oracle.')
    write(output/'protocol.json',protocol)
    for name in FILES:
        dest=output/'code_snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
    records=[]
    for case in CASES:
        source=inventory/case
        catalogue=read(census/case/'catalogue.json')
        family,variants,selection=choose_family(catalogue)
        record=dict(case=case,selection=selection,status='no_eligible_family',provider_calls=0)
        if family is not None:
            case_record=read(source/'case.json')
            issue_path=source/'issue.md'
            issue_sha=digest(issue_path)
            declared=[a['sha256'] for a in case_record.get('artifacts',[]) if a['path']=='issue.md']
            if declared!=[issue_sha] or digest(Path(case_record['issue']))!=issue_sha:
                raise ValueError('Issue does not match sealed registry/source: '+case)
            by_id={c['id']:c for c in read(source/'source_pool.json')['candidates']}
            candidates=[by_id[v['candidate_id']] for v in variants]
            record.update(family_id=family['id'],member_ids=[c['id'] for c in candidates],
                          members=len(candidates),issue_source=str(issue_path.resolve()),issue_sha256=issue_sha)
            corpus,frontend=read(source/'corpus.json'),read(source/'frontend.json')
            try:
                requests={arm:build_question(corpus,frontend,candidates,issue_path.read_text(),representation=arm) for arm in ['template','expanded']}
                for request in requests.values():
                    request['source_prepared']=str(source.resolve())
                    request['paired_input_case']=case
                common,identity=verify_pair(requests['template'],requests['expanded'])
            except (ValueError,TypeError,KeyError,AttributeError,UnicodeError) as error:
                record.update(status='selected_family_not_offerable',error_type=type(error).__name__,reason=str(error))
            else:
                arms={}
                for arm,request in requests.items():
                    destination=output/case/arm
                    request_path=destination/'request.json';wire_path=destination/'wire_preview.json'
                    write(request_path,request);wire_path.write_bytes(provider_encoded(wire_preview(request)))
                    arms[arm]=dict(request=str(request_path.resolve()),request_sha256=digest(request_path),
                        wire_preview=str(wire_path.resolve()),wire_preview_sha256=digest(wire_path),
                        prompt_bytes=len(request['prompt'].encode()),system_bytes=len(request['system'].encode()),
                        wire_bytes=len(provider_encoded(wire_preview(request))))
                write(output/case/'common_payload.json',common)
                write(output/case/'identity_review.json',identity)
                record.update(status='offerable',arms=arms,identity=identity,
                              actual_member_exposure_per_arm=len(candidates))
        write(output/case/'record.json',record)
        records.append(record)
        print(json.dumps({k:record[k] for k in ['case','status','members'] if k in record}),flush=True)
    if any(digest(inventory/case/name)!=expected for case,rows in inputs.items() for name,expected in rows.items()):
        raise ValueError('Inputs changed during preparation; no ready seal')
    if any(digest(ROOT/name)!=expected for name,expected in code.items()):
        raise ValueError('Code changed during preparation; no ready seal')
    offered=[r for r in records if r['status']=='offerable']
    totals=dict(cases=len(records),offerable_pairs=len(offered),nonofferable_cases=len(records)-len(offered),
                multi_member_pairs=sum(r['members']>1 for r in offered),
                members_per_arm=sum(r['members'] for r in offered),maximum_provider_requests=2*len(offered),
                provider_calls=0,subject_executions=0,
                prompt_bytes_by_arm={arm:sum(r['arms'][arm]['prompt_bytes'] for r in offered) for arm in ['template','expanded']},
                wire_bytes_by_arm={arm:sum(r['arms'][arm]['wire_bytes'] for r in offered) for arm in ['template','expanded']})
    result=dict(status='ready' if len(offered)==len(CASES) else 'ready_with_nonofferable_cases',
                protocol_sha256=digest(output/'protocol.json'),records=records,totals=totals,
                model_calls=0,provider_calls=0)
    write(output/'ready.json',result)
    write(output/'seal.json',dict(files_sha256={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))
    return totals


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--census',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.inventory,args.census,args.output)))
