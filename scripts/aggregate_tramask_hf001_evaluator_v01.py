"""Derive a narrow endpoint supplement from actual HF001 runs and two reviews."""
from pathlib import Path
from collections import Counter
import csv,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from tramask_pilot.corpus import read,receipt
from tramask_rerun.study import RUN,now,write_new
from tramask_rerun.metrics import reviewer_agreement
BASE=RUN/'neutral_hf001_evaluator_review_v01'
OUT=RUN/'hf001_evaluator_completion_v01'

def checked(r):
    assert receipt(r['path'])==r
    return read(r['path'])

def run_record(r):
    data=checked(r['result']);e=data['execution']
    logs={}
    for channel in ['stdout','stderr']:
        p=Path(e['raw_'+channel]);raw=p.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==e[channel+'_sha256'] and len(raw)==e[channel+'_bytes']
        logs[channel]=receipt(p)
    text=Path(logs['stdout']['path']).read_text()+Path(logs['stderr']['path']).read_text()
    # Explicit original Jest summary only; shell exit status is not the verdict.
    counts=re.findall(r'^Tests:\s+(\d+)\s+(passed|failed),\s+(\d+)\s+total\s*$',text,re.M)
    assert len(counts)==1,('ambiguous_or_missing_jest_summary',r['result'])
    number,verdict,total=counts[0];assert int(number)==int(total)==1
    assert re.search(r'^(?:PASS|FAIL) __tests__/apply\.test\.ts\s*$',text,re.M)
    assert data['status']=='completed' and e['status']=='completed' and not e['timed_out'] and not e['transport_error'] and not e['execution_error']
    return {'arm':r['arm'],'repeat':r['repeat'],'result':r['result'],'logs':logs,
        'runner':'Jest','test_identity':'__tests__/apply.test.ts::direct apply','test_verdict':verdict,
        'tests':1,'shell_returncode':e['returncode'],'shell_status_used_as_verdict':False,
        'container':e['container'],'checkpoint_image_id':e['checkpoint_image_id'],'command':e['command'],
        'elapsed_seconds':e['elapsed_seconds'],'build_commands':len(data['builds'])}

if __name__=='__main__':
    if OUT.exists():raise FileExistsError(OUT)
    mappings=read(RUN/'neutral_hf001_evaluator_review_mapping_v01.json')
    records=[];agreements={k:[] for k in ['E3','E7','E9']};all_runs=[]
    for m in mappings:
        pid=m['pair_id'];reviews={label:read(BASE/f'reviewer_{label}/{pid}.json') for label in ['A','B']}
        decisions={}
        for gate in agreements:
            a,b=(reviews[label][gate]['status'] for label in ['A','B'])
            assert a in ['pass','fail','unresolved'] and b in ['pass','fail','unresolved']
            agreements[gate].append({'reviewer_a':a,'reviewer_b':b})
            if a!=b:raise ValueError('Third independent adjudication required: '+pid+' '+gate)
            decisions[gate]={'status':a,'resolution':'two_independent_reviewer_agreement',
                'evidence':[receipt(BASE/f'reviewer_{label}/{pid}.json') for label in ['A','B']]}
        for label,review in reviews.items():assert review['pair_id']==pid and review['reviewer_id']==label
        cell=Path(m['cell']);ex=cell/'candidate_execution/rank_01';qdir=ex/'evaluator_comparator_v01'
        psummary=read(ex/'summary.json');qsummary=read(qdir/'summary.json')
        runs=[run_record(r) for s in [psummary,qsummary] for r in s['runs']]
        assert len(runs)==12 and len({r['container'] for r in runs})==12
        assert len({r['checkpoint_image_id'] for r in runs})==1
        outcomes={arm:[r['test_verdict'] for r in runs if r['arm']==arm] for arm in ['p_original','p_candidate','q_original','q_candidate']}
        assert outcomes=={'p_original':['passed']*3,'p_candidate':['passed']*3,'q_original':['failed']*3,'q_candidate':['failed']*3}
        originals_differ=outcomes['p_original'][0]!=outcomes['q_original'][0]
        record={**{k:m[k] for k in ['pair_id','case_id','method','repeat','cell']},'checks':decisions,
            'review_receipts':[receipt(BASE/f'reviewer_{label}/{pid}.json') for label in ['A','B']],
            'Q':m['Q'],'plan':m['plan'],'original_P_results':receipt(ex/'summary.json'),'new_Q_results':receipt(qdir/'summary.json'),
            'runtime_records':runs,'observed_outcomes':outcomes,'R1_paired_executable':'pass' if decisions['E3']['status']=='pass' else 'unresolved',
            'original_test_distinguishes_qualified_Q':originals_differ and decisions['E3']['status']=='pass',
            'E6_original_test_insensitivity':{'status':'fail' if originals_differ and decisions['E3']['status']=='pass' else 'unresolved','reason':'Original P and Q tests already differ at the original b-trailing-spaces assertion; the same difference remains after the frozen import edit.'},
            'additional_discrimination_over_original_test_observed':False,'strict_R2_established':False,
            'whole_oracle_qualified_improvement_established':False,'newly_exposed_real_P_defect_established':False,
            'classification':'original_test_already_distinguishes_evaluation_Q' if originals_differ and decisions['E3']['status']=='pass' else 'unresolved_counterfactual_qualification',
            'scope_limit':'One post-freeze evaluator Q, not an exhaustive proof of all possible context factors. This is the Track B selected pair, not the distinct Pilot1 fixed HF001 reference pair. No new local-effect probe or masking-positive inference.'}
        records.append(record);all_runs.extend(runs)
    assert len(records)==2 and len({r['container'] for r in all_runs})==24
    ledger=read(RUN/'provider_budget.json');assert ledger['limit_tokens']==10000000 and sum(v['charged_tokens'] for v in ledger['calls'].values())==9968405
    source_export=read(RUN/'runs/HF001/evaluator_review_sources_v01/export/result.json')
    assert source_export['status']=='complete' and len(source_export['files'])==2
    result={'schema':'tramask.hf001-evaluator-completion.v1','created_at':now(),'status':'evaluated_with_independent_semantic_reviews','pairs':records,
        'additional_review_agreement':{gate:reviewer_agreement(rows) for gate,rows in agreements.items()},
        'review_reliability_scope':'Two candidate instances from one issue; do not count as two independent issues. Constant equal labels give undefined kappa; original initial-review statistics remain unchanged.',
        'cost':{'new_provider_calls':0,'new_provider_tokens':0,'new_subject_commands':12,'linked_preexisting_P_commands':12,
            'new_build_commands':0,'new_Q_subject_seconds':sum(r['elapsed_seconds'] for r in all_runs if r['arm'].startswith('q_')),
            'new_readonly_file_export_operations':1,'new_exported_files':2},
        'source_export':receipt(RUN/'runs/HF001/evaluator_review_sources_v01/export/result.json'),
        'review_launches':receipt(BASE/'thread_launches.json'),'code':receipt(Path(__file__)),
        'frozen_evaluation_protocol':receipt(RUN/'amendments/018_hf001_postfreeze_evaluator.json'),
        'original_semantic_aggregation_retained':receipt(RUN/'evidence_aggregation_v01/semantic_reviews.json'),
        'provider_ledger_unchanged':receipt(RUN/'provider_budget.json'),
        'full_pilot_objective_complete':False}
    write_new(OUT/'summary.json',result)
    print(json.dumps({'path':str(OUT/'summary.json'),'pairs':len(records),'new_subject_commands':12,'new_provider_tokens':0,'classifications':[r['classification'] for r in records]}))
