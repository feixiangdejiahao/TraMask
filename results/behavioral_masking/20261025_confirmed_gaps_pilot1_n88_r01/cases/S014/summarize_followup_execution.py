from pathlib import Path
import json,re,hashlib
# Reuse the already-reviewed receipt formatter only; never execute its old case-writing loop.
formatter=Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01/cases/S068/summarize_execution.py').read_text().split('\nnotes={',1)[0]
exec(formatter)
R=Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01')
SIDS=['S014','S019','S042','S059','S062']
BASE={'S014':'baseline','S019':'baseline','S042':'baseline_cli_fixed','S059':'actual8cells','S062':'baseline'}
DETAILS={
'S014':'Resolve the original deferred initial fetch with existing fruits and drain microtasks before the unchanged a keypress/debounce. Original signalcount2 and firstsignal.aborted assertions preserved. P leaves firstsignal.aborted false; R true.',
'S019':'Omit explicit put options in two parser constructions. Same original schema, payloads, parse operation and all4 throw/notthrow assertions. P does not throw for conditionallymissing details; R does. Inline parser construction vs target argument boundary still needs semantic review.',
'S042':'Move original createRemoved before pair-bearing player spawn; preserve original pre-removal empty query, remove Likesapple, final toContainplayer assertion. P returns[]; R containsplayer. The initialquery stilldelimits the observationwindow; no adding/deleting targetevent.',
'S059':'Preload NoSync history with unchanged-key writes until the next sequence is99999, before launching the unchanged WaitForDurability100000. Same Seta1Sync and pending/no-early-return/ErrClosed assertions. P unblocks early; R remainsblocked untilClose.',
'S062':'Both endpoint max_channels256→1; preserve channelID7, open/accept, ID equality, duplicate check and cleanup. P raises illegal ID>capacity ValueError before equality; R succeeds equality and duplicate ValueError OK. Standalone original unit has explicitassertions, not framework testcount.'}

def receipt(f,case):
 d=cell(f);a=json.loads(f.read_text());x=a.get('execution',{});out=x.get('stdout','')+'\n'+x.get('stderr','');d['attempt']=str(f.parent.relative_to(case))
 if 'Unknown option `--minWorkers`' in out:d['verdict']='CLI_ERROR';d['actual_test_counts']={'executed':0,'passed':0,'failed':0};d['failure_stage']='test runner argument parsing'
 if case.name=='S062' and x.get('command')=='python /tmp/pilot1_selected.py':
  passed=x.get('returncode')==0 and 'duplicate ValueError OK' in out and 'FAIL duplicate' not in out
  failed=x.get('returncode')==1 and 'ValueError: channel id 7 exceeds max_channels 1' in out
  d['verdict']='PASS' if passed else 'FAIL' if failed else 'UNRESOLVED';d['actual_test_counts']={'executed':1,'passed':int(passed),'failed':int(failed),'count_kind':'one frozen original standalone validation unit; no framework discovery count'}
 return d

for sid in SIDS:
 case=R/'cases'/sid;cells=[]
 for group in ['baseline','baseline_cli_fixed','actual8cells','candidate_001']:
  for f in sorted((case/group).glob('*/repeat_*/result.json')):cells.append(receipt(f,case))
 baseline=[x for x in cells if x['attempt'].startswith(BASE[sid]+'/')]
 original=[x for x in baseline if '/original_' in x['attempt']];ver=[x for x in baseline if '/verifier_' in x['attempt']]
 edited=[x for x in cells if x['attempt'].startswith('candidate_001/')]
 matrix={}
 for variant in ['original','edited']:
  for impl in ['delivered','reference']:
   key=variant+'_'+impl;rows=[x for x in (original if variant=='original' else edited) if '/'+key+'/' in x['attempt']];matrix[key]=rows
   assert len(rows)==2,(sid,key,len(rows));expected='FAIL' if key=='edited_delivered' else 'PASS'
   assert all(x['verdict']==expected and x['actual_test_counts']['executed']==1 for x in rows),(sid,key)
 assert len(ver)==4 and all(x['verdict']==('FAIL' if '/verifier_delivered/' in x['attempt'] else 'PASS') and x['actual_test_counts']['executed']==1 for x in ver),sid
 invalid=[x for x in cells if x['verdict'] in ['NO_TESTS','CLI_ERROR','COLLECTION_ERROR','PREPARATION_ERROR']]
 base={'schema':'confirmed-gaps-baseline.v1','screen_id':sid,'qualification':str(case/'checkpoint_validation/qualification.json'),'qualified_baseline_group':BASE[sid],'original_tests':original,'specific_official_verifier':ver,'invalid_attempts':invalid,'all_baseline_attempts':[x for x in cells if not x['attempt'].startswith('candidate_001/')],'manual_verdict_rule':'Actual selected test count plus assertion/error output inspected; rc0 alone is not a pass.','command_correction':{'S042':'Removed only unsupported --minWorkers1 for Vitest4, preserved --maxWorkers1; original8 CLI errors retained.','S059':'Added official -tags batch_durable to verifier invocation; original4zero-test runs retained. Newactual8cells includes originalP/R2repeat aswell.'}.get(sid)}
 (case/'baseline_observation.json').write_text(json.dumps(base,ensure_ascii=False,indent=2)+'\n')
 diag=[receipt(f,case) for f in sorted((case/'diagnostic_c0/executions').glob('*/result.json'))]
 summary={'schema':'confirmed-gaps-matrix.v1','screen_id':sid,'execution_stage_complete':True,'candidate_count':1,'candidates':[{'candidate_id':'candidate_001','freeze':str(case/'prepared_candidate_001/frozen.json'),'matrix':matrix,'execution_matrix_satisfied':True,'semantic_factor_count':1,'notes':DETAILS[sid],'ablation':{'method':'Remove sole semantic setup change; original baseline is precisely this control and passesP/R twice.','global_minimality_claim':False}}],'specific_official_verifier':ver,'all_attempts':cells,'postcheck_diagnostics_excluded_from_repair_matrix':diag,'outcome_pending_independent_review':'Single-factor Context Repair','successful_candidate_ids':['candidate_001'],'strict_behavioral_masking_confirmed':False,'mechanism_postcheck':str(case/'O4_mechanism_postcheck.json'),'reviews':'Not read; independent semantic review and root adjudication pending','DeepSeek_calls':0}
 if sid=='S059':summary['strict_behavioral_masking_status']='Pending original-c0 readonly DurableState diagnostic; not inferred from feature execution.'
 assert all(x['production_source_unchanged_during_execution'] is True for x in cells+diag),(sid,'production drift')
 (case/'matrix_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 print(sid,len(cells),'attempts',len(diag),'diagnostics; validmatrix')
