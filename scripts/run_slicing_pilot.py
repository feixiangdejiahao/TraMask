#!/usr/bin/env python3
"""Run the research slicer on all D point types; score gold after freezing slices."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.anchors import STRINGS, parse_source, changed_lines
from eviweave.artifacts import read_json, write_json
from eviweave.evidence import SourceGraph
from eviweave.invocations import commands
from eviweave.pre_slice import covered, merge_ranges
from eviweave.pre_slice_queries import public_rules, role_points
from eviweave.replay.trajectory import resolve_submission_actions
from verify_pre_slice_five_pilot import original_sources

FR=ROOT/'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
D=ROOT/'results/behavioral_masking/20261103_eviweave_d_optimized_n88_r01'
PRIOR=ROOT/'results/behavioral_masking/20261103_pre_slice_provenance_n88_r01'
GOLD=ROOT/'results/behavioral_masking/20261102_step_d_selectivity_n88_r01'


def token_ranges(root,start,end,*,core=False):
    result=[];todo=[root]
    while todo:
        node=todo.pop()
        if node.end_byte<=start or node.start_byte>=end:
            continue
        if (core and node.type=='expression_statement' and node.parent is not None
                and node.parent.type=='block' and node.parent.parent.type=='function_definition'
                and node.parent.named_children[0]==node and node.start_byte>=start and node.end_byte<=end
                and len(node.named_children)==1 and node.named_children[0].type=='string'):
            continue
        # String content may have children only for escapes. Its ordinary text
        # lies between those children, so a leaf-only walk would miss it.
        if node.type in STRINGS:
            result.append([max(start,node.start_byte),min(end,node.end_byte)])
        elif not node.children:
            if core and node.type in {'(',')','{','}','[',']',',',';',':'}:
                continue
            result.append([max(start,node.start_byte),min(end,node.end_byte)])
        else:
            todo.extend(node.children)
    return result


def run_case(job):
    case,out,mode=job;sid=case['screen_id'];started=perf_counter()
    directory=out/'cases'/sid;directory.mkdir()
    originals=original_sources(case)
    actions,_=resolve_submission_actions(read_json(Path(case['input_directory'])/'trajectory.json'))
    write_ids,per_action={},Counter()
    for i,w in enumerate(commands(actions)['source_literals']):
        aid=w['action_id'];write_ids[aid,per_action[aid]]=f'H:{aid}:{i:04}';per_action[aid]+=1
    def canonical(u):
        if 'write' in u:
            aid=u['source'].partition('#/')[2].removesuffix(':command');return write_ids[aid,u['write']]
        if 'inline' in u:
            aid=u['source'].partition('#/')[2].removesuffix(':command');return f"I:{aid}:{u['inline']:04}"
        return 'F:'+u['path'].removeprefix('/app/')
    selection=read_json(D/'selections'/(sid+'.json'))
    units=defaultdict(list)
    for i,u in enumerate(selection['units']):
        units[canonical(u)].append((i,u))
    changes=changed_lines((FR/'public_inputs'/sid/'patch.diff').read_text())
    final=[]
    for path in changes:
        if 'F:'+path in originals and Path(path).suffix in {'.py','.go','.rs','.js','.jsx','.ts','.tsx','.mjs','.cjs','.mts','.cts'}:
            _,raw=originals['F:'+path];final.append((path,raw,parse_source(path,raw)))
    rules=public_rules((FR/'public_inputs'/sid/'issue.md').read_text(),changes,final,[],family=False)
    totals,kinds=Counter(),Counter();source_results={};unions=defaultdict(list)
    for source_index,(source,entries) in enumerate(sorted(units.items())):
        path,raw=originals[source];graph=SourceGraph({'id':source,'path':path,'raw':raw})
        seeds={};unmapped=[];coarse=[u for _,u in entries if not source.startswith('F:') and [u['start'],u['end']] in u['anchors']]
        def add(a,b,origin,entry=None):
            c=graph.criterion(a,b) if graph.nodes else None
            if c is None:
                unmapped.append({'range':[a,b],'origin':origin});return
            key=c['start'],c['end'],c['node']
            if key not in seeds:
                seeds[key]={**c,'origins':set(),'raw_references':0,'entries':set()}
            item=seeds[key];item['origins'].add(origin);item['raw_references']+=1
            if entry is not None:item['entries'].add(entry)
        for entry,u in entries:
            for a,b in u['anchors']:
                if not source.startswith('F:') and [a,b]==[u['start'],u['end']]:
                    totals['whole_scope_markers']+=1
                else:
                    totals['raw_precise_points']+=1;add(a,b,'D_precise',entry)
        if coarse:
            public={'id':source,'path':path,'raw':raw,'parsed':parse_source(path,raw)}
            for (_,a,b),points in role_points([public],rules,precise=True).items():
                if any(u['start']<=a and b<=u['end'] for u in coarse):
                    for _,_,c,d in points:add(c,d,'authored_local_query')
            for n in graph.nodes:
                if n['observation'] and any(u['start']<=n['start'] and n['end']<=u['end'] for u in coarse):
                    add(n['start'],n['end'],'authored_observation')
                if source.startswith('I:') and any(name in {'write','write_text','write_bytes','dump'} for name,_,_ in n['calls']):
                    add(n['start'],n['end'],'authored_file_output')
        unique={};seed_rows=[];by_statement={}
        for seed in sorted(seeds.values(),key=lambda s:(s['start'],s['end'],s['node'])):
            node=seed['node']
            if node not in by_statement:
                by_statement[node]=graph.slice(node,forward=mode!='backward_only',
                                               state=mode!='without_state',calls=mode!='without_calls')
            result=by_statement[node]
            signature=(graph.nodes[node]['scope'],tuple(result['nodes']),tuple(tuple(binding) for binding in result['bindings']))
            if signature not in unique:
                unique[signature]={'id':len(unique),'scope':graph.nodes[node]['scope'],**result,'seeds':[]}
            target=unique[signature]
            seed_rows.append({k:v for k,v in seed.items() if k not in {'origins','entries'}}|
                             {'origins':sorted(seed['origins']),'entries':sorted(seed['entries']),'slice':target['id']})
            target['seeds'].append(len(seed_rows)-1)
            kinds[seed['kind']]+=1
        slices=list(unique.values())
        totals['source_graphs']+=1;totals['graph_nodes']+=len(graph.nodes)
        totals['normalized_criteria']+=len(seed_rows);totals['statement_criteria']+=len(by_statement)
        totals['unique_slices']+=len(slices);totals['duplicate_slice_criteria']+=len(seed_rows)-len(slices)
        totals['unmapped_points']+=len(unmapped)
        totals['slices_with_unresolved_context']+=sum(bool(s['unresolved']) for s in slices)
        totals['slice_node_references']+=sum(len(s['nodes']) for s in slices)
        union=merge_ranges(span for s in slices for span in s['ranges']);unions[source]=union
        totals['slice_union_bytes']+=sum(b-a for a,b in union)
        totals['sum_slice_bytes']+=sum(b-a for s in slices for a,b in s['ranges'])
        # Count strict source-node containment within one function context.
        buckets=defaultdict(list)
        for s in slices:buckets[s['scope']].append(s)
        contained=0;examples=[]
        for scope,items in buckets.items():
            ordered=sorted(items,key=lambda s:len(s['nodes']),reverse=True)
            inverted=defaultdict(set);sets={}
            for s in ordered:
                ids=set(s['nodes']);sets[s['id']]=ids
                candidates=set.intersection(*(inverted[n] for n in ids)) if ids else set()
                supers=[i for i in candidates if ids<sets[i]]
                if supers:
                    contained+=1
                    if len(examples)<8:examples.append([s['id'],min(supers)])
                for n in ids:inverted[n].add(s['id'])
        totals['strictly_contained_slices_same_function']+=contained
        filename=f'source_{source_index:04}.json'
        write_json(directory/filename,{'source':source,'path':path,'graph':graph.export_nodes(),
                                      'scopes':[{'id':s['id'],'name':s['name'],'kind':s['kind'],'parent':s['parent'],'header':s['header']} for s in graph.scopes],
                                      'issues':graph.issues,'criteria':seed_rows,'slices':slices,'unmapped':unmapped,
                                      'containment_examples':examples})
        source_results[source]={'file':filename,'union':union,'slice_ranges':[s['ranges'] for s in slices],
                                 'root':graph.root,'raw':raw}
    write_json(directory/'selection.json',{'case_id':sid,'counts':dict(totals),'criteria_kinds':dict(kinds),
                                          'sources':{s:v['file'] for s,v in source_results.items()}})
    # Gold is evaluated after the public slices above have been written.
    prior=read_json(PRIOR/'cases'/(sid+'.json'));gold={q['id']:q for q in read_json(GOLD/'quote_inventory.json') if q['case_id']==sid}
    rows=[]
    for q in prior['quotes']:
        reference=gold[q['id']]
        if q['native']:
            spans=q['original_spans']
        else:
            spans=[];origin=reference['source_audit']['cited_origin'];kind=reference['source_audit']['span_kind']
            candidates=[]
            if origin.startswith('s') and '_c' in origin and kind.startswith('exact_command'):
                candidates=[s for s in originals if s.startswith(('H:'+origin+':','I:'+origin+':'))]
            elif '/files/' in origin:
                source='F:'+origin.split('/files/',1)[1]
                if source in originals and hashlib.sha256(originals[source][1]).hexdigest()==hashlib.sha256(Path(origin).read_bytes()).hexdigest():
                    candidates=[source]
            for source in candidates:
                needle=reference['code'].strip().encode();a=originals[source][1].find(needle)
                if a!=-1:spans.append([source,a,a+len(needle)])
        alternatives=[]
        for source,a,b in spans:
            if source not in source_results:continue
            sr=source_results[source];assert sr['raw'][a:b]==gold[q['id']]['code'].strip().encode()
            required=token_ranges(sr['root'],a,b)
            core=token_ranges(sr['root'],a,b,core=True)
            covered_union=all(covered(c,d,sr['union']) for c,d in required)
            covered_core=all(covered(c,d,sr['union']) for c,d in core)
            one=[i for i,ranges in enumerate(sr['slice_ranges']) if all(covered(c,d,ranges) for c,d in required)]
            core_one=[i for i,ranges in enumerate(sr['slice_ranges']) if all(covered(c,d,ranges) for c,d in core)]
            hit_tokens=sum(covered(c,d,sr['union']) for c,d in required)
            alternatives.append({'source':source,'span':[a,b],'tokens':len(required),'tokens_covered':hit_tokens,
                                 'all_tokens_in_slice_union':covered_union,'single_slices':one[:8],
                                 'core_tokens':len(core),'core_union_covered':covered_core,'core_single_slices':core_one[:8]})
        if q['native']:assert alternatives,q['id']
        rows.append({'id':q['id'],'native':q['native'],'code_aligned':bool(alternatives),
                     'union_covered':any(x['all_tokens_in_slice_union'] for x in alternatives),
                     'single_slice_covered':any(x['single_slices'] for x in alternatives),
                     'core_union_covered':any(x['core_union_covered'] for x in alternatives),
                     'core_single_slice_covered':any(x['core_single_slices'] for x in alternatives),
                     'alternatives':alternatives})
    write_json(directory/'evaluation.json',{'case_id':sid,'quotes':rows})
    row={'case_id':sid,'task':case['task'],'counts':dict(totals),'criteria_kinds':dict(kinds),
         'native_references':sum(q['native'] for q in rows),
         'native_union_covered':sum(q['native'] and q['union_covered'] for q in rows),
         'native_single_slice_covered':sum(q['native'] and q['single_slice_covered'] for q in rows),
         'native_core_union_covered':sum(q['native'] and q['core_union_covered'] for q in rows),
         'native_core_single_slice_covered':sum(q['native'] and q['core_single_slice_covered'] for q in rows),
         'other_code_aligned':sum(not q['native'] and q['code_aligned'] for q in rows),
         'other_core_union_covered':sum(not q['native'] and q['core_union_covered'] for q in rows),
         'other_core_single_slice_covered':sum(not q['native'] and q['core_single_slice_covered'] for q in rows),
         'misses':[q['id'] for q in rows if q['native'] and not q['union_covered']],
         'core_misses':[q['id'] for q in rows if q['native'] and not q['core_union_covered']],
         'seconds':perf_counter()-started}
    write_json(out/'case_metrics'/(sid+'.json'),row);print(sid,'covered',row['native_union_covered'],'/',row['native_references'],'slices',totals['unique_slices'],flush=True)
    return row


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--cases',nargs='*');parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--mode',choices=['full','backward_only','without_state','without_calls'],default='full')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True)
    for name in ['cases','case_metrics','code']:(out/name).mkdir()
    for path in [Path(__file__),ROOT/'src/eviweave/evidence.py']:(out/'code'/path.name).write_bytes(path.read_bytes())
    cases=read_json(FR/'cases.json')['cases']
    if args.cases:cases=[c for c in cases if c['screen_id'] in args.cases]
    write_json(out/'protocol.json',{'case_ids':[c['screen_id'] for c in cases],
                                  'mode':args.mode,
                                  'algorithm':'CFG reaching definitions + lexical class/import binding + conservative object state order + matched local call contexts + observation backward completion.',
                                  'seeds':'D precise points; in protected authored scopes: unfiltered public queries and observation/file-output statements. No gold-derived seeds.',
                                  'evaluation':'All 128 original references; AST token coverage where the cited origin aligns with an analyzed public source. Strict tokens and executable-core tokens (structural delimiters/function docstrings excluded) separately. Input string contents remain exact. Event/data-only references are not counted as program-sliced.',
                                  'containment':'Descriptive same-function node-set containment only; not a deletion rule.',
                                  'new_llm_calls':0,'new_replays':0})
    started=perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:results=list(pool.map(run_case,[(c,out,args.mode) for c in cases]))
    counts,kinds=Counter(),Counter()
    for r in results:counts.update(r['counts']);kinds.update(r['criteria_kinds'])
    summary={'trajectories':len(results),'tasks':len({r['task'] for r in results}),'counts':dict(counts),'criteria_kinds':dict(kinds),
             **{k:sum(r[k] for r in results) for k in ['native_references','native_union_covered','native_single_slice_covered',
                 'native_core_union_covered','native_core_single_slice_covered','other_code_aligned','other_core_union_covered','other_core_single_slice_covered']},
             'misses':[{'case_id':r['case_id'],'ids':r['misses']} for r in results if r['misses']],
             'core_misses':[{'case_id':r['case_id'],'ids':r['core_misses']} for r in results if r['core_misses']],
             'wall_seconds':perf_counter()-started,'new_llm_calls':0,'new_replays':0}
    write_json(out/'summary.json',summary)
    with (out/'cases.csv').open('w',encoding='utf-8',newline='') as stream:
        fields=['case_id','task','native_references','native_union_covered','native_single_slice_covered',*sorted(counts)]
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader()
        writer.writerows({**{k:r[k] for k in fields[:5]},**{k:r['counts'].get(k,0) for k in sorted(counts)}} for r in results)
    print(summary,flush=True)


if __name__=='__main__':main()
