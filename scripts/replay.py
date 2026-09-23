"""Local Docker replay driver using the copied oracle_gap container runner.

command mode = base + submitted patch + explicit test command.
trajectory mode = fresh base + chronological original shell calls (no patch reapply).
"""
import argparse, json, os, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def docker(*args,**kw):return subprocess.run(['docker',*args],capture_output=True,text=True,**kw)
def main():
 p=argparse.ArgumentParser();p.add_argument('--case',required=True);p.add_argument('--command');p.add_argument('--trajectory',action='store_true');p.add_argument('--timeout',type=int,default=180);p.add_argument('--output');p.add_argument('--generated',action='store_true');args=p.parse_args()
 if bool(args.command)==args.trajectory:p.error('Choose --command or --trajectory')
 c=next(c for c in json.loads((ROOT/'data/cases.json').read_text()) if c['id']==args.case);base=ROOT/'data/cases'/c['id'];out=ROOT/(args.output or f'results/{c["id"]}/replay-{time.time_ns()}');out.mkdir(parents=True)
 request={'program':'candidate','command':args.command,'language':c['language'],'coverage':False,'timeout':args.timeout,'uid':os.getuid(),'gid':os.getgid()}
 (out/'request.json').write_text(json.dumps(request,indent=2))
 if not args.trajectory:
  cmd=['run','--rm','--interactive','--init','--network','none','--cpus','2','--memory','8g','--mount',f'type=bind,src={ROOT/"vendor/replay/container_replay.py"},dst=/replay.py,readonly','--mount',f'type=bind,src={out},dst=/replay-logs','--mount',f'type=bind,src={base/"model.patch"},dst=/candidate.patch,readonly']
  if args.generated:
   generated=ROOT/'results'/args.case/'generated'
   for path in generated.rglob('*'):
    if path.is_file():cmd+=['--mount',f'type=bind,src={path},dst=/app/{path.relative_to(generated)},readonly']
  cmd+=['--entrypoint','python3',c['image'],'/replay.py']
  r=docker(*cmd,input=json.dumps(request),timeout=args.timeout+120);(out/'transport.stdout').write_text(r.stdout);(out/'transport.stderr').write_text(r.stderr)
  print(out)
  if not (out/'result.json').exists():raise RuntimeError(r.stderr)
  result=json.loads((out/'result.json').read_text()); print(json.dumps(result));raise SystemExit(result.get('returncode',1) if 'error' not in result else 2)
 # Historical text is executed only inside a fresh isolated container, never on host.
 r=docker('run','-d','--init','--network','none','--cpus','2','--memory','8g','--entrypoint','sleep',c['image'],'infinity',check=True);name=r.stdout.strip(); records=[]
 try:
  tr=json.loads((base/'trajectory.json').read_text())
  for step in tr['steps']:
   for index,call in enumerate(step.get('tool_calls',[])):
    a=call['arguments'];a=json.loads(a) if isinstance(a,str) else a;command=a.get('command')
    if not command:continue
    label=f'{step["step_id"]}-{index}';(out/(label+'.sh')).write_text(command)
    try:
     r=docker('exec','--workdir','/app',name,'timeout','--kill-after=10',str(args.timeout),'bash','-lc',command,timeout=args.timeout+30)
     (out/(label+'.stdout')).write_text(r.stdout);(out/(label+'.stderr')).write_text(r.stderr);records.append({'step':step['step_id'],'call':index,'returncode':r.returncode})
    except subprocess.TimeoutExpired:records.append({'step':step['step_id'],'call':index,'timeout':True})
    (out/'progress.json').write_text(json.dumps(records,indent=2))
  # Compare expected patch file bytes to replay workspace without masking mismatches.
  import re,hashlib
  differences=[]
  for path in re.findall(r'^\+\+\+ b/(.+)$',(base/'model.patch').read_text(),re.M):
   expected=base/'repository'/path
   r=subprocess.run(['docker','exec',name,'cat','/app/'+path],capture_output=True)
   if not expected.exists() or r.returncode or r.stdout!=expected.read_bytes():differences.append(path)
  (out/'result.json').write_text(json.dumps({'mode':'chronological trajectory','calls':records,'candidate_file_mismatches':differences,'equivalent_candidate':not differences,'limitation':'checks added/modified patch paths only; not full workspace equivalence'},indent=2))
 finally:docker('rm','-f',name)
 print(out)
if __name__=='__main__':main()
