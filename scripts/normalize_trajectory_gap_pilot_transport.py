"""Recover only lossless output-format errors; never change a test assertion."""
import ast
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_trajectory_gap_pilot import read,write,frozen,load_protocol,decode

def normalize_test(row,language,allowed):
    row=deepcopy(row);changes=[]
    if not isinstance(row,dict):return row,changes
    code=row.get('rewritten_test')
    if language=='python' and isinstance(code,str) and code!=code.rstrip():
        stripped=code.rstrip()
        try:
            tree=ast.parse(code)
            if len(tree.body)==1 and isinstance(tree.body[0],(ast.FunctionDef,ast.AsyncFunctionDef)) and ast.dump(tree)==ast.dump(ast.parse(stripped)):
                row['rewritten_test']=stripped;changes.append('Remove trailing whitespace after Python definition; AST unchanged.')
        except SyntaxError:pass
    added=row.get('imports')
    if isinstance(added,list):
        result=[]
        for value in added:
            if isinstance(value,dict) and set(value)=={'module','imported_name','name'} and any(all(value[k]==a[k] for k in value) for a in allowed):
                result.append(value['name']);changes.append('Convert exact source-verified named import object to required name string.')
            else:result.append(value)
        row['imports']=result
    return row,changes

def prepare(run):
    source=ROOT/'results/trajectory_gap_pilot_20261005'/run
    target=source.with_name(run+'_normalized')
    if target.exists():raise ValueError('immutable output already exists')
    p=deepcopy(load_protocol(source));rows=[];audit=[]
    for item in p['requests']:
        c=next(x for x in p['cases'] if x['case']==item['case']);corpus=read(c['inputs']['corpus.json']['path'])
        old=source/'cases'/item['case']/item['arm'];d=target/'cases'/item['case']/item['arm']
        manifest=read(old/'completion/manifest.json');decoded=dict(status='no_recovery',candidates=[],rejected=[])
        edits=[]
        if manifest.get('finish_reason')=='stop':
            raw=json.loads((old/'completion/completion.txt').read_text())
            if isinstance(raw,dict) and isinstance(raw.get('tests'),list):
                fixed=deepcopy(raw)
                for i,row in enumerate(raw['tests']):
                    fixed['tests'][i],ch=normalize_test(row,corpus['language'],c['permitted_imports'])
                    if ch:edits.append(dict(rank=i+1,changes=ch))
                converted=decode(corpus,c,json.dumps(fixed),'stop')
                accepted_orders={tuple(x['order']) for x in read(old/'decoded.json')['candidates']}
                decoded=dict(converted,candidates=[x for x in converted['candidates'] if tuple(x['order']) not in accepted_orders])
                write(d/'normalized_response.json',fixed)
        write(d/'decoded.json',decoded)
        for i,candidate in enumerate(decoded['candidates'],1):write(d/f'candidate_{i:02d}/program.json',candidate)
        r=dict(case=item['case'],arm=item['arm'],status=decoded['status'],candidates=len(decoded['candidates']),rejected=decoded['rejected'],decoded=frozen(d/'decoded.json'),manifest=frozen(old/'completion/manifest.json'),provider_calls=0,tokens=0,finish_reason=manifest.get('finish_reason'))
        rows.append(r);audit.append(dict(case=item['case'],arm=item['arm'],original_decoded=frozen(old/'decoded.json'),original_response=frozen(old/'completion/completion.txt') if (old/'completion/completion.txt').exists() else None,transformations=edits,recovered_original_ranks=[x['order'][0] for x in decoded['candidates']]))
    p['algorithm_entrypoints'].append(frozen(__file__))
    p['transport_normalization']={'original_prepared':frozen(source/'prepared.json'),'original_generation':frozen(source/'generation_summary.json'),'scope':'Apply same two syntax/schema-only rules to every complete response in both pilot rounds. Execute only newly recovered candidates; preserve original strict scores.','model_calls':0,'manual_assertion_changes':False,'audit':audit}
    p['created_utc']=datetime.now(timezone.utc).isoformat()
    write(target/'prepared.json',p);write(target/'seal.json',frozen(target/'prepared.json'))
    s=dict(stage='deterministic_transport_recovery',results=rows,provider_calls=0,measured_tokens=0,usage_missing=0,candidates=sum(x['candidates'] for x in rows),native_executions=0)
    write(target/'generation_summary.json',s);write(target/'generation_summary_seal.json',frozen(target/'generation_summary.json'))
    return dict(run=run,prepared=frozen(target/'prepared.json'),recovered=s['candidates'])
if __name__=='__main__':
    print(json.dumps(prepare(sys.argv[1])))
