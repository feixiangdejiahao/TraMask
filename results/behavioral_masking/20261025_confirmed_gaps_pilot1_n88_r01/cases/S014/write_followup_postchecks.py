import hashlib,json,pathlib,re
R=pathlib.Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01')
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def evidence(p,needles,limit=24):
 p=pathlib.Path(p);hits=[];step=None
 for n,line in enumerate(p.read_text().splitlines(),1):
  if line.startswith('STEP '):step=line
  if any(q in line for q in needles):hits.append({'line':n,'step':step,'text':line[:350]})
 assert hits,(p,needles)
 return {'path':str(p),'sha256':sha(p),'anchors':hits[:limit]}
def calls(s,steps):
 p=R/'screening'/s/'trajectory_tool_calls.jsonl';out=[]
 for n,line in enumerate(p.read_text().splitlines(),1):
  x=json.loads(line)
  if x['step'] in steps:
   out.append({'line':n,'step':x['step'],'call_index':x['call_index'],'command':x['command'],'observation':x['observation']})
 return {'path':str(p),'sha256':sha(p),'exact_selected_calls':out}
def model(s):
 m=json.loads((R/'screening'/s/'evidence_sources.json').read_text())
 return pathlib.Path(next(x['path'] for x in m['sources'] if x['path'].endswith('/model.patch')))
