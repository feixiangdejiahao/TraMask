from pathlib import Path
import json,re,hashlib
R=Path('/home/jhx/combination_coverage/results/behavioral_masking/20261025_confirmed_gaps_pilot1_n88_r01')

def ref(sid,name,needles,limit=12):
 p=R/'screening'/sid/'evidence'/name;lines=p.read_text().splitlines();found=[];step=None
 for i,l in enumerate(lines,1):
  if l.startswith('STEP '):step=l
  if any(n in l for n in needles):found.append({'line':i,'step':step,'text':l})
 return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'anchors':found[:limit]}

rows={
'S068':{
 'candidate':'candidate_002','O2':{'semantic_factor_count':1,'factor':'Filesystem state: database exists at unchanged CLI path versus absent. Removing SQLite creation and table setup is the realization of one existence condition; table cannot exist when the database file does not.'},
 'O3':'Precreated persistent resource at the target path',
 'O4':{'earlier_action':'Archived step85 defines cli_db_path, creates SQLite file and items table, commits/closes, returns path. Step111 appends the selected enable/disable CLI test, runs26tests and passes; later127 full1078pass.','relation':'The original test inherited a fixture that precreates the path. Removing that fixture construction exposes the same archived verifier failure for a nonexistent target path.','agent_intent_inferred':False},
 'original_c0_target':'CliRunner invokes enable-safe-import then disable-safe-import at an existing database path. Both returnexit0 on P and R. At the selected defect boundary, P Click exists=True admits the path and R also admits it.',
 'edited_c1_mechanism':'P @click.argument(path,type=click.Path(exists=True,...)) rejects absent path with SystemExit2 before enable_safe_import callback executes. R permits database creation and passes original exit0 assertions.',
 'strict_Def1':{'classification':'Target Bypass','original_target_effects_different_established':False,'reason':'The known defect is rejection of a missing path. Under c0 the resource already exists; the rejection precondition is absent and the selected target outcome is identical. Executing the enable/disable feature does not establish defect-related unequal effects under c0.','scope':'Assessment concerns this specific CLI absent-path defect, not the separate bulk UPDATE verifier failure.'},
 'evidence':[ref('S068','trajectory-evidence.txt',['def cli_db_path','def test_cli_enable_disable_safe_import','26 passed']),ref('S068','model.patch',['click.Path(exists=True','def enable_safe_import(path','def disable_safe_import(path'],7)]},
'S074':{
 'candidate':'candidate_001','known_case':'T13','O2':{'semantic_factor_count':1,'factor':'Use cloned compiled instance before extracting the same inc/get functions; add c=c.Clone().'},
 'O3':'Object ownership/clone state of the receiver used by unchanged operations',
 'O4':{'earlier_action':'Original TestCompiledFunctionCallClosureSharing introduced at archived94, inspected again110; constructs a factory with two distinct functions sharing one local n, runsinc twice, then Go inc and get, expecting3. Original95 and125 targeted suites pass. Other original clone tests use a single closure; selected sharing test itself never clones.','relation':'Original shared-cell observation is retained. Clone context is transferred from executed failing official nested-callable clone test, creating the previously untested combination without changing the Tengo source program.','agent_intent_inferred':False},
 'original_c0_target':'Go inc/get callable operations run on the un-cloned compiled instance, returning3 on both implementations.',
 'edited_c1_mechanism':'P Compiled.Clone iterates globals and bindObject with fresh seen maps; binding free variables creates new ObjectPtr independently. Two distinct closures lose shared-cell identity. R uses clone state that memoizes pointers across the object graph. P get returns2 after inc; R get returns3.',
 'strict_Def1':{'classification':'Target Bypass','original_target_effects_different_established':False,'reason':'Selected c0 does not invoke Clone at all, so the clone-specific alias-preservation defect is not activated. Calls exercise the callable feature but show no defect-related unequal target effects under c0.','known_case_reporting':'Known T13 retained and not an independent discovery.'},
 'evidence':[ref('S074','trajectory-evidence.txt',['func TestCompiledFunctionCallClosureSharing','TestCompiledFunctionCallClosureSharing ...','TestCompiledFunctionCallCloneIsolation'],8),ref('S074','model.patch',['free := make([]*ObjectPtr','free[i] = &ObjectPtr','clone.globals[idx] = bindObject','func (c *Compiled) Clone'],8)]},
'S082':{
 'candidate':'candidate_002','O2':{'semantic_factor_count':1,'factor':'Omit only the optional onFinish callback injected by original beforeEach.'},
 'O3':'Optional callback availability provided by a test fixture',
 'O4':{'earlier_action':'Archived125 authors Tap abort test and fixture, then127 revises original to done/catch promise style. Fixture provides process.kill and onStart/onEnd/onFinish noops. The selected original Tap test at final174 is partof273passing tests.','relation':'Official failing abort test constructs runner without start/onFinish. Candidate removes only onFinish assignment while preserving original process stub, both abort operations and all killCount/finished/reporter assertions.','agent_intent_inferred':False},
 'original_c0_target':'Both abort calls resolve with killCount1, finishedtrue and reporter.total0 while onFinish is callable. P unguarded onFinish call succeeds.',
 'edited_c1_mechanism':'P TapProcessTestRunner.abort calls wrapUp with missing onFinish; inherited wrapUp unconditionally invokes this.onFinish and throws TypeError. R guards callback existence in abort and wrapUp. Existing promise catch fails test, without new oracle.',
 'strict_Def1':{'classification':'Target Bypass at selected missing-callback defect boundary','original_target_effects_different_established':False,'reason':'The original fixture supplies the callable whose absence activates the defect, so no defect-related error or target-effect divergence is established under c0. P/R may differ in ancillary callback timing/count or timestamps; those are not evidence that this absence-check defect already produced erroneous target effects. Do not count feature execution alone as strict Behavioral Masking.','limits':'This is a mechanism inference from retained source and the matrix, not a whole-trace semantic-equivalence proof.'},
 'evidence':[ref('S082','trajectory-evidence.txt',["it('is idempotent and wraps up","runner.onFinish = function() {};",'273 passing'],12),ref('S082','model.patch',['this.wrapUp();','this.onFinish();','abort()'],14)]},
'S085':{
 'candidate':'candidate_001','O2':{'semantic_factor_count':1,'factor':'One threshold parameter150→350, consistently in both shard configurations. Two changed lines are not two semantic factors.'},
 'O3':'Feature threshold selecting a different valid algorithm branch',
 'O4':{'earlier_action':'Archived108 authors selected isolation test with2shards, four unchanged fixturefiles/history400,300,200,100 and threshold150. It explicitly comments3slow>=shardcount and asserts[1] versus[2,3,4]. Archived112 passes8test; final149 passes19.','relation':'Threshold350 yields1slow<2shards while the compliant assignment remains exactly[1] versus[2,3,4]. No fixture source, history, targetshards or assertion change.','agent_intent_inferred':False},
 'original_c0_target':'Threshold150 selects slowcount>=shardcount branch. Both implementations produce firstshard[1], second[2,3,4].',
 'edited_c1_mechanism':'Threshold350 selects slowcount<shardcount. P distributes remaining files over allshards rather than remaining unreserved shards and appends2.test.js to the reserved firstshard. R reserves the firstshard and puts allremaining into second, preserving original expectedsets.',
 'strict_Def1':{'classification':'Target Bypass','original_target_effects_different_established':False,'reason':'Original condition selects the other branch, which meets the selected assignment contract. The faulty remaining-shard distribution branch is activated only by c1; original feature coverage alone is insufficient for strict masking.','legitimacy_boundary':'Whether sequence configuration is setup rather than the target stimulus is retained for independent semantic adjudication. Execution success does not resolve that boundary.'},
 'evidence':[ref('S085','trajectory-evidence.txt',["test('isolateSlowThreshold isolates",'slow files (1, 2, 3) >= shard count','19 passed'],8),ref('S085','model.patch',['if (slow.length < shardCount)','const remainingAssignment = shardByStrategy','newAssignment[index].push(...group)'],5)]}
}
for sid,d in rows.items():
 d.update(schema='confirmed-gaps-success-postcheck.v1',screen_id=sid,matrix_summary=str(R/'cases'/sid/'matrix_summary.json'),postcheck_after_success=True,strict_rule_used='Strict Def1 requires a defect-related difference in target effects under original c0 that its observation fails to distinguish; merely invoking the named feature is insufficient.',independent_reviews='Not read; root adjudication pending')
 (R/'cases'/sid/'O4_mechanism_postcheck.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
 print(sid,d['strict_Def1']['classification'])
