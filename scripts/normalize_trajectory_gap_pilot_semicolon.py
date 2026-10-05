"""Additional lossless restoration of a missing test-registration semicolon."""
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from anchor_retrieval.syntax import Source
from scripts.run_trajectory_gap_pilot import read,write,frozen,load_protocol,decode,oracle
from scripts.normalize_trajectory_gap_pilot_transport import normalize_test

def named_shape(source,node):
    return (node.type,tuple(named_shape(source,n) for n in node.named_children)) if node.named_children else (node.type,source.text(node))

def restore(code,original):
    if not isinstance(code,str) or not original.endswith(';') or not code.rstrip().endswith(')'):return code,False
    fixed=code.rstrip()+';'
    a=Source('test.ts',code,'typescript');b=Source('test.ts',fixed,'typescript')
    if a.root.has_error or b.root.has_error or named_shape(a,a.root)!=named_shape(b,b.root):return code,False
    return fixed,True

def prepare(run):
    source=ROOT/'results/trajectory_gap_pilot_20261005'/run
    target=source.with_name(run+'_semicolon')
    if target.exists():raise ValueError('immutable output already exists')
    p=deepcopy(load_protocol(source));rows=[];audit=[]
    for item in p['requests']:
        c=next(x for x in p['cases'] if x['case']==item['case']);corpus=read(c['inputs']['corpus.json']['path'])
        old=source/'cases'/item['case']/item['arm'];d=target/'cases'/item['case']/item['arm']
        manifest=read(old/'completion/manifest.json');decoded=dict(status='no_recovery',candidates=[],rejected=[]);changes=[]
        if manifest.get('finish_reason')=='stop':
            raw=json.loads((old/'completion/completion.txt').read_text());fixed=deepcopy(raw)
            seeds={s['seed_alias']:s for s in c['seeds']}
            for i,row in enumerate(raw.get('tests',[])):
                row,_=normalize_test(row,corpus['language'],c['permitted_imports'])
                if isinstance(row,dict) and corpus['language']=='typescript' and row.get('seed_alias') in seeds:
                    seed=seeds[row['seed_alias']];original=oracle.text(corpus,seed['span'])
                    code,changed=restore(row.get('rewritten_test'),original)
                    if changed:row['rewritten_test']=code;changes.append(i+1)
                fixed['tests'][i]=row
            converted=decode(corpus,c,json.dumps(fixed),'stop')
            accepted={tuple(x['order']) for x in read(old/'decoded.json')['candidates']}
            previous=source.with_name(run+'_normalized')/'cases'/item['case']/item['arm']/'decoded.json'
            accepted.update(tuple(x['order']) for x in read(previous)['candidates'])
            decoded=dict(converted,candidates=[x for x in converted['candidates'] if tuple(x['order']) not in accepted])
            write(d/'normalized_response.json',fixed)
        write(d/'decoded.json',decoded)
        for i,candidate in enumerate(decoded['candidates'],1):write(d/f'candidate_{i:02d}/program.json',candidate)
        rows.append(dict(case=item['case'],arm=item['arm'],status=decoded['status'],candidates=len(decoded['candidates']),rejected=decoded['rejected'],decoded=frozen(d/'decoded.json'),manifest=frozen(old/'completion/manifest.json'),provider_calls=0,tokens=0,finish_reason=manifest.get('finish_reason')))
        audit.append(dict(case=item['case'],arm=item['arm'],semicolon_restored_at_original_ranks=changes,recovered_original_ranks=[x['order'][0] for x in decoded['candidates']]))
    p['algorithm_entrypoints'] += [frozen(__file__),frozen(ROOT/'scripts/normalize_trajectory_gap_pilot_transport.py')]
    p['semicolon_supplement']={'original_prepared':frozen(source/'prepared.json'),'previous_normalization':frozen(source.with_name(run+'_normalized')/'prepared.json'),'rule':'Restore only final registration semicolon when original seed has one and named AST tree is identical. Apply to all complete responses; repeat every existing structural check.','assertions_changed':False,'provider_calls':0,'audit':audit}
    write(target/'prepared.json',p);write(target/'seal.json',frozen(target/'prepared.json'))
    s=dict(stage='lossless_semicolon_recovery',results=rows,provider_calls=0,measured_tokens=0,usage_missing=0,candidates=sum(x['candidates'] for x in rows),native_executions=0)
    write(target/'generation_summary.json',s);write(target/'generation_summary_seal.json',frozen(target/'generation_summary.json'))
    print(json.dumps(dict(run=run,prepared=frozen(target/'prepared.json'),recovered=s['candidates'])))
if __name__=='__main__':prepare(sys.argv[1])
