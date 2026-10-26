import pathlib,json,sys
ROOT=pathlib.Path('/home/jhx/combination_coverage');R=ROOT/'results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01';C=R/'cases/S018';P=C/'prepared_original_namespace_control'
x=next(x for x in json.loads((R/'screening_order.json').read_text())['trials'] if x['screen_id']=='S018');q=json.loads((C/'checkpoint_validation/qualification.json').read_text());assert q['passed'];task=pathlib.Path(x['task_directory'])
sys.path.insert(0,str(ROOT/'src'));from context_recovery_pilot1_runtime import patch_paths,validate_plan
paths=sorted(set(patch_paths((task/'solution/solution.patch').read_text()))|set(patch_paths((pathlib.Path(x['input_directory'])/'model.patch').read_text())))
production=[p for p in paths if not any(z in p.split('/') for z in ['tests','test','testdata','fixtures','docs'])]
base={'checkpoint':q['checkpoint'],'checkpoint_validation':str(C/'checkpoint_validation/qualification.json'),'base_commit':x['base_commit'],'task_directory':str(task),'input_directory':x['input_directory'],'timeout':300,'build_commands':[],'files':[],'env':{},'workdir':'/app','resources':{'cpus':2,'memory':'8g','pids_limit':1024},'production_paths':production}
plans=C/'execution_plans';plans.mkdir(exist_ok=True)
for mode in ['original','verifier']:
 for impl in ['delivered','reference']:
  p={**base,'implementation':impl,'mode':'agent' if mode=='original' else 'verifier','command':'python -m pytest tests/test_rrule.py::'+('RRuleTZInteropTest::testRRuleRepr' if mode=='original' else 'RRuleTest::testRruleReprReconstructable')+' -q'}
  if mode=='original':p['files']=[{'source':str(P/'original_test_rrule.py'),'destination':'/app/tests/test_rrule.py'}]
  validate_plan(p);(plans/(mode+'_'+impl+'.json')).write_text(json.dumps(p,indent=2)+'\n')
print('S018 four plans ready; no edited plan or modified file')
