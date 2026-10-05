"""Join frozen execution receipts with source-first manual validity judgments."""
from collections import Counter
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_trajectory_gap_pilot import load_protocol,read,frozen,verify,write
BASE=ROOT/'results/trajectory_gap_pilot_20261005'
CASES=['N01','N03','N04','N06','N08','N09','P2','P7']

def summarize(run):
    nfile=ROOT/('research/trajectory_gap_pilot_generation_source_audit_n_20261005.json' if run=='generation_v2' else 'research/trajectory_gap_pilot_generation_source_audit_n_format_repair_20261005.json')
    audit=read(nfile);judgments={(x['case'],x['arm'],x['rank']):(x['semantic_status'],x['target_mechanism_match'],frozen(nfile)) for x in audit['candidates']}
    if run=='generation_v2':
        pf=ROOT/'research/trajectory_gap_pilot_generation_source_audit_p_20261005.json'
        judgments.update({('P7','source_only',1):('invalid',False,frozen(pf)),('P7','source_and_trajectory',1):('supported',False,frozen(pf))})
    else:
        pf=ROOT/'research/trajectory_gap_pilot_generation_format_repair_source_audit_p_20261005.json'
        for x in read(pf)['source_judgments']:
            s=x['judgment'];s='supported' if s.startswith('supported') else ('unknown' if s=='uncertain' else s)
            judgments[x['case'],x['arm'],x['raw_rank']]=(s,x['case']=='P7' and x['arm']=='source_only',frozen(pf))
    generation=read(BASE/run/'generation_summary.json');candidates=[];seen=set()
    for suffix in ['', '_normalized','_semicolon']:
        folder=BASE/(run+suffix);p=load_protocol(folder)
        verify(read(folder/'generation_summary_seal.json'))
        g=read(folder/'generation_summary.json')
        for item in g['results']:
            verify(item['decoded']);verify(item['manifest'])
            for index,c in enumerate(read(item['decoded']['path'])['candidates'],1):
                key=item['case'],item['arm'],c['order'][0]
                assert key not in seen;seen.add(key)
                target=folder/'cases'/item['case']/item['arm']/f'candidate_{index:02d}'
                nr=read(target/'native_result.json');assert read(nr['program']['path'])==c;verify(nr['program'])
                for o in nr['outcomes']:
                    verify(o['receipt']);actual=read(o['receipt']['path']);native=actual['native']
                    assert actual['transport']['status']=='matched' and native['controls']['status']=='all_source_controls_passed' and not native['parser_errors']
                    assert native==o['native'];verify(native['runs'])
                validity,match,source_judgment=judgments[key]
                failed=nr['repeated_controlled_failure']
                assert failed or all(t['status']=='pass' for t in nr['outcomes'][0]['native']['tests'])
                candidates.append(dict(case=key[0],arm=key[1],original_rank=key[2],strict_accepted=not suffix,
                    source_validity=validity,target_mechanism_match=match,repeated_controlled_failure=failed,
                    qualified_target_detection=failed and validity=='supported' and match,
                    qualified_other_defect=failed and validity=='supported' and not match,
                    native_groups=len(nr['outcomes']),source_audit=source_judgment,native_result=frozen(target/'native_result.json')))
    arms=[]
    for arm in ['source_only','source_and_trajectory']:
        rows=[x for x in candidates if x['arm']==arm]
        gr=[x for x in generation['results'] if x['arm']==arm]
        arms.append(dict(arm=arm,requests=8,strict_candidates=sum(x['strict_accepted'] for x in rows),effective_candidates=len(rows),
            semantic_status_counts=dict(Counter(x['source_validity'] for x in rows)),
            pass_count=sum(not x['repeated_controlled_failure'] for x in rows),repeated_fail_count=sum(x['repeated_controlled_failure'] for x in rows),
            qualified_target_cases=sorted({x['case'] for x in rows if x['qualified_target_detection']}),
            qualified_other_defect_cases=sorted({x['case'] for x in rows if x['qualified_other_defect']}),
            strict_qualified_target_cases=sorted({x['case'] for x in rows if x['strict_accepted'] and x['qualified_target_detection']}),
            unknown_requests=sum(x['status']=='unknown' for x in gr)))
    return dict(run=run,generation=frozen(BASE/run/'generation_summary.json'),provider_calls=generation['provider_calls'],measured_tokens=generation['measured_tokens'],usage_missing=generation['usage_missing'],
        candidates=candidates,arms=arms,native_groups=sum(x['native_groups'] for x in candidates),
        all_executable_candidates_evaluated=True,all_original_controls_passed=True,semantics_unchanged_by_format_normalization=True)

def main():
    rounds=[summarize(r) for r in ['generation_v2','generation_format_repair']]
    extraction=read(ROOT/'research/trajectory_gap_pilot_extraction_manual_evaluation_20261005.json')
    summary=dict(status='completed',created_utc=datetime.now(timezone.utc).isoformat(),task='Two independent trajectory-gap pilot experiments',
        part1=dict(extraction=frozen(ROOT/'research/trajectory_gap_pilot_extraction_20261005.json'),manual_evaluation=frozen(ROOT/'research/trajectory_gap_pilot_extraction_manual_evaluation_20261005.json'),signals=9308,totals=extraction['totals']),
        part2=dict(cases=CASES,primary_run='generation_format_repair',rounds=rounds,provider_calls=sum(r['provider_calls'] for r in rounds),measured_tokens=sum(r['measured_tokens'] for r in rounds),usage_missing=sum(r['usage_missing'] for r in rounds),native_groups=sum(r['native_groups'] for r in rounds),unique_generated_candidates=sum(len(r['candidates']) for r in rounds)),
        boundaries=['All8 cases were development-seen and manually selected; denominator8 is a selected-hypothesis yield, not population recall.',
        'Part2 inputs were selected by humans independently of Part1 outputs. This is not an end-to-end automatic result.',
        'Complete-test semantic validity is required. Do not count a valid failing prefix when a later assertion has no contract support.',
        'Formats were repaired uniformly after observed transport problems. Both original strict and repaired results remain available. No assertion was changed.',
        'No model-driven semantic gate was used. Human source-first review controls reported false alarms; this is not an automatic zero-FPR guarantee.',
        'Two prompt variants are not independent identical-condition repetitions. Do not union best cases across rounds or claim significance.',
        'Prior best and closed ten-hour search remain separate.'],
        summarizer=frozen(__file__),integrity=frozen(ROOT/'research/trajectory_gap_pilot_integrity_20261005.json'))
    write(ROOT/'research/trajectory_gap_pilot_results_20261005.json',summary)
    print(json.dumps({'part1':summary['part1']['totals'],'part2_totals':{k:v for k,v in summary['part2'].items() if k not in ['cases','rounds']},'rounds':[dict(run=r['run'],arms=r['arms']) for r in rounds]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
