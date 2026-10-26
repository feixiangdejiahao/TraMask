"""Neutral, receipt-bound manual-review packets for HF001 evaluator completion."""
import hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from tramask_pilot.corpus import receipt,read
from tramask_rerun.study import RUN,now,write_new
OUT=RUN/'neutral_hf001_evaluator_review_v01'
assert not OUT.exists();OUT.mkdir()
index=[];mapping=[]
for rep in [1,2]:
 cell=RUN/f'runs/HF001/track_b/M1/repeat_{rep:02d}'
 ex=cell/'candidate_execution/rank_01';qdir=ex/'evaluator_comparator_v01'
 plan=read(qdir/'plan.json');key='pair_'+hashlib.sha256(receipt(qdir/'plan.json')['sha256'].encode()).hexdigest()[:12]
 dest=OUT/'packets'/key;dest.mkdir(parents=True)
 shutil.copyfile(RUN/'inputs/HF001/instruction.md',dest/'issue.txt')
 code=[];sources=plan['staged']['arms']
 for i,path in enumerate(sorted(sources['p_original']['full_text'])):
  row={'subject_path':path}
  for arm in ['p_original','p_candidate','q_original','q_candidate']:
   data=sources[arm]['full_text'][path].encode();fp=dest/'code'/f'{i:03d}_{arm}.txt';fp.parent.mkdir(exist_ok=True);fp.write_bytes(data);row[arm]=receipt(fp)
  code.append(row)
 executions=[];original_refs=[]
 for summary_path in [ex/'summary.json',qdir/'summary.json']:
  summary=read(summary_path);original_refs.append(receipt(summary_path))
  for run in summary['runs']:
   rr=run['result'];assert receipt(rr['path'])==rr;result=read(rr['path']);e=result['execution'];row={k:e.get(k) for k in ['status','command','working_directory','returncode','timed_out','transport_error','execution_error','elapsed_seconds','checkpoint_image_id','container','environment_overlay','exit_status_is_not_test_verdict']}
   row.update(arm=run['arm'],repeat=run['repeat'],runtime_status=result['status'],builds=result['builds'])
   logdir=dest/'logs'/f"{run['arm']}_{run['repeat']:02d}";logdir.mkdir(parents=True)
   for channel in ['stdout','stderr']:
    raw=Path(e['raw_'+channel]).read_bytes();assert hashlib.sha256(raw).hexdigest()==e[channel+'_sha256'];assert len(raw)==e[channel+'_bytes']
    fp=logdir/(channel+'.bin');fp.write_bytes(raw);row[channel]=receipt(fp)
   fp=logdir/'execution.json';write_new(fp,row);executions.append(receipt(fp));original_refs.append(rr)
 q=read(qdir/'fixed_evaluator_Q.json');submitted=read(cell/'stage_02/canonical_candidates.json')['candidates'][0]
 packet={'pair_id':key,'created_at':now(),'issue':receipt(dest/'issue.txt'),'target':read(cell/'stage_01/planning.json')['target'],'original_command':sources['p_original']['command'],'test_edits':submitted['edits'],'Q_edits':q['edits'],'code':code,'executions':executions,'scope':'Raw code and exact recorded outcomes only. P/Q names do not imply correctness. Test verdict must be read from runner output, not the pipeline exit code. Review semantic E3/E7/E9 separately; do not vote on masking or infer a new defect from a mutation kill. This comparator was constructed after test edits froze; no generation method identity, automated scientific label or earlier reviewer answer is supplied.'}
 write_new(dest/'packet.json',packet);index.append({'pair_id':key,'packet':receipt(dest/'packet.json')});mapping.append({'pair_id':key,'case_id':'HF001','method':'M1','repeat':rep,'cell':str(cell),'source_execution_receipts':original_refs,'Q':receipt(qdir/'fixed_evaluator_Q.json'),'plan':receipt(qdir/'plan.json'),'candidate':receipt(cell/'stage_02/canonical_candidates.json')})
write_new(OUT/'index.json',index)
write_new(OUT/'review_protocol.json',{'version':'tramask.hf001-evaluator-semantic-review.v1','assignments':[x['pair_id'] for x in index],'allowed_read_roots':[str(OUT/'packets')],'criteria':{'E3':'Relevant isolated executable Q: inspect exact mechanism change and recorded execution; assertion failures on relevant behavior are distinct from syntax/import/build failures.','E7':'Candidate changes legal setup only, retaining target operation, input, original observation and assertions. Claims in a generator response are not evidence.','E9':'Each original/augmented test assertion and P/Q outcome direction must be supported by the issue/contract; do not presume P correct. Scope is these assertions, not proof of all issue requirements.'},'output_contract':{'pair_id':'registered ID','reviewer_id':'A or B','E3':{'status':'pass|fail|unresolved','rationale':'concise evidence-based reason','evidence':['packet-local path plus source line or log detail']},'E7':'same structure','E9':'same structure','test_outcomes':'per-arm actual verdict/count across three runs, with evidence','uncertainties':[]},'blindness':'Fresh fork-none Codex threads, separate output directories. Filesystem exclusion is instruction enforced, not ACL isolation. Do not inspect another reviewer, private root mapping, prior reports, prior reviews or other experiments.','timing':'Each reviewer records start/end UTC and elapsed wall seconds; token usage unknown unless actually available; no human-labor claim.','scientific_label':'Reviewers do not emit masking/repair votes; root derives endpoints from evidence.'})
write_new(RUN/'neutral_hf001_evaluator_review_mapping_v01.json',mapping)
print(json.dumps({'root':str(OUT),'pairs':len(index),'new_provider_calls':0}))
