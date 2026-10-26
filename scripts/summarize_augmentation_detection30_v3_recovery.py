"""Offline semantic-review accounting for the uniform final-call supplement."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from augmentation.pipeline import write_json
from scripts.recover_augmentation_detection30_v3_decisions import RUN,OUT


def read(p):
    return json.loads(Path(p).read_text())


def main():
    protocol=read(OUT/'protocol.json')
    supplemental=[read(p) for p in sorted(OUT.glob('cases/*/*/result.json'))]
    supplement_reviews=[read(p) for p in sorted((OUT/'evaluation/claims').glob('*.json'))]
    original=read(RUN/'evaluation/inventory.json')
    original_reviews=[read(p) for p in sorted((RUN/'evaluation/claims').glob('*.json'))]
    reviews=original_reviews+supplement_reviews
    by_review={v['id']:v for v in supplement_reviews}
    override={v['id']:v for v in supplemental}
    final=[override.get(v['id'],v) for v in original]
    pending=[v['id'] for v in supplemental if v['decision']=='gap' and v['id'] not in by_review]
    targets=read(RUN/'evaluation/target_review.json')['targets']
    found={t for v in reviews if v['verdict']=='correct' for t in v.get('reference_targets',[])}
    changed_requests=[]
    primary_changed=[]
    for row in protocol['eligible']:
        p=OUT/'cases'/row['case']/row['candidate']/'round1/request.json'
        if p.exists():
            old=read(row['request']['path']);new=read(p)
            assert new['max_tokens']==32768
            old.pop('max_tokens');new.pop('max_tokens')
            if old!=new:changed_requests.append(str(p))
        expected=row['primary_result']
        if hashlib.sha256(Path(expected['path']).read_bytes()).hexdigest()!=expected['sha256']:
            primary_changed.append(expected['path'])
    outcomes=Counter(v['decision'] for v in final)
    summary={'status':'complete' if len(supplemental)==len(protocol['eligible']) and not pending else 'in_progress',
      'eligible':len(protocol['eligible']),'completed':len(supplemental),'unreviewed_claims':pending,
      'supplement_decisions':dict(Counter(v['decision'] for v in supplemental)),
      'supplement_stop_reasons':dict(Counter(v['stop_reason'] for v in supplemental)),
      'external_model_calls':sum(v['external_model_calls'] for v in supplemental),
      'charged_tokens':sum((v.get('usage') or {}).get('total_tokens',0) for v in supplemental),
      'combined_model_decisions':dict(outcomes),
      'combined_claim_review':dict(Counter(v['verdict'] for v in reviews)),
      'combined_correct_task_ids':sorted({v['case'] for v in reviews if v['verdict']=='correct'}),
      'qualified_core_claims':[{'id':v['id'],'case':v['case'],'counted_observation':v['counted_observation'],'qualification':v['qualification']}
                               for v in reviews if v['verdict']=='correct' and v.get('counted_observation')],
      'correct_task_ids_excluding_qualified_claims':sorted({v['case'] for v in reviews if v['verdict']=='correct' and not v.get('counted_observation')}),
      'combined_false_positive_task_ids':sorted({v['case'] for v in reviews if v['verdict']=='false_positive'}),
      'primary_targets':23,'primary_detected':sum(v['set']=='primary23' and v['id'] in found for v in targets),
      'primary_missed':sum(v['set']=='primary23' and v['id'] not in found for v in targets),
      'expanded_targets':24,'expanded_detected':sum(v['id'] in found for v in targets),
      'expanded_missed':sum(v['id'] not in found for v in targets),
      'new_discoveries':[{'id':v['new_target_id'],'case':v['case'],'claim':v['id']} for v in reviews if v['verdict']=='correct' and v.get('new_target_id')],
      'request_changes_other_than_max_tokens':changed_requests,
      'primary_result_changes':primary_changed,
      'test_generation_calls':0,'test_execution_calls':0,
      'review_mode':'Codex static semantic review; not independent human validation.',
      'interpretation':'Supplemental retry and higher output allowance. Original primary results remain frozen; no attribution to one factor.'}
    write_json(OUT/'summary.json',summary)
    write_json(OUT/'combined_inventory.json',final)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
