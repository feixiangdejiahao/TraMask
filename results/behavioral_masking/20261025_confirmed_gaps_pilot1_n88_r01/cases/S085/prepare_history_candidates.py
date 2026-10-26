import pathlib,json,hashlib,shutil,difflib,datetime,copy
R=pathlib.Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01');C=R/'cases/S085';src=C/'prepared_candidate_001'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
hist=pathlib.Path('required-files/test/config/fixtures/duration-shard/duration-history.json')
old=(src/hist).read_text();original=json.loads(old)
base_summary=json.loads((C/'matrix_summary.json').read_text());base=base_summary['candidates'][0]['matrix']
factors={'F1':{'cache_record':'test/2.test.js','field':'duration','original':300,'edited':100},'F2':{'cache_record':'test/3.test.js','field':'duration','original':200,'edited':100}}
for cid,fs in [('candidate_002',['F1','F2']),('candidate_003',['F1']),('candidate_004',['F2'])]:
 p=C/('prepared_'+cid);assert not p.exists();p.mkdir();shutil.copy2(src/'original.ts',p/'original.ts');shutil.copytree(src/'required-files',p/'required-files')
 text=old
 for f in fs:
  v=factors[f];before='"'+v['cache_record']+'": { "duration": '+str(v['original'])
  after='"'+v['cache_record']+'": { "duration": '+str(v['edited'])
  assert text.count(before)==1;text=text.replace(before,after)
 (p/hist).write_text(text);new=json.loads(text)
 for key in original:
  assert new[key]['recordedAt']==original[key]['recordedAt']
  assert new[key]['duration']==(100 if key in [factors[f]['cache_record'] for f in fs] else original[key]['duration'])
 (p/'history-only.diff').write_text(''.join(difflib.unified_diff(old.splitlines(keepends=True),text.splitlines(keepends=True),fromfile='a/test/config/fixtures/duration-shard/duration-history.json',tofile='b/test/config/fixtures/duration-shard/duration-history.json')))
 for f in (src/'required-files').rglob('*.js'):assert sha(f)==sha(p/f.relative_to(src))
 assert sha(src/'original.ts')==sha(p/'original.ts')
 manifest={str(f.relative_to(p)):{'sha256':sha(f),'bytes':f.stat().st_size} for f in sorted(p.rglob('*')) if f.is_file()}
 freeze={'schema':'confirmed-gaps-history-candidate.v1','screen_id':'S085','candidate_id':cid,'frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'frozen_before_execution':True,'source':str(src/'original.ts'),'selected_test':'isolateSlowThreshold isolates slow files across shards','test_source_byte_unchanged':True,'original_test_sha256':sha(src/'original.ts'),'fixture_test_programs_byte_unchanged':True,'protected_operations':'Both complete original runVitest calls: shard1/2 and2/2, shardStrategy time, isolateSlowThreshold150, durationHistoryPath historyPath. All original parsePaths operations/assertions and full original.ts file unchanged.','protected_assertions':[['1.test.js'],['2.test.js','3.test.js','4.test.js']],'setup_only_delta':'Change only the specified independent duration cache records; recordedAt, filenames, fixture program text and test configuration are unchanged.','factor_ids':fs,'factors':{f:factors[f] for f in fs},'semantic_factor_count':len(fs),'original_history':original,'edited_history':new,'expected_slow_file_count':sum(v['duration']>=150 for v in new.values()),'hypothesis':'Joint F1+F2 leaves only file1 slow, exposing P fast-file assignment over all shards; either proper subset leaves2 slow files and should retain original expected shard sets. These are predictions, not results.','local_ablation_scope':'Two independently changeable cache entries. All three nonempty subsets frozen before execution; original empty subset uses exact original baseline receipts. No global minimality claim.','baseline_reuse':{k:base[k] for k in ['original_delivered','original_reference']},'original_baseline_reference':str(C/'matrix_summary.json'),'files':manifest,'independent_reviews':'Not read; root adjudication pending'}
 save(p/'frozen.json',freeze);manifest['frozen.json']={'sha256':sha(p/'frozen.json'),'bytes':(p/'frozen.json').stat().st_size};save(p/'input_receipts.json',manifest)
 for impl in ['delivered','reference']:
  q=json.loads((C/'execution_plans'/('candidate_001_original_'+impl+'.json')).read_text())
  for f in q['files']:f['source']=str(p/pathlib.Path(f['source']).relative_to(src))
  save(C/'execution_plans'/(cid+'_edited_'+impl+'.json'),q)
 print(cid,p/'frozen.json',fs,'test_sha256',sha(p/'original.ts'))
