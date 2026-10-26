from pathlib import Path
import json,hashlib,shutil,sys,shlex
ROOT=Path('/home/jhx/combination_coverage');R=ROOT/'results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01';xs={x['screen_id']:x for x in json.loads((R/'screening_order.json').read_text())['trials']}
sys.path.insert(0,str(ROOT/'src'))
from context_recovery_pilot1_runtime import patch_paths,validate_plan
commands={'S068':('python -m pytest /tmp/pilot1_agent_test.py -q -k test_cli_enable_disable_safe_import','python -m pytest tests/test_safe_bulk_import.py -q -k "test_cli_enable_safe_import or test_cli_disable_safe_import"'),'S071':('./node_modules/.bin/vitest run src/error-stack.test.ts -t "runs the processor once for the top-level error, not for causes"','./node_modules/.bin/vitest run src/error-stack.test.ts -t "registerErrorStackProcessor fires even when no errorStack option is set"'),'S074':('go test -count=1 -v -run "^TestCompiledFunctionCallClosureSharing$" .','go test -count=1 -v -run "^TestCompiledFunctionCall_CloneKeepsNestedCallableGraphsIsolated$" .'),'S082':('', './node_modules/.bin/mocha tests/bail_on_test_failure_tests.js --grep "^(ProcessTestRunner|TapProcessTestRunner) abort functionality abort method is idempotent"'),'S085':('pnpm vitest --run test/duration-shard.test.ts -t "isolateSlowThreshold isolates slow files across shards"','pnpm vitest --run test/shard-balance.test.ts -t "isolateSlowThreshold"')}
for sid in ['S068','S071','S074','S082','S085']:
 x=xs[sid];case=R/'cases'/sid;plans=case/'execution_plans';plans.mkdir(exist_ok=True);task=Path(x['task_directory']);q=json.loads((case/'checkpoint_validation/qualification.json').read_text());assert q['passed']
 production=sorted(set(patch_paths((task/'solution/solution.patch').read_text()))|set(patch_paths((Path(x['input_directory'])/'model.patch').read_text())))
 production=[p for p in production if not any(z in p.split('/') for z in ['tests','test','fixtures','docs']) and not p.endswith(('_test.go','.test.ts','.spec.ts','_tests.js')) and not p.lower().startswith('readme')]
 base={'checkpoint':q['checkpoint'],'checkpoint_validation':str(case/'checkpoint_validation/qualification.json'),'base_commit':x['base_commit'],'task_directory':str(task),'input_directory':x['input_directory'],'timeout':300,'build_timeout':600,'build_commands':[],'files':[],'env':{'PYTHONPATH':'/app'} if sid=='S068' else {},'workdir':'/app/test/config' if sid=='S085' else '/app','resources':{'cpus':2,'memory':'8g','pids_limit':1024},'production_paths':production}
 if sid=='S085':base.update(build_commands=['cd /app && pnpm --filter vitest run build'],requires_build=True)
 for c in sorted((R/'screening'/sid).glob('candidate_*')):
  manifest=json.loads((c/'frozen.json').read_text());prepared=case/('prepared_'+c.name);shutil.copytree(c,prepared,dirs_exist_ok=True)
  receipts=[]
  for f in c.rglob('*'):
   if f.is_file():
    f2=prepared/f.relative_to(c);h=hashlib.sha256(f.read_bytes()).hexdigest();assert h==hashlib.sha256(f2.read_bytes()).hexdigest();receipts.append({'source':str(f),'copy':str(f2),'sha256':h})
  (prepared/'copy_receipt.json').write_text(json.dumps(receipts,indent=2)+'\n')
  for variant in ['original','edited']:
   for impl in ['delivered','reference']:
    p={**base,'implementation':impl,'mode':'agent','command':commands[sid][0],'files':[],'build_commands':list(base['build_commands'])}
    if sid=='S068':p['files']=[{'source':str(prepared/(variant+'_test_safe_import.py')),'destination':'/tmp/pilot1_agent_test.py'}]
    elif sid in ['S071','S074']:
     ext='ts' if sid=='S071' else 'go';p['files']=[{'source':str(prepared/(variant+'.'+ext)),'destination':'/app/'+manifest['test_path']}]
    elif sid=='S085':
     p['files']=[{'source':str(prepared/(variant+'.ts')),'destination':'/app/'+manifest['test_path']}]
     for f in (prepared/'required-files').rglob('*'):
      if f.is_file():p['files'].append({'source':str(f),'destination':'/app/'+str(f.relative_to(prepared/'required-files'))})
    elif sid=='S082':
     target='tests/runners/'+('process' if c.name=='candidate_001' else 'tap_process')+'_test_runner_tests.js';p['command']=manifest['command'].removeprefix('cd /app && ')
     p['files']=[{'source':str(prepared/'original-tests.patch'),'destination':'/tmp/pilot1_original_tests.patch'}]
     p['build_commands']=['git -c safe.directory=/app show '+x['base_commit']+':'+target+' > '+target,'git -c safe.directory=/app apply --whitespace=nowarn /tmp/pilot1_original_tests.patch']
     if variant=='edited':
      p['files'].append({'source':str(prepared/'setup-only.diff'),'destination':'/tmp/pilot1_setup.diff'})
      p['build_commands'].append('patch -p0 < /tmp/pilot1_setup.diff')
    validate_plan(p);(plans/(c.name+'_'+variant+'_'+impl+'.json')).write_text(json.dumps(p,indent=2)+'\n')
 for impl in ['delivered','reference']:
  p={**base,'implementation':impl,'mode':'verifier','command':commands[sid][1]};validate_plan(p);(plans/('verifier_'+impl+'.json')).write_text(json.dumps(p,indent=2)+'\n')
 print(sid,'plans ready')
