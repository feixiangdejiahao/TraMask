from pathlib import Path
import json,hashlib,sys,re
ROOT=Path('/home/jhx/combination_coverage');R=ROOT/'results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01';C=R/'cases/S026';P=C/'prepared_aux_type_scope_001'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
protected=[]
for name in ['positive_tests.go','negative_tests.go']:
 rel='checkers/testdata/brokenDocLink/'+name;a=P/'original'/rel;b=P/'modified'/rel;assert a.read_bytes()==b.read_bytes()
 comments=re.findall(r'/\*!.*?\*/',a.read_text(),re.S)
 protected.append({'repository_path':rel,'original_sha256':sha(a),'modified_sha256':sha(b),'byte_unchanged':True,'expected_diagnostic_count':len(comments),'expected_diagnostic_comments':comments,'diagnostic_comments_sha256':hashlib.sha256('\n'.join(comments).encode()).hexdigest()})
save(C/'protected_primary_input_receipts.json',{'schema':'confirmed-gaps-protected-primary.v1','screen_id':'S026','candidate':'aux_type_scope_001','protected_files':protected,'scope_boundary':'File-specific lint input versus package-wide analyzed source boundary remains open to independent semantic adjudication; these hashes prove unchanged primary files, not a scientific boundary ruling.'})
x=next(x for x in json.loads((R/'screening_order.json').read_text())['trials'] if x['screen_id']=='S026');task=Path(x['task_directory']);q=json.loads((C/'checkpoint_validation/qualification.json').read_text());assert q['passed']
sys.path.insert(0,str(ROOT/'src'));from context_recovery_pilot1_runtime import patch_paths,validate_plan
paths=sorted(set(patch_paths((task/'solution/solution.patch').read_text()))|set(patch_paths((Path(x['input_directory'])/'model.patch').read_text())))
production=[p for p in paths if not any(z in p.split('/') for z in ['testdata','tests','test','fixtures','docs']) and not p.endswith('_test.go')]
base={'checkpoint':q['checkpoint'],'checkpoint_validation':str(C/'checkpoint_validation/qualification.json'),'base_commit':x['base_commit'],'task_directory':str(task),'input_directory':x['input_directory'],'timeout':300,'build_timeout':600,'build_commands':[],'files':[],'env':{'GOMAXPROCS':'2'},'workdir':'/app','resources':{'cpus':2,'memory':'8g','pids_limit':1024},'production_paths':production,'command':"go test ./checkers/ -run '^TestCheckers/brokenDocLink$' -count=1 -timeout 120s -v"}
plans=C/'execution_plans';plans.mkdir(exist_ok=True)
for variant in ['original','edited']:
 for impl in ['delivered','reference']:
  p={**base,'implementation':impl,'mode':'agent','files':[]}
  for f in sorted((P/('original' if variant=='original' else 'modified')).rglob('*.go')):p['files'].append({'source':str(f),'destination':'/app/'+str(f.relative_to(P/('original' if variant=='original' else 'modified')))})
  validate_plan(p);save(plans/(variant+'_'+impl+'.json'),p)
for impl in ['delivered','reference']:
 p={**base,'implementation':impl,'mode':'verifier'};validate_plan(p);save(plans/('verifier_'+impl+'.json'),p)
print('S026 plans prepared; protected primary files unchanged; diagnostic count',protected[0]['expected_diagnostic_count'])
