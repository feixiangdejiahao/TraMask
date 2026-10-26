import hashlib,json,pathlib,collections
R=pathlib.Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01')
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(pathlib.Path(p).read_text())
def write(p,x):pathlib.Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
rows=[];total=0;diags=0
for s in ['S014','S019','S042','S059','S062']:
 c=R/'cases'/s;m=read(c/'matrix_summary.json');checks=collections.Counter()
 for p in c.rglob('*.json'):
  read(p);checks['parseable_json']+=1
 prep=c/'prepared_candidate_001'
 for name,receipt in read(prep/'input_receipts.json').items():
  p=prep/name;assert sha(p)==receipt['sha256'];assert p.stat().st_size==receipt['bytes'];checks['prepared_receipts_matched']+=1
 candidate=m['candidates'][0];assert candidate['execution_matrix_satisfied'];assert candidate['semantic_factor_count']==1
 for cell,want in [('original_delivered','PASS'),('original_reference','PASS'),('edited_delivered','FAIL'),('edited_reference','PASS')]:
  xs=candidate['matrix'][cell];assert len(xs)==2
  for x in xs:assert x['verdict']==want and x['actual_test_counts']['executed']==1
  checks['valid_matrix_cells']+=len(xs)
 assert len(m['specific_official_verifier'])==4
 for x in m['specific_official_verifier']:
  assert x['verdict']==('FAIL' if '/verifier_delivered/' in x['attempt'] else 'PASS')
  assert x['actual_test_counts']['executed']==1
  checks['valid_verifier_cells']+=1
 attempts=m['all_attempts']+m['postcheck_diagnostics_excluded_from_repair_matrix']
 for a in attempts:
  p=pathlib.Path(a['result']);assert sha(p)==a['result_sha256'];x=read(p);e=x['execution']
  assert a['production_source_unchanged_during_execution']
  for stream in ['stdout','stderr']:
   raw=pathlib.Path(e['raw_'+stream]);assert raw.exists();assert sha(raw)==e[stream+'_sha256'];checks['raw_stream_hashes_matched']+=1
  for receipt in read(p.parent/'input_receipts.json'):
   for key in ['source','frozen']:
    z=receipt[key];fp=pathlib.Path(z['path']);assert fp.exists();assert sha(fp)==z['sha256'];assert fp.stat().st_size==z['bytes'];checks['execution_input_hashes_matched']+=1
  checks['attempt_result_hashes_matched']+=1
 o=read(c/'O4_mechanism_postcheck.json')
 for ev in o['evidence']:
  assert sha(ev['path'])==ev['sha256'];checks['postcheck_evidence_hashes_matched']+=1
  lines=pathlib.Path(ev['path']).read_text().splitlines()
  for a in ev.get('anchors',[]):assert lines[a['line']-1].startswith(a['text'])
 total+=len(m['all_attempts']);diags+=len(m['postcheck_diagnostics_excluded_from_repair_matrix'])
 row={'screen_id':s,'baseline_observation':str(c/'baseline_observation.json'),'matrix_summary':str(c/'matrix_summary.json'),'postcheck':str(c/'O4_mechanism_postcheck.json'),'successful_candidate_ids':['candidate_001'],'execution_outcome_pending_independent_review':'Single-factor Context Repair','semantic_factor_count':1,'mechanism_pending_independent_review':o['strict_Def1']['classification'],'strict_c0_effect_difference_supported':o['strict_Def1']['original_target_effects_different_established'],'retained_normal_attempts':len(m['all_attempts']),'retained_postcheck_diagnostics':len(m['postcheck_diagnostics_excluded_from_repair_matrix']),'retained_attempt_verdicts':dict(collections.Counter(x['verdict'] for x in m['all_attempts'])),'checks':dict(checks)}
 rows.append(row);print(s,json.dumps(row['retained_attempt_verdicts']),dict(checks))
# Read-only diagnostic changes exactly two observation lines, retaining the complete original test.
d=R/'cases/S059/diagnostic_c0';orig=R/'cases/S059/prepared_candidate_001/original_selected_test.go';x=read(d/'frozen.json');assert sha(orig)==x['source_sha256'];assert sha(d/'original_with_readonly_state_log.go')==x['diagnostic_sha256']
text=(d/'original_with_readonly_state_log.go').read_text();without=''.join(line for line in text.splitlines(keepends=True) if 'pilot1High, pilot1Err :=' not in line and 'PILOT1_C0_DURABLE_STATE' not in line);assert without==orig.read_text()
write(R/'cases/S014/execution_handoff_index.json',{'schema':'confirmed-gaps-followup-execution-handoff.v1','scope':['S014','S019','S042','S059','S062'],'execution_complete':True,'normal_attempts_retained':total,'postcheck_diagnostics_retained':diags,'all_attempts_retained':total+diags,'cases':rows,'all_five_matrices_satisfied_two_repeats':True,'specific_official_verifiers_all_actual_one_test_two_repeats':True,'frozen_inputs_raw_streams_and_source_snapshots_verified':True,'invalid_attempts':'S042 original8 CLI errors and S059 original4 no-test verifier attempts remain archived and excluded from qualified matrices. S059 original4 valid baseline attempts are retained in addition to the corrected actual8cells baseline.','S059_diagnostic':str(d/'summary.json'),'mechanism_support':'S059 observed original c0 frontier11(P) versus10(R), both original tests PASS. Other four classified Target Bypass by investigator. Independent semantic review is still required.','review_status':'Neither independent-review artifact has been read; root adjudication pending.','global_or_runtime_files_modified':False,'DeepSeek_calls':0})
print('TOTAL',total,diags,total+diags)
