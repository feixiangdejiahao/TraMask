"""Source-only comparison of ordinary slots and helper expected-argument slots.

The entire original 4,502-candidate inventory is fixed by the paired protocol.
Only Go members receive the helper extension. No oracle answer or outcome is
read; source eligibility never implies a correct expected value or a gap hit.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from prototypes.singleton_oracle_slots import assertion_inventory
from relation_search.instrument import _program_edits
from relation_search.oracle import program_candidate

FILES = ['scripts/census_helper_expected_slots.py','tests/test_helper_expected_slots_census.py',
    'prototypes/helper_expected_slots.py','tests/test_helper_expected_slots.py',
    'prototypes/singleton_oracle_slots.py','prototypes/go_assertion_helper.py',
    'tests/test_go_assertion_helper.py','prototypes/go_arity_guard.py','prototypes/assertion_operand_guard.py',
    'prototypes/source_failure_evidence.py','prototypes/local_helper_evidence.py',
    'tests/test_source_failure_evidence.py','tests/test_local_helper_evidence.py',
    'prototypes/finite_oracle_templates.py','tests/test_finite_oracle_templates.py',
    'relation_search/oracle.py','relation_search/instrument.py','relation_search/oracle_evidence.py',
    'anchor_retrieval/syntax.py','anchor_retrieval/index.py','anchor_retrieval/graph.py',
    'generic_composition/corpus.py','relational_gap/frontend.py']


def read(path):return json.loads(Path(path).read_text())
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def sha_order(identifier):
    return hashlib.sha256(identifier.encode()).hexdigest(),identifier


def compare_slots(candidate_id,ordinary,extended=None):
    """Rows, not module-supplied counts, determine the census denominator."""
    baseline=sum(bool(row['editable']) for row in ordinary)
    result=dict(candidate_id=candidate_id,ordinary_assertions=len(ordinary),
        ordinary_editable=baseline,ordinary_readonly=len(ordinary)-baseline,
        baseline_eligible=bool(baseline),helper_calls=0,helper_editable=0,
        extended_editable=baseline,extension_only_eligible=False,
        extended_eligible=bool(baseline),extended_status='not_go',unknown_reasons={})
    if extended is None:return result
    rows=extended
    helper=[row for row in rows if row['kind']=='helper_expected_call']
    other=[row for row in rows if row['kind']=='ordinary_assertion']
    if len(helper)+len(other)!=len(rows):raise ValueError('unrecognized slot inventory kind')
    helper_editable=sum(bool(row['editable']) for row in helper)
    result.update(helper_calls=len(helper),helper_editable=helper_editable,
        extended_editable=sum(bool(row['editable']) for row in rows),
        extended_eligible=any(row['editable'] for row in rows),
        extended_status='source_inventory',
        extension_only_eligible=not baseline and helper_editable>0,
        extended_ordinary_assertions=len(other),extended_ordinary_editable=sum(bool(row['editable']) for row in other),
        unknown_reasons=dict(Counter(row['reason'] for row in rows if not row['editable'] and row.get('reason'))))
    # Do not silently call a source-interface regression an extension benefit.
    result['ordinary_count_changed']=len(other)!=len(ordinary)
    result['ordinary_editable_changed']=result['extended_ordinary_editable']!=baseline
    return result


def select_source_members(rows,limit=2):
    """One frozen diagnostic rule, same across cases; no target-directed choice."""
    ordered=sorted(rows,key=lambda row:sha_order(row['candidate_id']))
    new=[row for row in ordered if row['helper_editable']>0]
    pool=new if new else [row for row in ordered if row['extended_eligible']]
    return dict(rule='SHA(candidate.id) first from helper-editable, else any editable',
        purpose='source-selected diagnostic sample, not an unbiased gap-detection cohort',
        member_limit=limit,selection_class='helper_editable' if new else 'ordinary_fallback',
        candidate_ids=[row['candidate_id'] for row in pool[:limit]],
        selected_candidates=len(pool[:limit]),available_candidates=len(pool))


def run(paired,output,limit=2):
    from prototypes.helper_expected_slots import inventory
    from prototypes.go_assertion_helper import HelperIndex
    protocol,ready=read(paired/'protocol.json'),read(paired/'ready.json')
    if digest(paired/'protocol.json')!=ready['protocol_sha256']:raise ValueError('paired protocol changed')
    source_root=Path(protocol['inventory'])
    inputs={str((paired/name).resolve()):digest(paired/name) for name in ['protocol.json','ready.json']}
    for case in protocol['cases']:
        for name in ['corpus.json','frontend.json','source_pool.json']:
            path=source_root/case/name
            if digest(path)!=protocol['input_sha256'][case][name]:raise ValueError('source cohort input changed')
            inputs[str(path.resolve())]=digest(path)
    hashes={name:digest(ROOT/name) for name in FILES}
    output.mkdir(parents=True,exist_ok=False)
    write(output/'protocol.json',dict(version='helper-expected-slot-census-v1',
        paired_protocol=str((paired/'protocol.json').resolve()),source_inventory=str(source_root.resolve()),
        input_sha256=inputs,code_sha256=hashes,expected_candidates=4502,
        selection='every existing source_pool candidate; helper extension when corpus.language == go',
        metric='source syntax slots and candidate eligibility; no expected-value correctness, safe edit or detection metric',
        interface_scope='new Go interface permits scalar literal expectations only; existing ordinary predicates can become readonly, so it is not a lossless extension',
        diagnostic_rule=select_source_members([],limit),provider_calls=0,subject_executions=0,
        diagnostic_selection_use='offline suggestion only; not dispatched or substituted into any running experiment',
        forbidden_inputs=['model responses','oracle answers','target labels','hidden verifier','reference patch']))
    for name in FILES:
        path=output/'code_snapshot'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
    summaries,totals,go_totals,reasons,selections={},Counter(),Counter(),Counter(),{}
    for case in protocol['cases']:
        corpus,frontend,pool=[read(source_root/case/name) for name in ['corpus.json','frontend.json','source_pool.json']]
        index=HelperIndex(corpus) if corpus['language']=='go' else None
        if index is not None:
            base=index.census()
            write(output/case/'original_helper_index.json',base)
        rows=[]
        for raw in pool['candidates']:
            if raw.get('semantic_revision') or any(e.get('role')=='semantic_expected'
                for e in [*_program_edits(raw),*raw.get('edits',[]),*raw.get('program_edits',[])]):
                raise ValueError('historical oracle revision is outside source-only cohort')
            candidate=program_candidate(raw)
            ordinary=assertion_inventory(corpus,frontend,candidate)
            failure=None
            try:
                extended=inventory(corpus,frontend,candidate,index=index) if index is not None else None
            except (ValueError,KeyError,TypeError,UnicodeError) as error:
                extended=None;failure=dict(reason=type(error).__name__,detail=str(error))
            row=compare_slots(raw['id'],ordinary,extended)
            if failure is not None:
                row.update(extended_status='unknown_inventory_unavailable',extended_editable=0,
                    extended_eligible=False,extension_only_eligible=False,inventory_failure=failure,
                    unknown_reasons={failure['detail']:1})
                write(output/case/'inventories'/(raw['id']+'.json'),dict(status='unknown',**failure))
            elif extended is not None:
                # Keep all offered/readonly source rows for independent checks.
                write(output/case/'inventories'/(raw['id']+'.json'),extended)
            rows.append(row)
            numeric={k:int(row[k]) for k in ['ordinary_assertions','ordinary_editable','ordinary_readonly',
                'baseline_eligible','helper_calls','helper_editable','extended_editable','extended_eligible','extension_only_eligible']}
            numeric['candidates']=1;totals.update(numeric)
            if corpus['language']=='go':go_totals.update(numeric)
            reasons.update(row['unknown_reasons'])
        selection=select_source_members(rows,limit)
        selections[case]=selection
        write(output/case/'candidates.json',rows)
        summary=dict(language=corpus['language'],candidates=len(rows),
            baseline_eligible=sum(r['baseline_eligible'] for r in rows),
            extended_eligible=sum(r['extended_eligible'] for r in rows),
            extension_only_eligible=sum(r['extension_only_eligible'] for r in rows),
            ordinary_editable=sum(r['ordinary_editable'] for r in rows),helper_editable=sum(r['helper_editable'] for r in rows),
            ordinary_count_changed=sum(r.get('ordinary_count_changed',False) for r in rows),
            ordinary_editable_changed=sum(r.get('ordinary_editable_changed',False) for r in rows),
            extended_inventory_unavailable=sum(r['extended_status']=='unknown_inventory_unavailable' for r in rows),
            diagnostic_selection=selection)
        summaries[case]=summary;print(json.dumps(dict(case=case,**summary)),flush=True)
    if totals['candidates']!=4502 or len(summaries)!=17:raise ValueError('fixed cohort denominator changed')
    result=dict(version='helper-expected-slot-census-v1',cases=summaries,totals=dict(totals),
        go_totals=dict(go_totals),unknown_reasons=dict(reasons),
        interpretation='source support only; expected/oracle quality and subject behavior remain unmeasured')
    write(output/'summary.json',result);write(output/'diagnostic_selection.json',selections)
    if hashes!={name:digest(ROOT/name) for name in FILES} or any(digest(path)!=value for path,value in inputs.items()):
        raise ValueError('inputs/code changed during census; no seal')
    write(output/'seal.json',dict(files_sha256={str(path.relative_to(output)):digest(path)
        for path in sorted(output.rglob('*')) if path.is_file()}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--paired',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--diagnostic-members-per-case',type=int,default=2)
    args=parser.parse_args()
    if not 1<=args.diagnostic_members_per_case<=4:raise ValueError('diagnostic member limit must be one to four')
    print(json.dumps(run(args.paired,args.output,args.diagnostic_members_per_case)['go_totals']))
