"""Build and inspect offline evidence for the 30-task trajectory study.

This is a retrospective review aid. Seed steps come from prior case reviews.
It does not run subject code, call a provider, or measure automatic retrieval.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.read_deepswe_trajectory import observations, display_text

BASE = ROOT / 'experiments/relation_distinction/results/pilot30_20261007_v1'
OUT = ROOT / 'research/trajectory_program_search30_20261010'
SEEDS = {
 'T01':[44,49,55,69,97,107], 'T02':[69,76,81,103],
 'T03':[70,75,84,87,131], 'T04':[139,140,165,169,171],
 'T05':[32,34,58,59,63], 'T06':[80,100,144,187,236],
 'T07':[50,60,73,77], 'T08':[30,36,54,74,75],
 'T09':[89,114,164,215], 'T10':[25,38,74,78,82],
 'T11':[45,50,66,92,97,103], 'T12':[48,53,103,112],
 'T13':[67,81,85,101,104,106,110], 'T14':[43,69,92,96],
 'T15':[35,39,54,118], 'T16':[24,47,52,70,80],
 'T17':[54,72,84,99,107], 'T18':[28,29,37,42,72],
 'T19':[22,74,75], 'T20':[68,76,86,148,168,213],
 'T21':[40,95,96,104], 'T22':[104,120,121,158,211],
 'T23':[49,53,54,59,64,79], 'T24':[39,124,161,174,183],
 'T25':[25,32,43,53], 'T26':[64,82,83,96,99],
 'T27':[54,59,60,66,75], 'T28':[58,70,79,80,81,107,130,131],
 'T29':[76,94,96,97,146,149], 'T30':[47,51,55,100,119],
}

def read(p): return json.loads(Path(p).read_text())
def write(p, value):
 p.parent.mkdir(parents=True, exist_ok=True)
 p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
def commands(step):
 result=[]
 for call in step.get('tool_calls') or []:
  args=call.get('arguments',{})
  if isinstance(args,str):
   try: args=json.loads(args)
   except ValueError: pass
  result.append(display_text(args.get('command',str(args)) if isinstance(args,dict) else args))
 return result

def prepare():
 cases=read(BASE/'cases.json'); targets=read(BASE/'benchmark_reverse_v4/combined_targets.json')['targets']
 benchmark={t['case']:t for t in read(BASE/'benchmark_reverse_v4/review.json')['targets']}
 manifest=[]
 for case in cases:
  path=Path(case['trajectory']);traj=read(path)
  oldpath=ROOT/'research/deepswe_failure_manual_20261006/trials'/(case['trial']+'.json')
  prior=read(oldpath)
  seeds=set(SEEDS[case['id']]); ids={n for s in seeds for n in [s-1,s,s+1]}
  index=[];episodes=[]
  for st in traj['steps']:
   cmd=commands(st); obs=observations(st)
   index.append({'step':st['step_id'],'commands':[c.split('\n')[0][:240] for c in cmd],
    'reasoning_chars':len(st.get('reasoning_content') or ''),
    'reasoning_summary':display_text(st.get('reasoning_content') or '')[:280],
    'output_returncodes':[rc for rc,_ in obs], 'output_chars':sum(len(t) for _,t in obs)})
   if st['step_id'] in ids:
    episodes.append({'step':st['step_id'],'seed':st['step_id'] in seeds,
     'message':display_text(st.get('message') or ''),
     'reasoning':display_text(st.get('reasoning_content') or ''),
     'commands':cmd,'outputs':[{'returncode':rc,'text':display_text(t)} for rc,t in obs]})
  name=case['id'];write(OUT/'inputs'/name/'index.json',index);write(OUT/'inputs'/name/'episodes.json',episodes)
  write(OUT/'inputs'/name/'context.json',{'case':case,'historical_review':prior,
    'fixed_targets':[t for t in targets if t['case']==name],
    'benchmark_representative':{k:v for k,v in benchmark[name].items() if k!='evidence'}})
  manifest.append({'case':name,'trial':case['trial'],'trajectory':str(path.relative_to(ROOT)),
    'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'steps':len(index),
    'steps_with_reasoning':sum(i['reasoning_chars']>0 for i in index),
    'seed_steps':sorted(seeds),'saved_neighborhood_steps':[e['step'] for e in episodes],
    'historical_review':str(oldpath.relative_to(ROOT))})
 write(OUT/'manifest.json',{'scope':'All 30 original trajectories indexed; selected neighborhoods stored for retrospective static review.',
  'selection':'Seed steps selected from existing case reviews and known targets, not a blind automatic retrieval evaluation.',
  'external_model_calls':0,'subject_executions':0,'cases':manifest})
 print(json.dumps({'cases':len(manifest),'all_indexed_steps':sum(x['steps'] for x in manifest),
  'neighborhood_steps':sum(len(x['saved_neighborhood_steps']) for x in manifest),
  'steps_with_reasoning':sum(x['steps_with_reasoning'] for x in manifest)}))

def show(args):
 for case in args.cases:
  ctx=read(OUT/'inputs'/case/'context.json')
  print('\nCASE',case,ctx['case']['task'])
  if args.search:
   tr=read(ctx['case']['trajectory'])
   records=[{'step':st['step_id'],'reasoning':display_text(st.get('reasoning_content') or ''),
    'commands':commands(st),'outputs':[{'returncode':rc,'text':display_text(t)} for rc,t in observations(st)]} for st in tr['steps']]
  else:records=read(OUT/'inputs'/case/'episodes.json')
  for e in records:
   if args.steps and e['step'] not in args.steps:continue
   if not args.steps and not args.search and not e.get('seed'):continue
   if args.search and not re.search(args.search,e['reasoning']+'\n'+'\n'.join(e['commands']),re.I):continue
   print('STEP',e['step'])
   if args.search and not args.full:
    lines=(e['reasoning']+'\n'+'\n'.join(e['commands'])).splitlines()
    selected=set()
    for i,l in enumerate(lines):
     if re.search(args.search,l,re.I):selected.update(range(max(0,i-1),min(len(lines),i+2)))
    print('\n'.join(lines[i] for i in sorted(selected))[:args.limit])
   else:
    print('REASONING:',e['reasoning'][:args.limit])
    if args.commands:print('COMMANDS:',('\n'.join(e['commands']))[:args.limit])
   if args.outputs:
    for ob in e['outputs']:print('OUTPUT',ob['returncode'],ob['text'][-args.limit:])

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','show'])
 p.add_argument('cases',nargs='*');p.add_argument('--steps',type=int,nargs='+')
 p.add_argument('--commands',action='store_true');p.add_argument('--outputs',action='store_true')
 p.add_argument('--search');p.add_argument('--full',action='store_true');p.add_argument('--limit',type=int,default=1800)
 args=p.parse_args();prepare() if args.action=='prepare' else show(args)
