from pathlib import Path
import json,re,hashlib
R=Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01');cases=['S068','S071','S074','S082','S085']

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def cell(f):
 a=json.loads(f.read_text());x=a.get('execution',{});out=re.sub(r'\x1b\[[0-9;]*m','',x.get('stdout','')+'\n'+x.get('stderr',''));n=f.parent.name
 counts={};v='UNRESOLVED'
 if a.get('target_executed') is not True:v='PREPARATION_ERROR'
 elif 'no tests to run' in out:v='NO_TESTS';counts={'passed':0,'failed':0,'executed':0}
 elif 'error during collection' in out:v='COLLECTION_ERROR';counts={'passed':0,'failed':0,'executed':0,'collection_errors':1}
 else:
  # Test-runner totals checked manually against each raw log; exit0 alone is never used as pass.
  if 'go test' in x.get('command',''):
   passed=len(re.findall(r'^--- PASS:',out,re.M));failed=len(re.findall(r'^--- FAIL:',out,re.M))
  elif 'vitest' in x.get('command',''):
   lines=[s for s in out.splitlines() if re.match(r'^\s*Tests\s+',s)];line=lines[-1] if lines else ''
   passed=int(re.search(r'(\d+) passed',line).group(1)) if re.search(r'(\d+) passed',line) else 0
   failed=int(re.search(r'(\d+) failed',line).group(1)) if re.search(r'(\d+) failed',line) else 0
  elif 'mocha' in x.get('command',''):
   passed=int(re.findall(r'(\d+) passing',out)[-1]) if re.findall(r'(\d+) passing',out) else 0
   failed=int(re.findall(r'(\d+) failing',out)[-1]) if re.findall(r'(\d+) failing',out) else 0
  else:
   passed=int(re.findall(r'(\d+) passed',out)[-1]) if re.findall(r'(\d+) passed',out) else 0
   failed=int(re.findall(r'(\d+) failed',out)[-1]) if re.findall(r'(\d+) failed',out) else 0
  counts={'passed':passed,'failed':failed,'executed':passed+failed}
  if failed:v='FAIL'
  elif passed and x.get('returncode')==0:v='PASS'
  else:v='UNRESOLVED'
 snapshots=a.get('production_snapshots',{});stable=None
 if snapshots.get('before_build') and snapshots.get('final'):
  stable=json.loads(snapshots['before_build']['stdout'])==json.loads(snapshots['final']['stdout'])
 return {'attempt':n,'verdict':v,'actual_test_counts':counts,'returncode':x.get('returncode'),'runner_status':a['status'],'command':x.get('command'),'command_sha256':x.get('command_sha256'),'result':str(f),'result_sha256':digest(f),'raw_stdout':x.get('raw_stdout'),'raw_stderr':x.get('raw_stderr'),'frozen_plan':str(f.parent/'plan.json'),'input_receipts':str(f.parent/'input_receipts.json'),'checkpoint_binding':str(f.parent/'checkpoint_validation_binding.json'),'production_source_unchanged_during_execution':stable,'production_snapshot_scope':a.get('production_diff_scope')}

