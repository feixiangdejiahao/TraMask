#!/usr/bin/env python3
"""Audit and summarize the 88-history entry/matching/slicing comparisons."""
import argparse
from collections import Counter
import csv
from pathlib import Path
import shutil
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json
from eviweave.anchors import STRINGS
from eviweave.blobs import BlobStore
from eviweave.evidence import SourceGraph
from eviweave.pre_slice import covered
from verify_pre_slice_five_pilot import original_sources

FR=ROOT/'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
GOLD=ROOT/'results/behavioral_masking/20261102_step_d_selectivity_n88_r01/quote_inventory.json'


def distribution(values):
    values=sorted(values)
    return {'min':min(values),'median':statistics.median(values),'p95':values[int(.95*(len(values)-1))],'max':max(values)}


def byte_complete(raw,start,end,ranges,tree):
    # A byte mask is independent of the pilot's AST token scoring. Whitespace
    # inside strings remains part of the required input, including XML/programs.
    if any(not covered(i,i+1,ranges) for i in range(start,end) if raw[i] not in b' \t\r\n'):return False
    todo=[tree]
    while todo:
        node=todo.pop()
        if node.end_byte<=start or node.start_byte>=end:continue
        if node.type in STRINGS:
            if not covered(max(start,node.start_byte),min(end,node.end_byte),ranges):return False
        else:todo.extend(node.named_children)
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--program',type=Path,required=True);parser.add_argument('--materials',type=Path,required=True)
    parser.add_argument('--local',type=Path,required=True);parser.add_argument('--screen',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True);(out/'cases').mkdir();shutil.copyfile(Path(__file__),out/'reporter.py')
    cases=read_json(FR/'cases.json')['cases'];gold={q['id']:q for q in read_json(GOLD)};ledger=[];counts=Counter()
    mode='test_frontier_syntax';case_rows=[];sizes=[];frontiers=[];gains=[];losses=[];context_gains=[];boundary_issues=[]
    for case in cases:
        sid=case['screen_id'];base=args.program/'cases'/sid
        selection=read_json(base/'selection.json');evaluation=read_json(base/'evaluation.json')
        links=read_json(args.materials/'cases'/(sid+'.json'));local=read_json(args.local/'cases'/sid/'evaluation.json')
        local_by={q['id']:q for q in local['quotes']};originals=original_sources(case);graphs={}
        case_counts=Counter({k:0 for k in ('references','native_references','program','material','combined',
                                          'batch_union_equal_groups','original_matched_statements_retained')})
        all_ports=set();covered_ports=set()
        for source,filename in selection['sources'].items():
            source_view=read_json(base/filename);views=source_view['views'];path,raw=originals[source]
            assert raw==BlobStore(base/'blobs').read(source_view['sha256'])
            groups=source_view['groups'][mode];ids={r['view'] for r in groups};sizes.extend(len(views[i]['nodes']) for i in ids)
            for group in groups:
                ranges=views[group['view']]['ranges'];frontiers.append(len(group['frontier']))
                for node in group['matches']:
                    all_ports.add((source,node))
                    if all(covered(a,b,ranges) for a,b in source_view['graph'][node]['ranges']):covered_ports.add((source,node))
                if 'boundary_issue' in group:boundary_issues.append({'case_id':sid,'source':source,'issue':group['boundary_issue']})
            left=source_view['groups']['test_frontier_comments'];right=source_view['groups']['test_frontier_batch']
            assert len(left)==len(right)
            for a,b in zip(left,right):assert views[a['view']]==views[b['view']]
            case_counts['batch_union_equal_groups']+=len(left)
            if any(q['alternatives'] and any(a['source']==source for a in q['alternatives']) for q in evaluation['quotes']):
                graphs[source]=(SourceGraph({'id':source,'path':path,'raw':raw}),source_view)
        assert all_ports==covered_ports
        case_counts['original_matched_statements_retained']+=len(all_ports)
        linked={q['id']:q for q in links['quotes']};rows=[]
        for q in evaluation['quotes']:
            qid=q['id'];reference=gold[qid];proofs=[]
            for alternative in q['alternatives']:
                source=alternative['source'];g,data=graphs[source];start,end=alternative['span']
                assert g.raw[start:end]==reference['code'].strip().encode()
                ids={group['view'] for group in data['groups'][mode]}
                for identity in sorted(ids):
                    if byte_complete(g.raw,start,end,data['views'][identity]['ranges'],g.root):
                        proofs.append({'source':source,'sha256':data['sha256'],'quote_span':[start,end],'view':identity});break
            program=bool(proofs);assert program==q['modes'][mode]['strict']
            material=linked[qid]['modes']['validation_and_structured_reads']['material']
            assert program or material
            assert not q['native'] or program
            baseline=q['modes']['all_public']['core'];core=q['modes'][mode]['core']
            if baseline and not core:losses.append(qid)
            if core and not baseline:gains.append(qid)
            if core and not local_by[qid]['modes']['test_frontier_comments']['core']:context_gains.append(qid)
            rows.append({'id':qid,'native':q['native'],'program':program,'program_proofs':proofs,
                         'material':material,'material_links':linked[qid]['modes']['validation_and_structured_reads']['links'],
                         'combined':program or material})
            case_counts.update({'references':1,'native_references':q['native'],'program':program,'material':material,'combined':program or material})
        result={'case_id':sid,'task':case['task'],'metrics':evaluation['metrics'],'verification':dict(case_counts),'references':rows}
        write_json(out/'cases'/(sid+'.json'),result);counts.update(case_counts);ledger.extend(rows)
        case_rows.append({'case_id':sid,'task':case['task'],'trial':case['trial'],'language':case['language'],
                          'baseline_groups':evaluation['metrics']['all_public']['entry_groups'],
                          'groups':evaluation['metrics'][mode]['entry_groups'],'views':evaluation['metrics'][mode]['unique_views'],
                          'source_bytes':evaluation['metrics'][mode]['sum_view_bytes'],**dict(case_counts)})
    assert not losses
    write_json(out/'reference_ledger.json',ledger)
    with (out/'cases.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(case_rows[0]));writer.writeheader();writer.writerows(case_rows)
    program=read_json(args.program/'summary.json');materials=read_json(args.materials/'summary.json');screen=read_json(args.screen/'summary.json')
    baseline=program['modes']['all_public'];final=program['modes'][mode]
    summary={'trajectories':len(cases),'tasks':len({c['task'] for c in cases}),
             'program_runs':{'context':str(args.program),'local':str(args.local)},'material_run':str(args.materials),
             'feature_run':str(args.screen),'feature_modes':screen['modes'],'program_modes':program['modes'],
             'material_modes':materials['modes'],'verification':dict(counts),'gains_over_baseline':gains,'losses_over_baseline':losses,
             'context_gains_over_local':context_gains,'boundary_issues':boundary_issues,
             'reductions_percent':{k:100*(1-final[k]/baseline[k]) for k in ('entry_groups','endpoint_seeds','unique_views','sum_view_nodes','sum_view_bytes','source_graphs')},
             'groups_per_trajectory':distribution([r['groups'] for r in case_rows]),
             'views_per_trajectory':distribution([r['views'] for r in case_rows]),'nodes_per_view':distribution(sizes),
             'endpoints_per_group':distribution(frontiers),'new_replays':0,'new_llm_calls':0}
    write_json(out/'summary.json',summary);print({k:summary[k] for k in ('trajectories','tasks','verification','reductions_percent','nodes_per_view')})


if __name__=='__main__':main()