def strip_ansi(x):return re.sub(r'\x1b\[[0-9;]*m','',x)
D={}
D['S014']={
 'O2':{'semantic_factor_count':1,'factor':'Initial asynchronous fetch has completed before the unchanged next-keypress fetch. Resolving the existing deferred value and draining its microtasks implement one lifecycle condition.'},
 'O3':'Prior asynchronous operation lifecycle state',
 'O4':{'earlier_action':'At original step 53 the agent authored the selected new fetch aborts previous signal test with deferred resolvers but never resolved the initial request before keypress a. That named test passed in the same output, although another cache test failed. Final step 149 successfully ran the core and prompts suites.','relation':'The frozen repair resolves only the initial request with the already defined fruits and drains two microtasks before the original a keypress, fake-clock advancement and both signal assertions.','agent_intent_inferred':False,'archived_count_correction':'Step 149 raw output is core two files / 42 tests and prompts two files / 30 tests. The screening shorthand core30 is not an exact quotation of that aggregate output. Fresh selected runs execute exactly one test.'},
 'original_c0_target':'First fetch remains pending. P retains its AbortController until the next #startFetch calls #abortCurrentFetch; the original assertion sees true, as does R.',
 'edited_c1_mechanism':'Resolving the first fetch executes P #handleFetchSuccess, which clears #abortController. The unchanged next fetch cannot abort the old signal and the original signals[0].aborted assertion fails false versus true. R retains the previous controller and passes.',
 'strict_Def1':{'classification':'Target Bypass','original_target_effects_different_established':False,'reason':'The original pending-first-request condition does not execute the completed-request controller-clearing defect before the next fetch. Invoking asynchronous autocomplete and abort logic is insufficient to establish a defect-related difference under original c0.'},
 'evidence':[calls('S014',[53,149]),evidence(model('S014'),['#startFetch(search: string)','#handleFetchSuccess(id: number','this.#abortController = undefined;','#abortCurrentFetch(): void']),evidence(R/'cases/S014/prepared_candidate_001/agent_test_original.ts',["test('new fetch aborts previous signal'","resolvers.set(search, resolve)",'expect(signals[0].aborted)'])]
}
D['S019']={
 'O2':{'semantic_factor_count':1,'factor':'Use omitted/default parser configuration in both original parser constructions instead of explicit put. Two replacements express one shared configuration condition; all payloads and formatter assertions remain.'},
 'O3':'Equivalent default configuration path',
 'O4':{'earlier_action':'Original step 124 exploratory Zod checks used explicit put mode. Step 161 authored the selected named test with explicit put parser calls. Step 174 removed a separate unsupported update-mode assertion; that deletion predates the frozen delivered original and is not part of this candidate. Final step 180 passed the eight requiredIf tests and step 201 passed 730 schema tests.','relation':'The agent explicitly selected the put-mode branch in both relevant original parser expressions. The repair relies on the specified default put semantics while retaining the same parse calls and exact missing/present-details payloads and assertions.','agent_intent_inferred':False},
 'original_c0_target':'P withRequiredIf receives mode=put, installs the refinement, and rejects the same missing-details payload that R rejects. The present-details payload and formatter checks pass.',
 'edited_c1_mechanism':'With omitted options, P destructures mode without a default; undefined !== put returns the unrefined Zod schema. The first original toThrow(z.ZodError) assertion fails. R treats omitted mode as put and passes all original assertions.',
 'strict_Def1':{'classification':'Target Bypass','original_target_effects_different_established':False,'reason':'The explicit-put c0 takes the correct refinement branch; the default-option bug is activated only in c1. No defective parse effect under c0 is established.','legitimacy_boundary':'Parser construction occurs inline inside the assertion expression. The investigator treats its options as parser configuration before the parse operation; independent review must adjudicate this target/setup boundary. Parse stimulus and assertion are byte-preserved.'},
 'evidence':[calls('S019',[124,161,174,180,201]),evidence(model('S019'),['{ mode }: ZodParserOptions',"if (!hasRequiredIf || mode !== 'put')"]),evidence(R/'cases/S019/prepared_candidate_001/agent_test_original.ts',["test('zod parser and formatter enforce requiredIf'","zod.parser({ mode: 'put' })",'zod.formatter().parse'])]
}
D['S042']={
 'O2':{'semantic_factor_count':1,'factor':'Create the Removed tracking factory before initial relation population instead of after it. The existing empty query that opens/resets the observation window is retained.'},
 'O3':'Observer registration lifetime relative to existing state',
 'O4':{'earlier_action':'Step 83 authored Removed pair works when the query is created before the removal with createRemoved after player spawn. Its named check passed, although a separate cancellation case failed in that earlier suite. Final step 154 passed the original pair suite (29 tests) and all core tests (166).','relation':'The original action sequence creates an observer after existing pairs, queries an empty removal set, removes the apple pair and asserts inclusion. Moving only observer creation before spawn introduces prior add history that should be outside the later observation window.','agent_intent_inferred':False},
 'original_c0_target':'The Removed tracker is created after both player pairs exist. Its added map does not contain the original apple add. The unchanged removal records the removed target, so the final query contains player in P and R.',
 'edited_c1_mechanism':'Creating the tracker before player spawn records the initial apple add. P retains that added event across the unchanged initial query, then markPairEvent(remove) deletes it and marks the removal canceled. The final query is empty. R respects the observation boundary and reports the removal.',
 'strict_Def1':{'classification':'Target Bypass','original_target_effects_different_established':False,'reason':'Original c0 has no preceding tracked add to trigger the erroneous cross-window cancellation. The target removal and oracle agree in P/R under c0; merely exercising pair removal is not strict masking.'},
 'infrastructure_correction':'The first eight attempts rejected --minWorkers before collection under Vitest 4. All are preserved and excluded. New execution_plans_fixed omit only that unsupported flag; baseline_cli_fixed and candidate_001 execute the intended one test per run.',
 'evidence':[evidence(R/'screening/S042/evidence/trajectory_commands.txt',["it('Removed pair works when the query is created before the removal'",'STEP 154','166 passed']),evidence(R/'screening/S042/evidence/model.patch',['Initial pairs at factory creation','Uncancelled pair additions','const addedByEntity = tracker.added','if (addedTargets?.delete(target))']),evidence(R/'cases/S042/prepared_candidate_001/original_test_file.ts',["it('Removed pair works when the query is created before the removal'",'const Removed = createRemoved();'])]
}
D['S059']={
 'O2':{'semantic_factor_count':1,'factor':'Pre-existing database sequence history: append a NoSync batch so the next unchanged original Sync write receives sequence 99999. All original WaitForDurability(100000), Set(a,1,Sync), pending-count, no-completion, Close and ErrClosed checks remain.'},
 'O3':'Distance between pre-existing state and a fixed observation threshold',
 'O4':{'earlier_action':'Step 117 authored TestWaitForDurabilityWaits on an empty in-memory database and explicitly commented that a Sync commit does not cover sequence 100000. The unchanged original test performs one one-key Sync commit and then checks that the waiter remains blocked. Steps 231, 233 (invariants), 234 (race) and final 244 executed suites selecting this WaitFor test successfully.','relation':'The original chosen target is far above the first actual Sync sequence. The repair preloads only database history so the unchanged next Sync is immediately below the same fixed target. This reveals the existing off-by-one frontier effect without changing the target sequence or assertions.','agent_intent_inferred':False},
 'original_c0_target':'The original one-key Sync writes actual sequence 10. P records highest durable sequence 11; R records 10. Both remain below the original waiter target 100000, so both original tests pass. This defect-related target effect difference is measured twice per implementation by a post-success read-only DurableState diagnostic.',
 'edited_c1_mechanism':'With the preloaded history, the unchanged Sync write covers sequence 99999. P stores exclusive end 100000 as if it were the inclusive highest durable sequence and wakes WaitForDurability(100000), violating the original no-premature-completion assertion. R stores 99999 and preserves the blocked waiter until the unchanged Close check.',
 'strict_Def1':{'classification':'Behavioral Masking','original_target_effects_different_established':True,'reason':'Under original c0, the defect changes the durable frontier from the correct 10 to 11. The original observation projects either frontier to pending at target100000 and therefore hides that difference. Context repair places the same fixed threshold between the correct and erroneous frontier. This is stronger than feature execution or branch coverage.','evidence_status':'Execution-supported investigator conclusion; two independent semantic reviews/root adjudication remain pending.','target_boundary':'The selected original validation consists of a Wait subscription, a Sync write producing the shared durability frontier, and the waiter observation. The diagnostic observes that frontier effect of the original Sync; it is not a replacement assertion or a candidate repair.'},
 'infrastructure_correction':'The original four verifier attempts selected zero tests because the official batch_durable build tag was missing. They remain archived as NO_TESTS. New execution_plans_verifier_fixed and actual8cells include the exact official tag/name, with one behavioral test actually executed each time.',
 'diagnostic':str(R/'cases/S059/diagnostic_c0/summary.json'),
 'evidence':[evidence(R/'screening/S059/evidence/trajectory_commands.txt',['STEP 117','func TestWaitForDurabilityWaits','A sync commit does not cover seqnum 100000','STEP 231','STEP 233','STEP 234','STEP 244']),evidence(R/'screening/S059/evidence/model.patch',['seqNumEnd := b.durableSeqNum','t.highestDurableSeqNum = seqNumEnd','n.seqNum <= t.highestDurableSeqNum']),evidence(pathlib.Path('/home/jhx/oracle_gap/external/deep-swe/tasks/pebble-durability-wait-apis/solution/solution.patch'),['lastSeqNum = uint64(seqNum) + uint64(c) - 1']),evidence(R/'screening/S059/evidence/agent_sources/durability_test.go',['func TestWaitForDurabilityWaits','d.WaitForDurability(100000)','waiter unblocked before sequence number was durable'])]
}
D['S062']={
 'O2':{'semantic_factor_count':1,'factor':'Channel capacity is 1 rather than default256 at both endpoints. Consistent capacity for the connected pair is one semantic condition; the explicit channel ID remains7.'},
 'O3':'Capacity configuration independent of identifier namespace',
 'O4':{'earlier_action':'Step 30 authored a complete independent explicit id, duplicate section using a fresh make_pair and default TubeMultiplexer constructors, then open_channel(channel_id=7), accept, assert both IDs equal7, and check duplicate rejection. Step30 had an unrelated full-script failure marker later; step44 reran the full script successfully, and steps88/113 printed full OK.','relation':'The original section combines a small explicit ID7 with the default capacity256. The setup repair makes the capacity1 while preserving ID7 and the single opened channel, which is legal because capacity bounds the number of live channels, not their numeric IDs.','projection':'The section plus original imports/helper was frozen as a naturally independent validation unit before fresh execution. Its original operations/assertions and duplicate pass/fail markers are preserved, and it owns a new connection pair and closes it. Full original script remains archived.','agent_intent_inferred':False},
 'original_c0_target':'P evaluates 7 > 256 as false and opens the requested ID7; R also opens7. Both satisfy the ID equality and reject the duplicate.',
 'edited_c1_mechanism':'P incorrectly checks channel_id > max_channels and rejects legal ID7 with capacity1 before the original equality assertion. R permits the first channel, reaches the equality assertion and rejects the duplicate. The fixed target stimuli and original validation remain intact.',
 'strict_Def1':{'classification':'Target Bypass','original_target_effects_different_established':False,'reason':'The invalid namespace/capacity guard does not reject the original small ID under c0. The erroneous effect is activated only after lowering capacity; no original defect-related target effect difference is established.'},
 'verdict_semantics':'Original validation is a standalone script, not a pytest-discovered test. Count1 denotes one frozen original validation unit. PASS requires returncode0, duplicate ValueError OK, no FAIL marker, and the preceding explicit ID assert reached. Merely exit0 is insufficient because duplicate rejection uses a printed failure branch.',
 'evidence':[evidence(R/'screening/S062/evidence/trajectory-evidence.txt',['# ---- explicit id, duplicate ----','duplicate ValueError OK','STEP 44','STEP 88','STEP 113','full OK']),evidence(R/'screening/S062/evidence/model.patch',['if channel_id > self._max_channels:','channel id %d exceeds max_channels']),evidence(R/'cases/S062/prepared_candidate_001/selected_unit_original.py',['channel_id=7','assert c.channel_id','duplicate ValueError OK'])]
}
# Diagnostics are supplemental observations under exact c0, not additional candidate cells.
c=R/'cases/S059';rows=[]
for p in sorted((c/'diagnostic_c0/executions').glob('*/result.json')):
 x=json.loads(p.read_text());e=x['execution'];match=re.search(r'PILOT1_C0_DURABLE_STATE highest=(\d+) next_sequence=(\d+) error=(.*)',e['stdout']);assert match
 assert e['returncode']==0 and '--- PASS: TestWaitForDurabilityWaits' in e['stdout']
 snaps=x['production_snapshots'];unchanged=json.loads(snaps['before_build']['stdout'])==json.loads(snaps['final']['stdout']);assert unchanged
 impl=x['implementation'];high=int(match[1]);assert high==({'delivered':11,'reference':10}[impl]);assert int(match[2])==11
 rows.append({'implementation':impl,'repeat':int(p.parent.name.rsplit('_',1)[1]),'actual_test_count':1,'original_test_verdict':'PASS','highest_durable_sequence':high,'next_sequence':11,'error':match[3],'result':str(p),'result_sha256':sha(p),'raw_stdout':e['raw_stdout'],'raw_stderr':e['raw_stderr'],'production_source_unchanged':unchanged})