notes={
'S068':{'candidate_001':'Full original source R collection failed because unrelated ImportInvariantError import is absent in R. Keep attempt; do not label behavior fail or change original assertions. candidate002 is separately frozen projection of exact original independent CLI test+fixture.','candidate_002':'Both original CLI commands and exit0 assertions unchanged. Remove only fixture precreation of path/database. Edited P first enable-safe-import returns exit2; R succeeds both commands.'},
'S071':{'candidate_001':'Original P passes but R runs actual selected test and yields calls2 expected1, twice. Candidate cannot satisfy baseline. Modified runs gated off; no deletion of cause, no weakening count assertion. Other original processor tests reviewed: after-all-steps has sanitization message/stack oracles; frames container hook requires stackFrames; registry/nonmatching tests do not provide matching hook-success target. No alternate legal candidate identified.'},
'S074':{'candidate_001':'Same original source script, Go inc/get calls and expected3 retained. Added c=c.Clone immediately before function extraction. P clone splits shared captured cell; get returns2 afterinc; R returns3. Known T13.'},
'S082':{'candidate_001':'Original R selected Process test runs and killCount2 violates original1 twice. No assertion removed; edited runs gated off for this candidate.','candidate_002':'Exact original Tap abort test retains both abort calls, killCount1, finishedtrue, reporter.total0, and done/catch. Remove injected onFinish noop only. P throws TypeError; R completes original assertions. Base test restored then exact model-added test patch applied identically on P/R.'},
'S085':{'candidate_001':'Same4 original fixture test programs, duration history400/300/200/100, shards1/2+2/2, two original assignment assertions. Threshold150→350 in both configuration invocations is one semantic condition. P adds2.test.js to first reservedshard, R retains[1] and[2,3,4]. Configuration-vs-target-input legitimacy remains for independent review.'}}
valid={'S068':['candidate_002'],'S071':[],'S074':['candidate_001'],'S082':['candidate_002'],'S085':['candidate_001']}
for sid in cases:
 case=R/'cases'/sid;cells=[cell(f) for f in sorted((case/'executions').glob('*/result.json'))]
 # Exact specific test provenance is the official test.patch; no verifier test copied into an agent candidate.
 ver=[x for x in cells if x['attempt'].startswith('verifier') and x['verdict']!='NO_TESTS']
 original=[x for x in cells if '_original_' in x['attempt']]
 baseline={'schema':'confirmed-gaps-baseline.v1','screen_id':sid,'qualification':str(case/'checkpoint_validation/qualification.json'),'original_tests':original,'specific_official_verifier':ver,'archived_evidence':str(R/'screening'/sid/'evidence'),'baseline_review':'Manual command/output/assertion review, actual test counts shown; success not inferred merely from process rc.','invalid_attempts':[x for x in cells if x['verdict'] in ['NO_TESTS','COLLECTION_ERROR','PREPARATION_ERROR']],'notes':notes[sid]}
 (case/'baseline_observation.json').write_text(json.dumps(baseline,ensure_ascii=False,indent=2)+'\n')
 cand=[]
 for cid,note in notes[sid].items():
  own=[x for x in cells if x['attempt'].startswith(cid+'_')];matrix={}
  for variant in ['original','edited']:
   for impl in ['delivered','reference']:
    key=variant+'_'+impl;matrix[key]=[x for x in own if cid+'_'+key+'_repeat_' in x['attempt']]
  passed=cid in valid[sid]
  if passed:
   for key,rows in matrix.items():
    assert len(rows)==2,(sid,cid,key)
    expected='FAIL' if key=='edited_delivered' else 'PASS'
    assert all(x['verdict']==expected and x['actual_test_counts']['executed']==1 for x in rows),(sid,cid,key)
  cand.append({'candidate_id':cid,'freeze':str(case/('prepared_'+cid)/'frozen.json'),'matrix':matrix,'execution_matrix_satisfied':passed,'semantic_factor_count':1,'notes':note,'ablation':{'method':'Remove the sole semantic context condition; this is the original-test control, already executed twice on P/R.','global_minimality_claim':False} if passed else None,'missing_cells_reason':None if passed else 'Original reference baseline did not pass. Modified cells deliberately not run after this gate failure; no repaired outcome is claimed.'})
 summary={'schema':'confirmed-gaps-matrix.v1','screen_id':sid,'execution_stage_complete':True,'candidate_count':len(cand),'candidates':cand,'specific_official_verifier':ver,'all_attempts':cells,'known_case':'T13' if sid=='S074' else None,'outcome_pending_independent_review':'Single-factor Context Repair' if valid[sid] else 'Assertion Repair Required','successful_candidate_ids':valid[sid],'strict_behavioral_masking_confirmed':False,'mechanism_postcheck':str(case/'O4_mechanism_postcheck.json') if valid[sid] else None,'invalid_attempt_policy':'All collection, zero-test and baseline failures preserved; no original target assertion changed to qualify a candidate.','reviews':'Not read by executor; independent reviews and root adjudication pending.','DeepSeek_calls':0}
 assert all(x['production_source_unchanged_during_execution'] is True for x in cells),(sid,'production drift')
 (case/'matrix_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 print(sid,'attempts',len(cells),'validmatrices',valid[sid])
