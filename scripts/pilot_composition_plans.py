#!/usr/bin/env python3
"""Compare lexical and connection-guided composition on frozen public slices."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json
from eviweave.anchors import changed_lines,test_path
from eviweave.evidence import SourceGraph
from eviweave.issue_filter import rank_lexical
from eviweave.llm import complete,MODEL
from eviweave.planning import (interface_features,text_features,related_order,check_plan,
                              changed_declaration_names,select_validation_centers,focused_patch,SYSTEM,PLAN,GENERATE)
from verify_pre_slice_five_pilot import original_sources

FR=ROOT/'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
SLICES=ROOT/'results/behavioral_masking/20261103_joint_pipeline_alignment_n88_r03'
COHORT=['S006','S013','S030','S037','S042','S046','S059','S065','S066','S073','S078','S085','S086','S088']
ARMS=['lexical','connections']
CHAR_BUDGET=64000



def excerpt(text,limit=6500):
    if len(text)<=limit:return text
    half=limit//2
    return text[:half]+'\n[... excerpt; request context if needed ...]\n'+text[-half:]


def case_rows():
    return {c['screen_id']:c for c in read_json(FR/'cases.json')['cases']}


def load_records(sid):
    """Only public source versions and F/B outputs enter the model workset."""
    case=case_rows()[sid];directory=SLICES/'cases'/sid
    originals=original_sources(case);records=[];cache={}
    selection=read_json(directory/'selection.json')
    for source,filename in selection['sources'].items():
        doc=read_json(directory/filename);path,raw=originals[source]
        key=path,doc['sha256']
        if key not in cache:cache[key]=SourceGraph({'id':source,'path':path,'raw':raw})
        graph=cache[key]
        boundaries={}
        for group in doc['groups']:
            boundaries.setdefault(group['view'],group['group']['boundary'])
        for index,view in enumerate(doc['views']):
            file,=view['files']
            code='\n'.join(raw[a:b].decode() for a,b in file['ranges'])
            features=interface_features(graph,file['nodes'])
            extra=text_features(code)
            features['keys']=sorted(set(features['keys'])|set(extra['keys']))
            features['paths']=extra['paths']
            identity='V'+str(len(records)).zfill(5)
            records.append({'id':identity,'kind':'program','source':source,'path':path,
                            'sha256':doc['sha256'],'boundary':boundaries[index],
                            'view_file':str(directory/filename),'view':index,'ranges':file['ranges'],
                            'text':path+'\n'+code,'features':features})
    targets=read_json(directory/'targets.json')
    for record in targets['records']:
        source=record['source']
        # Full B remains eligible, including source/contracts outside D's views.
        # Its records reference existing material rather than a second copy here.
        features={k:[] for k in ('calls','fields','observations','names')}
        features.update(text_features(record['text']))
        records.append({'id':'M'+record['id'][1:],'kind':'material','source':source,
                        'text':record['text'],'features':features})
    return records,targets,originals


def public_case(sid):
    root=FR/'public_inputs'/sid
    return {'issue':(root/'issue.md').read_text(),'patch':(root/'patch.diff').read_text()}


def pack(records,order,*,programs=24,materials=12,budget=CHAR_BUDGET):
    by_id={r['id']:r for r in records};selected=[];counts=Counter();chars=0
    limits={'program':programs,'material':materials}
    for identity in order:
        record=by_id[identity];kind=record['kind']
        if counts[kind]>=limits[kind]:continue
        text=excerpt(record['text'])
        if chars+len(text)>budget:continue
        row={'id':identity,'kind':kind,'text':text}
        if kind=='program':row.update(path=record['path'],features=record['features'])
        selected.append(row);chars+=len(text);counts[kind]+=1
    return selected,{'ids':[r['id'] for r in selected],'characters':chars,'counts':dict(counts)}


def initial_order(records,public):
    query=public['issue']+'\n'+public['patch']
    lexical=rank_lexical(records,query);by_id={r['id']:r for r in records}
    centers=[];boundaries=set()
    for identity in lexical:
        row=by_id[identity]
        if row['kind']=='program' and row['source'].startswith('F:') and row['boundary'][0]=='test':
            key=row['path'],tuple(row['boundary'])
            if key not in boundaries:
                centers.append(identity);boundaries.add(key)
        if len(centers)==4:break
    return lexical,centers


def prepare(out):
    out.mkdir(parents=True)
    cases=case_rows()
    protocol={'cases':COHORT,'tasks':len({cases[s]['task'] for s in COHORT}),
              'languages':dict(Counter(cases[s]['language'] for s in COHORT)),
              'arms':ARMS,'model':MODEL,'temperature':0,'max_tokens':None,
              'input_policy':'issue, submitted patch, public archived source slices and B materials; no manual labels, verifier, reference or earlier generated tests',
              'initial_program_records':24,'initial_material_records':12,'characters':CHAR_BUDGET,
              'analysis_calls_per_arm':2,'generation_calls_per_arm':1,
              'expansion_records':10,'candidate_count_per_arm':1,
              'evaluation':'freeze generated tests, then assess jointly selected manual evidence and P/R execution',
              'selection':'mechanism-diverse development pilot: configuration interaction, representation, lifecycle, witness revision, event alignment, disputed contract, helper/fault context, cross-API contract, formatting, object sharing, observation timing, output JSON and new operation',
              'new_native_replays':0}
    write_json(out/'protocol.json',protocol)
    for sid in COHORT:
        directory=out/'cases'/sid;directory.mkdir(parents=True)
        started=time.monotonic();records,targets,_=load_records(sid);public=public_case(sid)
        lexical,centers=initial_order(records,public)
        connections,reasons=related_order(records,centers,public['issue']+'\n'+public['patch'])
        index=[{k:v for k,v in r.items() if k!='text'} for r in records]
        write_json(directory/'index.json',{'records':index,'centers':centers,'orders':{'lexical':lexical,'connections':connections},
                   'reasons':reasons,'metrics':{'programs':sum(r['kind']=='program' for r in records),
                   'materials':sum(r['kind']=='material' for r in records),'index_seconds':time.monotonic()-started},
                   'task':cases[sid]['task'],'language':cases[sid]['language']})
        for arm in ARMS:
            arm_dir=directory/arm;arm_dir.mkdir()
            order={'lexical':lexical,'connections':connections}[arm]
            rows,receipt=pack(records,order)
            write_json(arm_dir/'initial_packet.json',{'records':rows,'receipt':receipt})
        print('prepared',sid,len(records),'centers',centers,flush=True)


def prepare_centered(out,previous):
    """Keep the workset; prioritize submitted test edits as composition centers."""
    out.mkdir(parents=True)
    protocol=read_json(previous/'protocol.json')
    protocol.update(arms=['centered'],strategy='changed-test centers + existing-condition composition',
                    initial_program_records=8,initial_material_records=4,
                    characters=40000,parent_run=str(previous),
                    amendment_reason='initial pilot selected unrelated existing tests and invented new edges instead of composing available conditions')
    write_json(out/'protocol.json',protocol)
    for sid in COHORT:
        directory=out/'cases'/sid;directory.mkdir(parents=True)
        records,_,originals=load_records(sid);public=public_case(sid)
        lexical=rank_lexical(records,public['issue']+'\n'+public['patch'])
        changes=changed_lines(public['patch'])
        production={path for path in changes if not test_path(path)}
        programs=[r for r in records if r['kind']=='program' and
                  (r['boundary'][0]=='test' or
                   r['source'].startswith(('H:','I:')) and r['features']['observations']
                   and r['path'].removeprefix('/app/') not in production)]
        modified=changed_declaration_names(public['patch'],[value for source,value in originals.items() if source.startswith('F:')])
        centers=select_validation_centers(programs,lexical,changes,modified)
        order,reasons=related_order(records,centers,public['issue']+'\n'+public['patch'])
        index=read_json(previous/'cases'/sid/'index.json')
        index.update(centers=centers,orders={'centered':order},reasons=reasons,modified_names=sorted(modified))
        write_json(directory/'index.json',index)
        arm_dir=directory/'centered';arm_dir.mkdir()
        rows,receipt=pack(records,order,programs=8,materials=4,budget=40000)
        write_json(arm_dir/'initial_packet.json',{'records':rows,'receipt':receipt,'centers':centers})
        print('centered',sid,[(r['id'],r['path']) for r in records if r['id'] in centers],flush=True)


def request_packet(records,requests,seen,public,*,budget):
    by_id={r['id']:r for r in records};order=[]
    requested_public=[]
    for request in requests:
        query=request['query']
        if query in {'issue','patch'}:
            requested_public.append({'id':query,'kind':'public_input','text':public[query]})
            continue
        if query in by_id:order.append(query)
        order.extend(rank_lexical(records,query))
    order=list(dict.fromkeys(order))
    # New snippets precede already supplied records; explicitly requested IDs
    # still permit rereading their unabridged local context below.
    order=sorted(order,key=lambda identity:identity in seen)
    rows,receipt=pack(records,order,programs=6,materials=4,budget=budget)
    rows=requested_public+rows
    receipt.update(ids=[r['id'] for r in rows],characters=sum(len(r['text']) for r in rows))
    return rows,receipt


def generate(job,*,centered=False):
    sid,arm,out=job;directory=out/'cases'/sid/arm
    records,_,_=load_records(sid);public=public_case(sid)
    packet_info=read_json(directory/'initial_packet.json');packet=packet_info['records']
    by_id={r['id']:r for r in records}
    context={**public,'materials':packet}
    instruction=PLAN
    if centered:
        centers=[by_id[i] for i in packet_info['centers']]
        context.update(patch=focused_patch(public['patch'],centers),composition_centers=packet_info['centers'])
        instruction+='''\nChoose your base from composition_centers. Compare its tested
conditions and observations with the supplied history. Transfer a concrete
existing setup/input/check, restore a weakened check, or supply a missing
contract-based observation. Make explicit which existing statements/values are
combined. Prefer this to inventing an unrelated edge case from the broad issue.
Several coordinated edits are allowed. A demand for only one changed factor
would be incorrect. If the existing cases already check the combination,
choose a different complement or identify the insufficient oracle.\n'''
    started=time.monotonic()
    plan=complete(SYSTEM,instruction+'\nPUBLIC INPUT:\n'+json.dumps(context,ensure_ascii=False),directory/'calls/plan_001',root=ROOT)
    seen={r['id'] for r in packet};expanded=[]
    if plan['requests']:
        expanded,receipt=request_packet(records,plan['requests'],seen,public,budget=40000 if centered else CHAR_BUDGET)
        write_json(directory/'expansion_packet.json',{'records':expanded,'receipt':receipt,'requests':plan['requests']})
        context.update(previous_plan=plan,additional_materials=expanded)
        plan=complete(SYSTEM,instruction+'\nThis is the final planning round. Make one supported plan or report no_plan; additional requests will be recorded as unresolved.\nPUBLIC INPUT:\n'+json.dumps(context,ensure_ascii=False),directory/'calls/plan_002',root=ROOT)
        seen.update(r['id'] for r in expanded)
    write_json(directory/'plan.json',plan)
    if plan['decision']!='plan':
        write_json(directory/'outcome.json',{'status':plan['decision'],'seconds':time.monotonic()-started});return sid,arm,plan['decision']
    validation=check_plan(plan,[by_id[i] for i in seen if i not in public],public['issue'],public['patch'])
    write_json(directory/'plan_checks.json',validation)
    if validation['unknown_source_ids'] or not validation['order_acyclic']:
        write_json(directory/'outcome.json',{'status':'invalid_plan','seconds':time.monotonic()-started});return sid,arm,'invalid_plan'
    return compose(sid,arm,out,records=records,public=public,started=started)


def compose(sid,arm,out,*,records=None,public=None,started=None):
    """Materialize an already saved plan; also usable after a driver correction."""
    directory=out/'cases'/sid/arm
    if records is None:records,_,_=load_records(sid)
    if public is None:public=public_case(sid)
    if started is None:started=time.monotonic()
    plan=read_json(directory/'plan.json');by_id={r['id']:r for r in records}
    selected=list(dict.fromkeys([plan['base']]+plan['sources']+[e['source'] for e in plan['edits']]))
    supplied=[]
    for identity in selected:
        if identity in {'issue','patch'}:
            supplied.append({'id':identity,'kind':'public_input','text':public[identity]})
        else:
            supplied.append({k:by_id[identity][k] for k in ('id','kind','text')})
    # The original public commands help select the runner/build without importing
    # any earlier generated witness or evaluation command.
    command_records=[r for r in records if r['kind']=='material' and ':command' in r['source']]
    command_order=rank_lexical(command_records,'pytest go test cargo test npm pnpm yarn build test')
    command_map={r['id']:r for r in command_records}
    commands=[excerpt(command_map[i]['text'],2500) for i in command_order[:8]]
    generation_context={**public,'plan':plan,'selected_materials':supplied,'original_command_examples':commands}
    candidate=complete(SYSTEM,GENERATE+'\nINPUT:\n'+json.dumps(generation_context,ensure_ascii=False),directory/'calls/generate_001',root=ROOT)
    return save_candidate(sid,arm,out,candidate,selected,started)


def save_candidate(sid,arm,out,candidate,selected,started):
    directory=out/'cases'/sid/arm
    write_json(directory/'candidate.json',candidate)
    installed=[]
    for index,file in enumerate(candidate['files']):
        target=directory/'generated'/f'{index:03d}'
        target.parent.mkdir(exist_ok=True);target.write_text(file['content'])
        installed.append({'source':str(target),'destination':'/app/'+file['path'],
                          'sha256':hashlib.sha256(file['content'].encode()).hexdigest()})
    realization=[]
    files={f['path']:f['content'] for f in candidate['files']}
    for row in candidate['realization']:
        realization.append({**row,'anchor_found':row['path'] in files and row['anchor'] in files[row['path']]})
    write_json(directory/'generated_checks.json',{'realization':realization,
        'fact_expressions':[{'name':f['name'],'expression_found':f['path'] in files and f['expression'] in files[f['path']]} for f in candidate['facts']],
        'check_expressions':[{'id':c['id'],'expression_found':c['path'] in files and c['expression'] in files[c['path']]} for c in candidate['checks']]})
    write_json(directory/'files.json',installed)
    write_json(directory/'outcome.json',{'status':'generated','seconds':time.monotonic()-started,
                'selected_ids':selected})
    print('generated',sid,arm,len(selected),'sources',flush=True)
    return sid,arm,'generated'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['prepare','generate','compose','prepare_centered','generate_centered'])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cases',nargs='+',default=COHORT)
    parser.add_argument('--arms',nargs='+',default=ARMS)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--previous',type=Path)
    args=parser.parse_args();out=args.out.resolve()
    if args.operation=='prepare':prepare(out)
    elif args.operation=='prepare_centered':prepare_centered(out,args.previous.resolve())
    else:
        jobs=[(sid,arm,out) for sid in args.cases for arm in args.arms]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            if args.operation=='generate':operation=generate
            elif args.operation=='generate_centered':operation=lambda job:generate(job,centered=True)
            else:operation=lambda job:compose(*job)
            for row in pool.map(operation,jobs):print(row,flush=True)


if __name__=='__main__':main()
