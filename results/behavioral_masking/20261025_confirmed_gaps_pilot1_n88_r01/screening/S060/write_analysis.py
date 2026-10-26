import json,re
from pathlib import Path
R=Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01')
XS={x['screen_id']:x for x in json.loads((R/'screening_order.json').read_text())['trials']}
def write(sid,steps,passed,tests,fail,contract,alignment,diffs,decision,outcome='Not Comparable / Unresolved',candidate=None,notes=None):
 x=XS[sid];e=R/'screening'/sid/'evidence';refs=[]
 for name in ['instruction.md','model.patch','verifier.patch','verifier-stdout.txt','trajectory-evidence.txt']:
  lines=(e/name).read_text().splitlines();needles=tests+(['STEP '+str(z)+' TOOL' for z in steps] if name=='trajectory-evidence.txt' else [])
  anchors=[{'line':i,'text':z[:220]} for i,z in enumerate(lines,1) if any(n in z for n in needles) or (name=='verifier-stdout.txt' and re.search(r'FAIL|expected:|actual  :|left:|right:',z))]
  refs.append({'path':str(e/name),'anchors':anchors[:130],'original_source_manifest':str(e/'sources.json')})
 d={'schema_version':'confirmed-gaps-screening.v1','screen_id':sid,'trial':x['trial'],'task':x['task'],'known_case':x.get('known_case'),'status':'candidate_frozen_awaiting_execution' if candidate else 'screened_no_legal_candidate_identified','investigator':'Codex manual raw-source review','step1':{'agent_validation':{'qualification':'archived successful task-relevant execution','evidence':passed,'steps':steps,'fresh_execution':False},'verifier_behavioral_failure':fail,'task_contract':contract,'fresh_P_R_baselines':'pending for justified candidates; archive not represented as fresh execution'},'related_original_tests':tests,'manual_pair_alignment':alignment,'complete_context_and_stimulus_differences':diffs,'joint_factor_consideration':decision,'candidate_files':[candidate] if candidate else [],'provisional_outcome':outcome,'execution_outcome':'pending candidate baseline/matrix' if candidate else 'not executed: no legal candidate identified; not an executed negative search','source_evidence':refs,'notes':notes,'prior_review_use':'2026-10-21 navigation only; raw instruction/model.patch/trajectory/tests/stdout used for current finding','independent_reviews':'pending two independent Codex reviews','DeepSeek_calls':0}
 (R/'screening'/sid/'analysis.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
