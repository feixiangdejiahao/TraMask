import json,pathlib,re,hashlib
RUN=pathlib.Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01')
CASES=json.loads((RUN/'screening_order.json').read_text())['trials']
def put(n,steps,agent,verifier,pairs,differences,decision,category,anchors,extra=None):
 c=CASES[n-1];d=RUN/'screening'/c['screen_id'];t=json.loads((pathlib.Path(c['input_directory'])/'trajectory.json').read_text()); selected=[s for s in t['steps'] if s['step_id'] in steps];(d/'evidence/selected_agent_steps.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2))
 refs=[]
 for filename,needle in anchors:
  p=d/'evidence'/filename; lines=p.read_text().splitlines();matches=[i+1 for i,l in enumerate(lines) if needle in l];refs.append({'source':str(p),'anchor':needle,'lines':matches})
 definitions=[]
 for l in (d/'evidence/model.patch').read_text().splitlines():
  if re.match(r'^\+(?:def test|async def test|func Test|test\(|it\(|describe\()',l):definitions.append(l[1:])
 a={'schema_version':'confirmed-gaps-pilot1.manual-screen.v1','screen_id':c['screen_id'],'trial':c['trial'],'task':c['task'],'known_case':c.get('known_case'),'investigator':'Codex manual investigator, middle slice','status':'screened_pending_two_independent_reviews','source_manifest':'sources.json','raw_evidence':'evidence/','step1':{'archived_agent_success':True,'agent_validation':agent,'agent_steps':steps,'actual_verifier_behavioral_failure':verifier,'qualification':'Archived successful validation and behavioral verifier failure established; fresh P/R baselines not run at screening stage.'},'relevant_original_tests':{'all_authored_test_definitions_in_delivered_patch':definitions,'exact_sources':'evidence/model.patch; evidence/agent_sources/ when file was newly added; evidence/selected_agent_steps.json for transient scripts/version','manual_comparable_pair_search':pairs},'complete_context_difference_analysis':differences,'multifactor_consideration':decision,'outcome_category':category,'candidate_status':'no_legal_candidate_frozen','candidate_count':0,'execution':{'fresh_runs':0,'reused_matrix_runs':0,'negative_search_executed':False,'reference_baseline':'not executed; no claim that original test passes reference'},'source_locations':refs,'limits':['No assertion of impossibility or exhaustive context search.','Prior supported label only selected this trial; conclusions use raw archived evidence.','All test inputs, fixture program source and assertions are protected; a setup label does not legalize changing them.']}
 if extra:a.update(extra)
 (d/'analysis.json').write_text(json.dumps(a,ensure_ascii=False,indent=2)+'\n')
