#!/usr/bin/env python3
"""Collect two real S030 validation commands with the new IO observer."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from eviweave.artifacts import read_json,write_json
from eviweave.collection import collect_tests
from eviweave.slicing import TrajectorySlicer
from eviweave.targets import targets_from_manifest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True)
    previous=ROOT/'results/behavioral_masking/20261031_eviweave_refactor_smoke_r02'
    checkpoint=read_json(previous/'S030/checkpoint.json');raw=out/'inputs';raw.mkdir();steps=[];jobs=[]
    (raw/'instruction.md').write_text('Check multipart streaming and closing behavior of `Response.iter_multipart()`.\n')
    (raw/'model.patch').write_bytes(b'')
    (raw/'task.toml').write_text('[metadata]\nbase_commit_hash="'+checkpoint['head']+'"\n[environment]\ndocker_image="'+checkpoint['image_id']+'"\n')
    for index,name in enumerate(['baseline_streaming','baseline_malformed']):
        plan=read_json(previous/name/'plan.json');command=plan['command'];jobs.append(command)
        output=(previous/name/'container/calls/test/output.bin').read_text()
        steps.append({'step_id':index,'tool_calls':[{'function_name':'bash','arguments':{'command':command}}],
                      'observation':{'results':[{'content':json.dumps({'returncode':0,'output':output})}]}})
    write_json(raw/'trajectory.json',{'steps':steps})
    result=collect_tests({'id':'S030-two-validations','image':checkpoint['image_id'],'base_commit':checkpoint['head']},raw,out/'replay')
    assert result['state_validation_passed'] and not result['timeouts'] and not result['returncode_differences']
    manifest_path=Path(result['step_a']['manifest']);manifest=read_json(manifest_path)
    targets=targets_from_manifest(manifest_path);write_json(out/'targets.json',targets)
    slicer=TrajectorySlicer(manifest_path);selected=0;views=[]
    for unit in targets['units']:
        if not unit['path'].endswith('test_multipart_response.py') or 'inline' in unit or 'write' in unit:continue
        path,digest,source=slicer.source(unit['source'])
        needle=b'list(response.iter_multipart())';start=source.find(needle,unit['start'],unit['end'])
        if start<0:continue
        selected+=1;views.extend(slicer.location(unit['source'],start,start+len(needle)))
    assert selected and views
    write_json(out/'selected_slices.json',views)
    summary={'case':'S030','commands':jobs,'submission_state_matches':True,
             'source_versions':len(manifest['source_versions']),'events':len(slicer.trajectory.events),
             'materials':len(slicer.trajectory.materials),'source_points':selected,'views':len(views),
             'execution_bound_views':sum('consumer' in v for v in views),
             'scope':'Two original validation commands on the existing S030 submitted checkpoint; not the complete original trajectory.',
             'new_llm_calls':0}
    write_json(out/'verification.json',summary);print(summary)


if __name__=='__main__':main()
