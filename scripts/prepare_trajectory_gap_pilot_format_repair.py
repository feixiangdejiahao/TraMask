"""Freeze a uniform JSON-format transport repair; preserve the original pilot."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_trajectory_gap_pilot import load_protocol,read,write,frozen,core

def prepare():
    source=ROOT/'results/trajectory_gap_pilot_20261005/generation_v2'
    target=ROOT/'results/trajectory_gap_pilot_20261005/generation_format_repair'
    if target.exists(): raise ValueError('immutable output already exists')
    p=deepcopy(load_protocol(source)); old_summary=read(source/'generation_summary.json')
    for item in p['requests']:
        q=read(item['request']['path'])
        q['system']+='\nReturn valid JSON. Each imports item must be a name string, not an object.\n'
        q.pop('id');q.pop('query_sha256')
        q['id']=q['query_sha256']=core._identity(q)
        path=target/'cases'/item['case']/item['arm']/'request.json'
        write(path,q);item['request']=frozen(path)
        item['prompt_bytes']=len(q['system'].encode())+len(q['prompt'].encode())
    p['created_utc']=datetime.now(timezone.utc).isoformat()
    p['format_repair']={'prior_prepared':frozen(source/'prepared.json'),
        'prior_generation':frozen(source/'generation_summary.json'),
        'reason':'7 requests rejected by provider JSON-keyword validation; one P7 output used import objects instead of permitted strings.',
        'changes':['Append explicit JSON keyword and string-only imports reminder uniformly to all16 systems.'],
        'unchanged':['Full test/source payloads','Original trajectory steps','Model and inference settings','Decoder','Native transport','Evaluation target labels'],
        'prior_calls':old_summary['provider_calls'],
        'interpretation':'Separate complete paired run. Never merge per-case best outputs across runs; retain truncation and all other original failures.'}
    p['algorithm_entrypoints'].append(frozen(__file__))
    write(target/'prepared.json',p);write(target/'seal.json',frozen(target/'prepared.json'))
    note={'status':'frozen_before_dispatch','prepared':frozen(target/'prepared.json'),'changes':p['format_repair'],
          'primary_comparison':'Use this uniformly repaired run for paired comparison; archive first run separately.',
          'no_per_case_regeneration':True}
    write(ROOT/'research/trajectory_gap_pilot_format_repair_20261005.json',note)
    print(note['prepared'])
if __name__=='__main__':prepare()
