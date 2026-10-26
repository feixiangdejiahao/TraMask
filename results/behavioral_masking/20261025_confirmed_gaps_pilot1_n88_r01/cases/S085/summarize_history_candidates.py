import pathlib,json,re,hashlib,copy,collections
R=pathlib.Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01');C=R/'cases/S085'
namespace={};exec((R/'cases/S068/summarize_execution.py').read_text().split('\nnotes={',1)[0],namespace);cell=namespace['cell']
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(pathlib.Path(p).read_text())
def save(p,x):pathlib.Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def evidence(p,needles):
 p=pathlib.Path(p);out=[];step=None
 for n,line in enumerate(p.read_text().splitlines(),1):
  if line.startswith('STEP '):step=line
  if any(x in line for x in needles):out.append({'line':n,'step':step,'text':line[:420]})
 assert out
 return {'path':str(p),'sha256':sha(p),'anchors':out}
old_path=C/'matrix_summary_before_history_candidates.json'
if not old_path.exists():old_path.write_bytes((C/'matrix_summary.json').read_bytes())
old=read(old_path);new=copy.deepcopy(old)
original=old['candidates'][0]['matrix'];baseline={k:original[k] for k in ['original_delivered','original_reference']}
for key,rows in baseline.items():
 assert len(rows)==2 and all(x['verdict']=='PASS' and x['actual_test_counts']['executed']==1 for x in rows)
 for a in rows:
  assert sha(a['result'])==a['result_sha256']
  p=pathlib.Path(a['result']);plan=read(p.parent/'plan.json')
  for receipt in read(p.parent/'input_receipts.json'):
   for k in ['source','frozen']:assert sha(receipt[k]['path'])==receipt[k]['sha256']
  expected=read(C/'execution_plans'/('candidate_001_'+key+'.json'))
  assert plan==expected
cells=[];summaries=[]
for cid,fs in [('candidate_002',['F1','F2']),('candidate_003',['F1']),('candidate_004',['F2'])]:
 prep=C/('prepared_'+cid);freeze=read(prep/'frozen.json')
 for name,z in read(prep/'input_receipts.json').items():assert sha(prep/name)==z['sha256']
 assert sha(prep/'original.ts')==sha(C/'prepared_candidate_001/original.ts')
 matrix=copy.deepcopy(baseline)
 for impl in ['delivered','reference']:
  key='edited_'+impl;rows=[cell(C/'executions'/(cid+'_'+key+'_repeat_'+str(rep))/'result.json') for rep in [1,2]]
  expect='FAIL' if cid=='candidate_002' and impl=='delivered' else 'PASS'
  assert all(x['verdict']==expect and x['actual_test_counts']['executed']==1 for x in rows),(cid,key,rows)
  for x in rows:
   assert x['production_source_unchanged_during_execution'] is True
   result=read(x['result']);e=result['execution']
   for stream in ['stdout','stderr']:assert sha(e['raw_'+stream])==e[stream+'_sha256']
   for receipt in read(pathlib.Path(x['result']).parent/'input_receipts.json'):
    for k in ['source','frozen']:assert sha(receipt[k]['path'])==receipt[k]['sha256']
  matrix[key]=rows;cells.extend(rows)
 summaries.append({'candidate_id':cid,'freeze':str(prep/'frozen.json'),'factor_ids':fs,'semantic_factor_count':len(fs),'matrix':matrix,'execution_matrix_satisfied':cid=='candidate_002','original_baseline_reused_exact_receipts':True,'history_duration_vector':[freeze['edited_history']['test/'+str(i)+'.test.js']['duration'] for i in range(1,5)],'slow_file_count_at_unchanged_threshold150':freeze['expected_slow_file_count'],'test_source_and_fixture_programs_byte_unchanged':True,'notes':'Joint history-only setup change exposes original first-shard assertion; both reference assertions pass.' if cid=='candidate_002' else 'Proper-subset ablation: selected original test passes P and R twice; this subset does not expose the defect.','ablation':{'proper_subsets':['candidate_003','candidate_004','original_baseline'],'all_proper_subsets_P_and_R_pass_twice':True,'local_interaction_order':2,'global_minimality_claim':False} if cid=='candidate_002' else {'removes':'F2' if cid=='candidate_003' else 'F1','from':'candidate_002','P_and_R_PASS_twice':True}})
