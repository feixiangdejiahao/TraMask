#!/usr/bin/env python3
"""Run the deployed public D/F algorithms on all 88 archived source histories."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json,relative_references
from eviweave.evidence import SourceGraph
from eviweave.material_entries import select_material_entries
import json
from eviweave.slice_frontier import matching_statements
from eviweave.slicing import ContextProgram
from eviweave.targets import locate_targets
from check_eviweave_step_d import public_materials
from report_entry_matching_slicing import byte_complete
from verify_pre_slice_five_pilot import original_sources
from eviweave.invocations import commands

FR=ROOT/'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
OLD=ROOT/'results/behavioral_masking/20261103_slicing_pilot_n88_r06'
GOLD=ROOT/'results/behavioral_masking/20261102_step_d_selectivity_n88_r01/quote_inventory.json'


def run_case(job):
    case,out=job;sid=case['screen_id'];directory=out/'cases'/sid;directory.mkdir()
    materials,submitted,actions=public_materials(case,directory/'materials')
    issue=(FR/'public_inputs'/sid/'issue.md').read_text();patch=(FR/'public_inputs'/sid/'patch.diff').read_text()
    targets=locate_targets(issue,patch,materials,submitted,set())
    write_json(directory/'targets.json',relative_references(targets,directory))
    originals=original_sources(case)
    local_queries={(row['source'],row.get('inline'),row.get('write')):row['points'] for row in targets['local_queries']}
    action_sources={m['source']:m['action_id'] for m in materials if m['kind']=='command'}
    writes={};per_action=Counter()
    for index,write in enumerate(commands(actions)['source_literals']):
        aid=write['action_id'];writes[aid,per_action[aid]]=f'H:{aid}:{index:04}';per_action[aid]+=1
    def canonical(unit):
        if 'write' in unit:return writes[action_sources[unit['source']],unit['write']]
        if 'inline' in unit:return f"I:{action_sources[unit['source']]}:{unit['inline']:04}"
        return 'F:'+unit['path'].removeprefix('/app/')
    grouped=defaultdict(list)
    for index,unit in enumerate(targets['units']):
        if unit['anchors']:grouped[canonical(unit)].append((index,unit))
    counts=Counter({k:0 for k in ('entry_groups','matched_statements','views','program','material','combined','references','native','native_program')})
    prepared={};sources={};paths=set();action_ids=set();pending=[]
    for source,units in sorted(grouped.items()):
        path=units[0][1]['path'];raw=originals[source][1]
        graph=SourceGraph({'id':source,'path':path,'raw':raw})
        unit=units[0][1];queries=local_queries.get((unit['source'],unit.get('inline'),unit.get('write')),[])
        ports,unmapped=matching_statements(graph,units,queries)
        if unmapped:pending.append({'source':source,'locations':unmapped,'issues':graph.issues})
        rows=ContextProgram.from_source(graph).grouped_slices(source,[p['node'] for p in ports]) if ports else []
        views=[];keys={};groups=[];by_node={p['node']:p for p in ports}
        for row in rows:
            view=row['view'];entries=view.pop('entries');file,=view['files']
            key=hashlib.sha256(json.dumps(view,sort_keys=True).encode()).hexdigest()
            if key not in keys:keys[key]=len(views);views.append(view)
            group=row['group'];assert all(n in file['nodes'] for n in group['matches'])
            groups.append({'group':group,'ports':[by_node[n] for n in group['matches']],
                           'program_entries':entries,'view':keys[key]})
        counts.update(entry_groups=len(groups),matched_statements=len(ports),views=len(views))
        if ports:
            paths.add(path)
            if source.startswith(('H:','I:')):action_ids.add(source.split(':')[1])
        filename=f'source_{len(sources):04}.json';sources[source]=filename
        write_json(directory/filename,{'source':source,'path':path,'sha256':hashlib.sha256(raw).hexdigest(),
                                      'groups':groups,'views':views,'issues':graph.issues})
        prepared[source]=(graph,views)
    carriers=select_material_entries(actions,targets['targets'],targets['changed_paths'],paths,action_ids,
              [{'path':m['path'],'source':m['source']} for m in materials if m['kind']=='file'])
    write_json(directory/'selection.json',{'sources':sources,'pending':pending,'metrics':dict(counts)})
    write_json(directory/'material_entries.json',relative_references(carriers,directory))
    # All public candidate selection and slices above are saved before labels.
    original_eval=read_json(OLD/'cases'/sid/'evaluation.json')
    gold={q['id']:q for q in read_json(GOLD) if q['case_id']==sid};quotes=[]
    chosen={a['action'] for a in carriers['actions']};by_action={a['id']:a for a in actions}
    file_sources={f['source'] for f in carriers['files']}
    for q in original_eval['quotes']:
        reference=gold[q['id']];code=reference['code'].strip();proofs=[]
        for alternative in q['alternatives']:
            source=alternative['source']
            if source not in prepared:continue
            graph,views=prepared[source];a,b=alternative['span'];assert graph.raw[a:b]==code.encode()
            proofs.extend({'source':source,'view':i} for i,v in enumerate(views)
                          if byte_complete(graph.raw,a,b,v['files'][0]['ranges'],graph.root))
        origin=reference['source_audit']['cited_origin'];material=False
        if not q['native']:
            if origin in chosen:
                action=by_action[origin];fields=[action['command']]+[action['expected'][k] for k in ('output','output_head','output_tail') if k in action['expected']]
                material=any(code in text for text in fields)
            elif '/files/' in origin:
                path='/app/'+origin.split('/files/',1)[1];raw=Path(origin).read_bytes()
                material=any(m['source'] in file_sources and m['path']==path and m['sha256']==hashlib.sha256(raw).hexdigest()
                             and code.encode() in raw for m in materials if m['kind']=='file')
        program=bool(proofs);counts.update(references=1,native=q['native'],native_program=q['native'] and program,
                                          program=program,material=material,combined=program or material)
        quotes.append({'id':q['id'],'native':q['native'],'program':program,'proofs':proofs[:3],
                       'material':material,'combined':program or material})
    result={'case_id':sid,'task':case['task'],'counts':dict(counts),'quotes':quotes,
            'material_entry_counts':{k:len(carriers[k]) for k in ('actions','files')}}
    write_json(directory/'evaluation.json',result);print(sid,dict(counts),flush=True);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=8);parser.add_argument('--cases',nargs='+');args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True);(out/'cases').mkdir()
    shutil.copytree(ROOT/'src/eviweave',out/'code/eviweave',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(Path(__file__),out/'code/checker.py')
    cases=read_json(FR/'cases.json')['cases']
    if args.cases:cases=[c for c in cases if c['screen_id'] in args.cases]
    write_json(out/'protocol.json',{'cases':[c['screen_id'] for c in cases],'algorithm':'deployed locate_targets + matching_statements + ContextProgram.grouped_slices + select_material_entries',
               'context':'archived immutable single-source versions; not new native replays','new_llm_calls':0})
    with ProcessPoolExecutor(max_workers=args.workers) as pool:results=list(pool.map(run_case,[(c,out) for c in cases]))
    counts=Counter()
    for row in results:counts.update(row['counts'])
    summary={'trajectories':len(results),'tasks':len({c['task'] for c in cases}),'counts':dict(counts),
             'misses':[q['id'] for row in results for q in row['quotes'] if not q['combined']],
             'code_misses':[q['id'] for row in results for q in row['quotes'] if q['native'] and not q['program']],
             'new_llm_calls':0,'new_native_replays':0}
    write_json(out/'summary.json',summary);print(summary,flush=True)


if __name__=='__main__':main()
