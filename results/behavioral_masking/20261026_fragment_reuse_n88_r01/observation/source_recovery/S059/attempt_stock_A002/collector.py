import base64,concurrent.futures,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path('/home/jhx/combination_coverage');RUN=ROOT/'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
COHORT=json.loads((ROOT/'results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01/cases.json').read_text())['cases']
REQUESTS={
'S073':['vm_test.go','script_test.go','go.mod'],
'S076':['vm_test.go','go.mod'],
'S022':['builtin/builtin_test.go','builtin/builtin.go','expr_test.go','vm/vm_test.go','go.mod'],
'S023':['builtin/builtin_test.go','builtin/builtin.go','expr_test.go','vm/vm_test.go','go.mod'],
'S024':['runtime_logs/testout.txt'],
'S055':['v1/profiler/profiler_test.go','v1/rego/profile_test.go','v1/topdown/query_test.go','v1/topdown/eval_test.go','go.mod'],
'S057':['crates/oxvg_optimiser/src/jobs/collapse_groups.rs','crates/oxvg_optimiser/src/jobs/snapshots/oxvg_optimiser__jobs__collapse_groups__collapse_groups-9.snap','crates/oxvg_optimiser/src/jobs/snapshots/oxvg_optimiser__jobs__collapse_groups__collapse_groups-10.snap','crates/oxvg_optimiser/src/test_config.rs','Cargo.toml'],
'S059':['runtime_logs/alltests.log'],
'S088':['interp/interp_consistent_test.go','interp/interp_eval_test.go','interp/interp_file_test.go','example/fs/fs_test.go','go.mod']}
SHA=lambda b:hashlib.sha256(b).hexdigest()
def run(argv):
 p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=170);return {'argv':argv,'returncode':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace')}
PAYLOAD=r'''import base64,hashlib,json,pathlib,subprocess,sys
paths=json.loads(sys.argv[1]);root=pathlib.Path('/app')
def cmd(args):
 p=subprocess.run(args,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30);return {'argv':args,'returncode':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace')}
files=[]
for rel in paths:
 p=pathlib.Path('/tmp')/pathlib.Path(rel).name if rel.startswith('runtime_logs/') else root/rel
 if not p.is_file():files.append({'path':rel,'status':'missing'});continue
 b=p.read_bytes();files.append({'path':rel,'status':'present','bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'base64':base64.b64encode(b).decode()})
print(json.dumps({'files':files,'head':cmd(['git','rev-parse','HEAD']),'status':cmd(['git','status','--short','--']+paths),'base_diff':cmd(['git','diff',sys.argv[2],'--']+paths),'no_tests_executed':True}))'''
def collect(s):
 c=next(x for x in COHORT if x['screen_id']==s);pointer=json.loads((RUN/f'cases/{s}/checkpoint.json').read_text());d=RUN/f'observation/source_recovery/{s}/attempt_stock_A002'
 if d.exists():raise RuntimeError('Refusing overwrite '+str(d))
 d.mkdir(parents=True);(d/'collector.py').write_text(Path(__file__).read_text());recs={}
 for variant,img in [('original',c['image']),('checkpoint',pointer['image_id'])]:
  vd=d/variant;vd.mkdir();identity=run(['docker','image','inspect','--format','{{.Id}}',img]);(vd/'image_identity.json').write_text(json.dumps(identity,indent=2)+'\n')
  if identity['returncode']!=0:raise RuntimeError('Missing Docker identity '+img+' '+identity['stderr'])
  argv=['docker','run','--rm','--read-only','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','128','--memory','2g','--entrypoint','python3',img,'-c',PAYLOAD,json.dumps(REQUESTS[s]),c['base_commit']]
  result=run(argv);(vd/'invocation.json').write_text(json.dumps({'argv':argv,'no_tests_executed':True},indent=2)+'\n');(vd/'stdout.json').write_text(result['stdout']);(vd/'stderr.txt').write_text(result['stderr'])
  if result['returncode']:raise RuntimeError(result['stderr'])
  r=json.loads(result['stdout']);r['image_id']=identity['stdout'].strip()
  for f in r['files']:
   if f['status']=='present':
    data=base64.b64decode(f.pop('base64'));assert SHA(data)==f['sha256'];p=vd/'files'/f['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);f['recovered_path']=str(p)
  (vd/'record.json').write_text(json.dumps(r,indent=2)+'\n');recs[variant]=r
 report={'schema_version':'stock-source-neutral-recovery.v1','case_id':s,'reviewer':'A collector; source receipts only','original_image_tag':c['image'],'base_commit':c['base_commit'],'checkpoint_image_id':pointer['image_id'],'raw_model_patch':pointer['raw_inputs']['model.patch'],'requested_paths':REQUESTS[s],'no_new_test_or_candidate_execution':True,'versions':{k:{'image_id':v['image_id'],'head':v['head']['stdout'].strip(),'record':str(d/k/'record.json'),'record_sha256':SHA((d/k/'record.json').read_bytes())} for k,v in recs.items()},'files':[],'historical_execution_not_inferred_from_recovery':True}
 for rel in REQUESTS[s]:
  a=next(f for f in recs['original']['files'] if f['path']==rel);b=next(f for f in recs['checkpoint']['files'] if f['path']==rel);report['files'].append({'path':rel,'original':a,'checkpoint':b,'equal_when_present':a.get('sha256')==b.get('sha256') if a['status']==b['status']=='present' else None})
 (d/'report.json').write_text(json.dumps(report,indent=2)+'\n');return {'case':s,'path':str(d/'report.json'),'equal_files':sum(x['equal_when_present'] is True for x in report['files']),'files':len(report['files'])}
for s in sys.argv[1:]:print(json.dumps(collect(s)),flush=True)