assert len(cells)==12
new['candidates'][0]['legitimacy_status']='Original threshold-argument edit retained; setup/target-input boundary pending root adjudication.'
new['candidates'][0]['mechanism_postcheck']=str(C/'O4_mechanism_postcheck.json')
new['candidates'].extend(summaries);new['candidate_count']=len(new['candidates']);new['all_attempts']=old['all_attempts']+cells
new['successful_candidate_ids']=['candidate_001','candidate_002'];new['history_only_successful_candidate_ids']=['candidate_002']
new['outcome_pending_independent_review']='Multi-factor Context Repair'
new['mechanism_postcheck']=str(C/'O4_history_candidates_postcheck.json')
new['strict_behavioral_masking_confirmed']=False;new['strict_behavioral_masking_supported_by_execution']=False;new['mechanism_classification_pending_independent_review']='Target Bypass'
new['factorization_scope']='F1 and F2 are independently changeable per-file historical duration cache entries. Their joint effect changes derived slow-file count from3 to1. The demonstrated order2 interaction is local to this factorization; no global minimum or unique factorization is claimed.'
new['candidate_001_boundary_pending_root_adjudication']=True
# Verifier identity is unchanged and its prior exact-source repeated receipt is reused, not rerun/copied as candidate.
new['verifier_reuse']='Same delivered/reference checkpoint identity, official test.patch, selector command, environment and four original verifier result receipts as before. Candidate cache changes occur only in separate fresh agent-test containers. The official selector executes4 tests:2 behavioral isolation checks plus2 config validation checks.'
save(C/'matrix_summary.json',new)
b=read(C/'baseline_observation.json');b['history_candidate_baseline_reuse']={'candidates':['candidate_002','candidate_003','candidate_004'],'original_baseline':baseline,'identity_checked':'Original test source, fixture programs/history, commands, checkpoint, environment, reference plan and input receipts match the original candidate001 baseline exactly. Each original P/R cell is reused twice by identity; no new baseline executions are implied.'};save(C/'baseline_observation.json',b)
history_summary={'schema':'confirmed-gaps-history-factorial.v1','screen_id':'S085','all_12_new_executions_complete':True,'test_source_byte_unchanged':True,'test_sha256':sha(C/'prepared_candidate_001/original.ts'),'four_fixture_test_programs_byte_unchanged':True,'original_baseline_exact_reuse':baseline,'specific_official_verifier_exact_reuse':old['specific_official_verifier'],'rows':[{'factor_ids':[],'durations':[400,300,200,100],'slow_count':3,'P':'PASS x2','R':'PASS x2','source':'original candidate001 baseline reused'},{'factor_ids':['F1'],'durations':[400,100,200,100],'slow_count':2,'P':'PASS x2','R':'PASS x2','candidate':'candidate_003'},{'factor_ids':['F2'],'durations':[400,300,100,100],'slow_count':2,'P':'PASS x2','R':'PASS x2','candidate':'candidate_004'},{'factor_ids':['F1','F2'],'durations':[400,100,100,100],'slow_count':1,'P':'FAIL x2','R':'PASS x2','candidate':'candidate_002'}],'candidates':summaries,'outcome_pending_independent_review':'Multi-factor Context Repair','local_interaction_order':2,'global_minimality_claim':False,'new_execution_count':12,'all_case_execution_count':len(new['all_attempts']),'strict_behavioral_masking':False,'candidate_001_retained':str(old_path),'independent_reviews':'Not read; root adjudication pending','DeepSeek_calls':0}
save(C/'history_factorial_summary.json',history_summary)
post={'schema':'confirmed-gaps-success-postcheck.v1','screen_id':'S085','candidate':'candidate_002','postcheck_after_success':True,'matrix_summary':str(C/'history_factorial_summary.json'),'O2':{'semantic_factor_count':2,'factor_ids':['F1','F2'],'factorization':'Independent recorded durations for file2 and file3. F1 changes300→100; F2 changes200→100. The shared derived slow-count is an effect of the two independent record changes, not an additional factor.','interaction_evidence':'Both singleton subsets pass P/R twice; only the pair fails P while R passes twice. Empty subset reuses exact original P/R baselines.','minimality_scope':'Necessary pair within these two frozen independent record changes only; no claim of global minimality or unique semantic factorization.'},'O3':'Persisted per-item historical cache state controlling branch selection','O4':{'same_edit_evidence_found':False,'earlier_actions':[{'step':87,'classification':'Related history-state exploration, different fixture/programs','action':'Agent ran earlier a/b/c/d fixtures with recordFileDurations enabled and printed cache observations about304/102/54/13. This demonstrates historical state inspection, not the same final-file cache edit.'},{'step':95,'classification':'Related target/configuration exploration, different stimulus and observation','action':'With the earlier a/b/c/d fixture and threshold200, raw output put a+b into first shard and c+d into second. The command filtered/printed paths; it did not contain the later exact shard-set assertions. This related defect exposure does not establish strict masking in the selected final c0.'},{'step':107,'classification':'Exact baseline cache construction, not the candidate edit','action':'Agent wrote the final independent duration-history.json entries400/300/200/100 with recordedAt1700000000000 and the four no-op numbered fixture tests. These are the baseline values now varied.'},{'step':108,'classification':'Exact selected original test construction','action':'Agent authored both runVitest calls with threshold150 and shard1/2 then2/2, and exact expected sets[1] and[2,3,4]. The comment explicitly identifies three slow files at baseline.'},{'step':112,'classification':'Archived successful validation','action':'Original duration-shard suite8 tests passed.'},{'step':149,'classification':'Archived final successful validation','action':'Final original shard and duration-shard suites19 tests passed.'}],'relation_to_repair':'The new repair changes two existing cache entries only. The earlier exact same300→100 and200→100 edits were not found; the available evidence supports baseline construction and related cache/isolation exploration. Do not label this as replaying a known same edit.','agent_intent_inferred':False},'original_c0_target':'With unchanged threshold150 and history400/300/200/100, slowcount3>=2 shards. P takes its else branch and produces the original expected sets, matching R. No defect-related target effect difference under this selected original c0 is established.','edited_c1_mechanism':'Only the joint cache edit makes slowcount1<2. P assigns the fast files across both shards, including the reserved first shard; the unchanged first assertion sees[1,2,4] rather than[1]. R returns the isolated slow file for first shard and all remaining files for second. Each singleton leaves slowcount2 and follows the correct other branch.','strict_Def1':{'classification':'Target Bypass','original_target_effects_different_established':False,'reason':'The defect-related fast-file redistribution branch is selected only by the joint edited history. Earlier raw evidence with different fixtures/context does not establish a difference under the selected original c0.'},'evidence':[evidence(R/'screening/S085/evidence/trajectory-evidence.txt',['STEP 87','STEP 95','STEP 107','STEP 108','STEP 112','STEP 149','"test/2.test.js": { "duration": 300','"test/3.test.js": { "duration": 200','slow files (1, 2, 3)','19 passed']),evidence(R/'screening/S085/evidence/model.patch',['if (slow.length < shardCount)','const remainingAssignment = shardByStrategy(remaining','newAssignment[index].push(...group)','newAssignment[shardCount - 1].push(...remaining)']),evidence(pathlib.Path('/home/jhx/oracle_gap/external/deep-swe/tasks/vitest-duration-sharding/solution/solution.patch'),['if (isolated.length >= count)','if (index <= isolated.length)','effectiveCount = remainingShardCount'])],'independent_reviews':'Not read; independent semantic reviews and root adjudication pending','preservation':'Entire original.ts, both threshold150 arguments, shards, all fixture test programs, parsePaths and original assertions byte-identical. All recordedAt fields remain byte-identical.'}
save(C/'O4_history_candidates_postcheck.json',post)
print('S085 12 new actual1-test executions; joint PFAIL/RPASS2; both singletons P/RPASS2; total attempts',len(new['all_attempts']))
