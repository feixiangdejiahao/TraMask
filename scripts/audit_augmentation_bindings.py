"""Offline, format-only diagnostic. Does not change formal inputs or scores."""
from copy import deepcopy
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from augmentation.trajectory_contrast import compute_contrasts
from augmentation.pipeline import write_json
from scripts.run_augmentation_trajectory_pilot import RUN,read,check

def main():
    check()
    rows=[]
    plans=list(sorted(RUN.glob('shared_plans/*/*/stage1/parsed.json')))
    assert len(plans)==16, 'wait_for_all_plans'
    for path in plans:
        case,repeat=path.parts[-4:-2]
        plan=read(path);facts=read(RUN/'inputs'/case/'facts.json')
        original=read(path.parent.parent/'computed_feedback.json')
        fixed=deepcopy(plan);changed={}
        for i,m in enumerate(fixed.get('models',[])):
            domains=m.get('domains',{})
            if not isinstance(domains,dict) or len(domains)!=1:continue
            factor=next(iter(domains))
            ids=[]
            for v in m.get('validation_rows',[]):
                q=v.get('bindings',{})
                if isinstance(q,dict) and 'call_id' in q and set(q)<= {'call_id','argument','path','get'}:
                    v['bindings']={factor:q};ids.append(v.get('id'))
            if ids:changed[i]=ids
        after=compute_contrasts(fixed,facts)
        for i,ids in changed.items():
            rows.append({'key':f'{case}/{repeat}/{i+1}','changed_rows':ids,
                         'change':'Wrap the unchanged flat query under the sole factor name. No value/path/expression/domain edits.',
                         'before':original[i],'after':after[i]})
    result={'purpose':'Post-hoc interface diagnosis only. Not a fifth arm; no external calls or changed formal scores.',
            'rule':'Only one-factor models with an unambiguous flat query; multi-factor ambiguity stays unchanged. No repairs to source semantics or value mappings.',
            'changed_models':len(rows),
            'models_with_complete_row_before':sum(r['before'].get('complete_literal_bound_rows',0)>0 for r in rows),
            'models_with_complete_row_after':sum(r['after'].get('complete_literal_bound_rows',0)>0 for r in rows),
            'rows':rows,
            'limit':'A syntactically successful projection can still bind the wrong semantic concept. Requires separate static review.'}
    write_json(RUN/'evaluation/binding_format_audit.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))

if __name__=='__main__':main()