assert len(rows)==4
save(c/'diagnostic_c0/summary.json',{'schema':'confirmed-gaps-original-context-diagnostic.v1','screen_id':'S059','frozen':str(c/'diagnostic_c0/frozen.json'),'original_context_preserved':True,'added_readonly_observation_only':True,'excluded_from_context_repair_matrix':True,'original_assertions_all_retained_and_passed':True,'observations':rows,'observed_original_effect_difference':'P highest11 versusR highest10 with next_sequence11, stable across two repeats each. Both original waiters remain pending at fixed target100000.','mechanism':'P stores exclusive batch end as inclusive durable frontier; reference subtracts1 for nonempty batch.','limitation':'Diagnostic adds an observation after the unchanged Sync and before the original select; production source, setup, operation inputs and original assertions are unchanged. The diagnostic is supplemental evidence, not the frozen candidate.'})
for s,x in D.items():
 c=R/'cases'/s
 x.update({'schema':'confirmed-gaps-success-postcheck.v1','screen_id':s,'candidate':'candidate_001','matrix_summary':str(c/'matrix_summary.json'),'postcheck_after_success':True,'strict_rule_used':'Strict Def1 requires a defect-related difference in target effects under original c0 that its observation fails to distinguish; merely invoking the named feature is insufficient.','ablation':{'semantic_factors':1,'proper_subset_control':'Original baseline removes the sole factor and passes P/R twice. No separate line-by-line ablation is a distinct semantic-factor removal.','global_minimality_claim':False},'independent_reviews':'Not read; independent review and root adjudication pending'})
 save(c/'O4_mechanism_postcheck.json',x)
 m=json.loads((c/'matrix_summary.json').read_text())
 m['strict_behavioral_masking_confirmed']=False
 m['strict_behavioral_masking_supported_by_execution']=s=='S059'
 m['mechanism_classification_pending_independent_review']=x['strict_Def1']['classification']
 if s=='S059':m['postcheck_diagnostic_summary']=str(c/'diagnostic_c0/summary.json')
 save(c/'matrix_summary.json',m)
 print(s,x['strict_Def1']['classification'])
