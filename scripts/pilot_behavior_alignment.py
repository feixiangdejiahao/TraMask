#!/usr/bin/env python3
"""Controlled source/entry alignment pilot; manual counterparts are evaluation only."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.alignment import AlignmentIndex,RegionAlignmentIndex
from eviweave.artifacts import read_json,write_json
from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph
from eviweave.value_recipes import value_candidates
from verify_pre_slice_five_pilot import original_sources,FR

STUDY=ROOT/'research/behavior_alignment_pilot_20261104'


def public_sources(case,cohort):
    originals=original_sources(cohort[case['case']]);sources={};metadata={}
    for record in case['input_sources']:
        if record['origin']=='original_sources':
            path,full=originals[record['source']]
            offset=0;raw=full
            if Path(path).suffix=='.json':
                json.loads(full)
                raw=b'('+full+b')';offset=-1;path='material.ts'
        else:
            actions=read_json(ROOT/record['container_path'])['actions']
            action=next(a for a in actions if a['id']==record['action'])
            text=action
            for field in record['field']:text=text[field]
            full=text.encode();start=record['material_start'];end=record['material_end']
            payload=full[start:end];json.loads(payload)
            raw=b'('+payload+b')';offset=start-1;path='material.ts'
        assert hashlib.sha256(full).hexdigest()==record['sha256'],record['source']
        graph=SourceGraph({'id':record['source'],'path':path,'raw':raw})
        sources[record['source']]=(graph,BehaviorIndex(graph))
        metadata[record['source']]={'offset':offset,'path':record['path'],'sha256':record['sha256'],
                                    'bytes':len(full),'parse_issues':graph.issues}
    return sources,metadata


def locate_operation(index,source,start,end,offset):
    a,b=start-offset,end-offset
    matching=[(op['expression_range'][1]-op['expression_range'][0],key)
              for key,op in index.operations.items() if key[0]==source and
              op['expression_range'][0]<=a and b<=op['expression_range'][1]]
    return min(matching)[1] if matching else None


def operation_record(index,key,metadata):
    op=index.operations[key];offset=metadata[key[0]]['offset']
    a,b=op['expression_range'];graph=index.sources[key[0]][0]
    return {'source':key[0],'id':key[1],'kind':op['kind'],'name':op['name'],
            'range':[a+offset,b+offset],'scope':op['scope'],
            'text':graph.raw[a:b].decode()[:400],
            'receiver':op['receiver'],'arguments':op['arguments'],
            'guards':op['guards'],'frames':op['frames'],'unknowns':op['unknowns']}


def corpus_metrics(index):
    groups=list(index.by_name.values())
    calls=[(key,op) for key,op in index.operations.items() if op['kind']=='call']
    shapes=Counter()
    for key,op in calls:
        shapes[(op['name'],tuple(p['role'] for p in op['arguments']))]+=1
    return {'operations':len(index.operations),'calls':len(calls),
            'all_operation_pairs':len(index.operations)*(len(index.operations)-1)//2,
            'same_named_role_pairs':sum(len(g)*(len(g)-1)//2 for g in groups),
            'same_call_signature_pairs':sum(n*(n-1)//2 for n in shapes.values()),
            'call_signatures':len(shapes),
            'guards':sum(bool(op['guards']) for op in index.operations.values()),
            'observations':sum(op['observation'] is not None for op in index.operations.values()),
            'expression_order_edges':sum(len(b.order) for _,b in index.sources.values()),
            'identity_kinds':dict(Counter(p['identity_kind'] for op in index.operations.values()
                                         for p in op['arguments']+([op['receiver']] if op['receiver'] else [])))}


def query_and_evaluate(index,metadata,item):
    left=item['left'];right=item['right']
    left_key=locate_operation(index,left['source'],left['start'],left['end'],metadata[left['source']]['offset'])
    result={'id':item['id'],'case':item['case'],'relation':item['expected']['relation'],
            'status':item['expected']['status'],'query':left,'left_operation':None,
            'counterpart_operation':None,'candidate_count':0,'rank_name':None,'rank_roles':None,
            'exact_endpoint_operations':False,'alignment':None,'outcome':'no_expression_operation'}
    if left_key is None:return result
    result['left_operation']=operation_record(index,left_key,metadata)
    # The algorithm receives only the source entry. All supplied sources remain
    # eligible; the expected counterpart is inspected after both query results.
    started=time.perf_counter()
    name=index.query(left_key,mode='name');ranked=index.query(left_key,mode='roles')
    result['query_seconds']=time.perf_counter()-started
    result['candidate_count']=len(ranked)
    result['candidate_order']=[r['key'] for r in ranked]
    result['top_candidates']=[{**r,'operation':operation_record(index,tuple(r['key']),metadata)}
                              for r in ranked[:5]]
    if right is None:
        result['outcome']='requires_extension_or_check_without_historical_counterpart'
        return result
    right_key=locate_operation(index,right['source'],right['start'],right['end'],metadata[right['source']]['offset'])
    if right_key is None:
        result['outcome']='counterpart_is_not_expression_operation';return result
    result['counterpart_operation']=operation_record(index,right_key,metadata)
    result['exact_endpoint_operations']=(result['left_operation']['range']==[left['start'],left['end']] and
                                        result['counterpart_operation']['range']==[right['start'],right['end']])
    for label,rows in [('name',name),('roles',ranked)]:
        position=next((i+1 for i,row in enumerate(rows) if tuple(row['key'])==right_key),None)
        result['rank_'+label]=position
    if result['rank_roles'] is None:
        result['outcome']='different_operation_requires_bridge'
    else:
        result['outcome']='counterpart_in_candidates'
        result['alignment']=index.align(left_key,right_key)
    return result


def region_query_and_evaluate(index,metadata,item):
    left=item['left'];source=left['source'];offset=metadata[source]['offset']
    started=time.perf_counter()
    result=index.query(source,left['start']-offset,left['end']-offset)
    selection=result['selection']
    value_rows=[]
    if (len(selection['selected'])==1 and selection['status']=='exact' and
        (selection['selected'][0]['kind']=='field' or selection['selected'][0]['role']=='field_value')):
        value_rows=value_candidates(index,source,selection)
    row={'id':item['id'],'case':item['case'],'status':item['expected']['status'],
         'relation':item['expected']['relation'],'left_selection_status':selection['status'],
         'left_regions':[{k:r[k] for k in ('id','range','kind','ast_type','unknowns')} for r in selection['selected']],
         'channel_sizes':{channel:len(values) for channel,values in result['channels'].items()},
         'query_seconds':time.perf_counter()-started,'unknowns':result['unknowns'],
         'right_selection_status':None,'right_nodes':0,'retrieved_nodes':0,'ranks':[],
         'counterpart_retrieved':False,'structurally_represented':False,
         'difference':None,'outcome':'input_not_parsed',
         'channels':{channel:[{k:r[k] for k in ('key','range','score','basis','unknowns')} for r in values]
                     for channel,values in result['channels'].items()},
         'value_recipes':value_rows,'specified_value_origin_rank':None,
         'value_origin_occurrences':len({(o['key'][0],tuple(o['range'])) for r in value_rows for o in r['origins']})}
    if item['right'] is None:
        row['outcome']='annotation_has_no_historical_counterpart'
        return row
    right=item['right'];roffset=metadata[right['source']]['offset']
    target=index.select(right['source'],right['start']-roffset,right['end']-roffset)
    row['right_selection_status']=target['status'];row['right_nodes']=len(target['selected'])
    row['right_regions']=[{k:r[k] for k in ('id','range','kind','ast_type','unknowns')} for r in target['selected']]
    target_keys={(right['source'],r['id']) for r in target['selected']}
    row['specified_value_origin_rank']=next((r['rank'] for r in value_rows
        if target_keys & {tuple(origin['key']) for origin in r['origins']}),None)
    row['structurally_represented']=selection['status'] in {'exact','node_set'} and target['status'] in {'exact','node_set'}
    if not row['structurally_represented']:return row
    channel=item['expected']['relation']
    if channel not in result['channels']:
        row['outcome']='relation_channel_has_no_candidates';return row
    candidates=result['channels'][channel]
    positions={tuple(r['key']):i+1 for i,r in enumerate(candidates)}
    row['ranks']=[positions.get((right['source'],r['id'])) for r in target['selected']]
    row['retrieved_nodes']=sum(rank is not None for rank in row['ranks'])
    row['counterpart_retrieved']=row['retrieved_nodes']==row['right_nodes']
    row['outcome']='counterpart_nodes_retrieved' if row['counterpart_retrieved'] else 'missing_counterpart_nodes'
    if row['counterpart_retrieved'] and channel in {'same_operation','structural_role'}:
        row['difference']=index.difference(source,selection,right['source'],target)
    return row


def run(out,mode):
    out.mkdir(parents=True)
    protocol=read_json(STUDY/'protocol.json')
    cohort={c['screen_id']:c for c in read_json(FR/'cases.json')['cases']}
    code=out/'code';code.mkdir()
    for file in ['src/eviweave/alignment.py','src/eviweave/behavior.py','src/eviweave/evidence.py',
                 'src/eviweave/composition.py','src/eviweave/regions.py','src/eviweave/relations.py',
                 'src/eviweave/value_recipes.py','scripts/pilot_behavior_alignment.py']:
        (code/Path(file).name).write_bytes((ROOT/file).read_bytes())
    protocol.update(mode=mode,entry_scope='Manually specified left source intervals are controlled query inputs. No right interval, relation label or required delta is passed to query(). The corpus is built before reading annotations. This is not autonomous Step-D entry selection.',
                    baseline_run='20261104_behavior_alignment_n20_r01' if mode=='regions' else None)
    protocol['algorithm_input']['slicing_rule']='The full sources are indexed. Annotated left intervals are controlled query seeds; right intervals and semantic annotations are evaluation only. This controlled-entry protocol supersedes the original no-gold-seeds proposal; no Step-D or slice-localization recall is measured.'
    protocol['evaluation']['implemented_metrics']=['structural_endpoint_representation',
        'specified_counterpart_retrieval_in_manually_designated_channel',
        'specified_value_origin_rank_in_separate_recipe_channel']
    protocol['evaluation']['not_measured']=['required_delta_completeness','hard_negative_relation_rejection',
        'automatic_missing_operation_detection','semantic_alignment_precision']
    write_json(out/'input_protocol.json',protocol)
    # The input corpus/representation is built without importing annotations.
    built={};counts=[]
    for case in protocol['cases']:
        started=time.perf_counter();sources,metadata=public_sources(case,cohort)
        index=AlignmentIndex(sources) if mode=='operations' else RegionAlignmentIndex(sources)
        metrics=corpus_metrics(index if mode=='operations' else index.calls)
        if mode=='regions':
            metrics.update(regions=sum(len(r.regions) for r in index.regions.values()),
                           candidate_regions=len(index.pool),
                           relation_edges=sum(len(r.edges) for r in index.relations.values()))
        counts.append({'case':case['case'],'task':case['task'],'language':case['language'],
                       **metrics,'build_seconds':time.perf_counter()-started,
                       'sources':metadata})
        built[case['case']]=index,metadata
        print('indexed',case['case'],metrics['operations'],metrics['same_named_role_pairs'],flush=True)
    write_json(out/'corpus.json',counts)
    expected=read_json(STUDY/'alignment_expectations.json')
    write_json(out/'evaluation_annotations.json',expected)
    results=[]
    for item in expected['expectations']:
        index,metadata=built[item['case']]
        result=(query_and_evaluate(index,metadata,item) if mode=='operations' else
                region_query_and_evaluate(index,metadata,item));results.append(result)
        print('evaluated',item['id'],result['outcome'],result['rank_roles'] if mode=='operations' else result['ranks'],flush=True)
    write_json(out/'alignments.json',results)
    positive=[r for r in results if r['status']=='positive']
    summary={'cases':len(counts),'distinct_tasks':len({r['task'] for r in counts}),
             'languages':dict(Counter(r['language'] for r in counts)),
             'expectations':len(results),'positive_correspondences':len(positive),
             'outcomes':dict(Counter(r['outcome'] for r in results)),
             'operations':sum(r['operations'] for r in counts),
             'naive_operation_pairs':sum(r['all_operation_pairs'] for r in counts),
             'same_named_role_pairs':sum(r['same_named_role_pairs'] for r in counts),
             'same_call_signature_pairs':sum(r['same_call_signature_pairs'] for r in counts),
             'interpretation':'Controlled entry/source experiment, not end-to-end retrieval, complete behavior alignment, oracle correctness or bug-revealing success.',
             'new_model_requests':0,'new_replays':0,'new_product_tests':0}
    if mode=='operations':
        summary.update(positive_counterpart_retrieved=sum(r['rank_roles'] is not None for r in positive),
                       positive_exact_expression_endpoints=sum(r['rank_roles'] is not None and r['exact_endpoint_operations'] for r in positive),
                       top1_name=sum(r['rank_name']==1 for r in positive),top1_roles=sum(r['rank_roles']==1 for r in positive),
                       top5_name=sum(r['rank_name'] is not None and r['rank_name']<=5 for r in positive),
                       top5_roles=sum(r['rank_roles'] is not None and r['rank_roles']<=5 for r in positive))
    else:
        summary.update(positive_structurally_represented=sum(r['structurally_represented'] for r in positive),
                       positive_counterpart_nodes_retrieved=sum(r['counterpart_retrieved'] for r in positive),
                       top1=sum(r['counterpart_retrieved'] and max(r['ranks'])<=1 for r in positive),
                       top5=sum(r['counterpart_retrieved'] and max(r['ranks'])<=5 for r in positive),
                       top20=sum(r['counterpart_retrieved'] and max(r['ranks'])<=20 for r in positive),
                       relation_edges=sum(r['relation_edges'] for r in counts),
                       candidate_regions=sum(r['candidate_regions'] for r in counts))
    write_json(out/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--mode',choices=['operations','regions'],default='regions')
    args=parser.parse_args();run(args.out.resolve(),args.mode)


if __name__=='__main__':main()
