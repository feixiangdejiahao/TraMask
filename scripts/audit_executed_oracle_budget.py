"""Static oracle-budget reallocation after recorded execution and source controls.

Compare current impact selection with and without the execution gate. The gate
never regards not-run/compile failure as an invalid program or a semantic label.
No model or repository execution is performed; all original inputs are retained.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search.impact_selection import select


POLICY=dict(version='executed-source-control-oracle-budget-v1',budget=16,
    admitted='recorded executed=True, at least one native pass/fail outcome, and control_and_seed_valid=True',
    outcome_polarity='pass and fail treated identically',
    unknown='missing/not_run/compile errors remain pending; never labelled invalid',
    source_pool='same saved prepared/candidates.json before semantic revisions',
    comparison='recorded prior selection, current impact on all original inputs, current impact on executed/control-valid subset',
    rounds='independent per completed round; no claim of campaign-wide backlog equivalence',
    forbidden=['evaluation labels','historical oracle cache','known target IDs','test failure message semantics'])
CODE_FILES=['scripts/audit_executed_oracle_budget.py','relation_search/impact_selection.py',
    'relation_search/semantic_selection.py','prototypes/singleton_oracle_slots.py',
    'prototypes/assertion_operand_guard.py','anchor_retrieval/graph.py','anchor_retrieval/syntax.py',
    'anchor_retrieval/index.py','relational_gap/frontend.py','relation_search/instrument.py',
    'relation_search/feedback.py','relation_search/frontier.py','combination_testing/test_reports.py']


def read(path):return json.loads(Path(path).read_text())
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def execution_gate(candidates,feedback):
    rows=feedback.get('current_results',[])
    results={r['candidate_id']:r for r in rows}
    if len(results)!=len(rows):
        raise ValueError('duplicate candidate execution record')
    records=[]
    for candidate in candidates:
        row=results.get(candidate['id'])
        statuses=sorted({status for outcome in (row or {}).get('candidate_outcomes',[])
                         for status in outcome.get('statuses',[]) if outcome.get('executed') is True})
        if row is None:
            category='execution_unknown';reason='no_current_native_outcome'
        elif row.get('executed') is not True or not set(statuses)&{'pass','fail'}:
            category='execution_unknown';reason='no_completed_pass_or_fail_testcase'
        elif row.get('control_and_seed_valid') is not True:
            category='executed_control_unconfirmed';reason='source_control_not_confirmed'
        else:
            category='executed_control_valid';reason='recorded_execution_and_source_control'
        records.append(dict(id=candidate['id'],category=category,reason=reason,
            source_control_valid=(row or {}).get('control_and_seed_valid'),native_statuses=statuses,
            executed=(row or {}).get('executed'),
            report_errors=[error for outcome in (row or {}).get('candidate_outcomes',[])
                           for error in outcome.get('report_errors',[])]))
    admitted={r['id'] for r in records if r['category']=='executed_control_valid'}
    return dict(policy=POLICY,records=records,counts=dict(Counter(r['category'] for r in records)),
        admitted=[c for c in candidates if c['id'] in admitted],
        retained_pending=[c for c in candidates if c['id'] not in admitted])


def run(campaign,output,*,inventory_path=None,rebuild_feedback=False):
    output.mkdir(parents=True,exist_ok=False)
    code={name:digest(ROOT/name) for name in CODE_FILES}
    inventory=[]
    if inventory_path is not None:
        frozen=read(inventory_path)
        if Path(frozen['campaign']).resolve()!=campaign.resolve():
            raise ValueError('frozen inventory belongs to a different campaign')
        inventory=frozen['inventory']
    else:
        for feedback in sorted(campaign.glob('*/round_*/feedback.json')):
            prepared=feedback.parent/'prepared';semantic=feedback.parent/'semantic'
            paths={name:prepared/name for name in ('corpus.json','frontend.json','candidates.json')}
            paths.update(feedback=feedback,recorded_selection=semantic/'semantic_selection.json')
            inventory.append(dict(case=feedback.parent.parent.name,round=feedback.parent.name,
                paths={name:str(path.resolve()) for name,path in paths.items()},
                files_sha256={name:digest(path) for name,path in paths.items()}))
    if rebuild_feedback and any(item['round']!='round_000' for item in inventory):
        raise ValueError('feedback rebuild currently requires independent first rounds')
    for item in inventory:
        if any(digest(path)!=item['files_sha256'][name] for name,path in item['paths'].items()):
            raise ValueError('frozen inventory material changed before audit')
    write(output/'protocol.json',dict(policy=POLICY,created_at=datetime.now(timezone.utc).isoformat(),
        campaign=str(campaign.resolve()),inventory=inventory,current_code_sha256=code,
        frozen_inventory_sha256=digest(inventory_path) if inventory_path else None,
        feedback_basis='current matcher replays original named reports' if rebuild_feedback else 'original feedback metadata',
        campaign_configuration_sha256=digest(campaign/'configuration.json'),
        provider_calls=0,subject_executions=0,interpretation='static presentation opportunity, not oracle correctness'))
    for name in CODE_FILES:
        destination=output/'code_snapshot'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes((ROOT/name).read_bytes())
    summaries=[]
    for item in inventory:
        p={name:Path(path) for name,path in item['paths'].items()}
        corpus=read(p['corpus.json']);front=read(p['frontend.json']);candidates=read(p['candidates.json'])['candidates']
        feedback=read(p['feedback'])
        if feedback['source_identity']['corpus.json']!=item['files_sha256']['corpus.json']:
            raise ValueError('feedback source corpus does not match candidates')
        if rebuild_feedback:
            from relation_search.feedback import collect
            feedback=collect(Path(feedback['checkpoint_inputs']['execution']))
            write(output/item['case']/item['round']/'replayed_feedback.json',feedback)
        gate=execution_gate(candidates,feedback)
        before=select(corpus,front,candidates,budget=16)
        after=select(corpus,front,gate['admitted'],budget=16)
        recorded=read(p['recorded_selection'])
        result=dict(case=item['case'],round=item['round'],policy=POLICY,gate=gate,
            original_candidates=candidates,recorded_offered_ids=recorded.get('offered_ids',[]),
            current_unfiltered=before,current_execution_gated=after)
        write(output/item['case']/item['round']/'result.json',result)
        summaries.append(dict(case=item['case'],round=item['round'],language=corpus['language'],
            original_inputs=len(candidates),gate_counts=gate['counts'],
            original_offered_count=len(recorded.get('offered_ids',[])),
            current_unfiltered_selected=len(before['selected']),current_gated_selected=len(after['selected']),
            changed_selected_ids=len({c['id'] for c in after['selected']}-{c['id'] for c in before['selected']})))
        if any(digest(path)!=item['files_sha256'][name] for name,path in p.items()):
            raise ValueError('completed round inputs changed during audit')
    summary=dict(rounds=summaries,totals=dict(rounds=len(summaries),
        original_inputs=sum(r['original_inputs'] for r in summaries),
        current_unfiltered_selected=sum(r['current_unfiltered_selected'] for r in summaries),
        current_gated_selected=sum(r['current_gated_selected'] for r in summaries),
        changed_selected_ids=sum(r['changed_selected_ids'] for r in summaries),
        gate_counts=dict(sum((Counter(r['gate_counts']) for r in summaries),Counter()))))
    write(output/'summary.json',summary)
    if {name:digest(ROOT/name) for name in CODE_FILES}!=code:
        raise ValueError('algorithm source changed during audit; results unsealed')
    write(output/'seal.json',dict(files_sha256={str(p.relative_to(output)):digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--campaign',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--frozen-inventory',type=Path)
    parser.add_argument('--rebuild-feedback',action='store_true')
    args=parser.parse_args();print(json.dumps(run(args.campaign,args.output,
        inventory_path=args.frozen_inventory,rebuild_feedback=args.rebuild_feedback),sort_keys=True))
