#!/usr/bin/env python3
"""Execute frozen composition candidates; reference data stays on this side."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json
from eviweave.execution import run_in_checkpoint,patch_paths
from eviweave.anchors import SUFFIXES
from eviweave.replay.container import open_container
from pilot_composition_plans import COHORT,ARMS,FR,case_rows


def prepare_reference(sid,out):
    case=case_rows()[sid];pointer=read_json(FR/'cases'/sid/'checkpoint.json')
    directory=out/'references'/sid;directory.mkdir(parents=True)
    solution=Path(case['task_directory'])/'solution/solution.patch'
    with open_container(pointer['image_id'],pointer['head'],directory/'container') as runtime:
        command='git -c safe.directory=/app -C /app reset --hard '+case['base_commit']+' && git -c safe.directory=/app -C /app clean -fd'
        reset=runtime.run(command,'reset',timeout=180)
        if reset['returncode']:
            write_json(directory/'preparation.json',{'status':'reset_failed','execution':reset});return sid,'reset_failed'
        remote=runtime.scratch+'/reference.patch';runtime.copy_to(solution,remote)
        applied=runtime.run('git -c safe.directory=/app -C /app apply --whitespace=nowarn '+remote,'apply',timeout=180)
        if applied['returncode']:
            write_json(directory/'preparation.json',{'status':'apply_failed','execution':applied});return sid,'apply_failed'
        committed=runtime.run('git -c safe.directory=/app -C /app add -A && git -c safe.directory=/app -C /app -c user.name=EviWeave -c user.email=eviweave@local commit --allow-empty -m reference-pilot','commit',timeout=180)
        if committed['returncode']:
            write_json(directory/'preparation.json',{'status':'commit_failed','execution':committed});return sid,'commit_failed'
        checkpoint=runtime.checkpoint()
    write_json(directory/'checkpoint.json',checkpoint)
    write_json(directory/'preparation.json',{'status':'ready','base_commit':case['base_commit'],
        'solution_patch':str(solution),'solution_sha256':hashlib.sha256(solution.read_bytes()).hexdigest(),
        'checkpoint':checkpoint,'reference_test_patch_installed':False})
    print('reference ready',sid,flush=True);return sid,'ready'


def facts(output):
    parsed=[];unparsed=[];decoder=json.JSONDecoder()
    for line in output.splitlines():
        if line.startswith('{"Time":'):
            outer=json.loads(line)
            if 'Output' in outer:line=outer['Output']
        marker='EVIWEAVE_FACT'
        if marker not in line:continue
        payload=line.split(marker,1)[1].lstrip()
        try:fact,_=decoder.raw_decode(payload)
        except json.JSONDecodeError:
            unparsed.append(line);continue
        parsed.append(fact)
    return parsed,unparsed


def prepare_dependencies(sid,implementation,out,attempt):
    """One explicit dependency-fetch stage, followed by offline test runs."""
    if implementation=='delivered':pointer=read_json(FR/'cases'/sid/'checkpoint.json')
    else:pointer=read_json(out/'references'/sid/'checkpoint.json')
    parent=out/'dependency_checkpoints'/sid/implementation
    directory=parent/attempt
    directory.mkdir(parents=True)
    with open_container(pointer['image_id'],pointer['head'],directory/'network_fetch',network='bridge') as runtime:
        record=runtime.run('CARGO_NET_RETRY=0 cargo fetch --locked','fetch',timeout=600)
        write_json(directory/'fetch.json',record)
        if record['returncode']!=0:return sid,implementation,'fetch_failed'
        checkpoint=runtime.checkpoint()
    write_json(parent/'checkpoint.json',checkpoint)
    return sid,implementation,'ready'


def source_paths(sid):
    case=case_rows()[sid]
    delivered=(Path(case['input_directory'])/'model.patch').read_text()
    reference=(Path(case['task_directory'])/'solution/solution.patch').read_text()
    paths=set(patch_paths(delivered)+patch_paths(reference))
    return sorted(p for p in paths if not re.search(r'(?:/tests?/|/fixtures?/|/testdata/|_test\.[^/]+$|/test_[^/]+$)',p))


def execute(job):
    sid,arm,implementation,repetition,out,checkpoint_set=job
    directory=out/'cases'/sid/arm
    outcome=read_json(directory/'outcome.json')
    if outcome['status']!='generated':return sid,arm,implementation,'not_generated'
    candidate=read_json(directory/'candidate.json');files=read_json(directory/'files.json')
    if checkpoint_set=='dependencies':pointer=read_json(out/'dependency_checkpoints'/sid/implementation/'checkpoint.json')
    elif implementation=='delivered':pointer=read_json(FR/'cases'/sid/'checkpoint.json')
    else:pointer=read_json(out/'references'/sid/'checkpoint.json')
    checkpoint={k:pointer[k] for k in ('image_id','head')}
    protected=source_paths(sid)
    observed_paths=sorted(set(protected)|{f['destination'] for f in files if Path(f['destination']).suffix in SUFFIXES})
    overlap=[f['destination'] for f in files if f['destination'] in protected]
    execution_dir=directory/'executions'/implementation/f'r{repetition:02}'
    if overlap:
        write_json(execution_dir/'assessment.json',{'status':'candidate_modifies_implementation','paths':overlap})
        return sid,arm,implementation,'candidate_modifies_implementation'
    command=candidate['command']
    if 'jest' in command and '--runInBand' not in command and '--maxWorkers' not in command:
        command+=' --runInBand'
    if re.search(r'\bgo\s+test\b',command) and not re.search(r'(^|\s)-v(?:\s|$)',command):
        command+=' -v'
    env={'PYTEST_ADDOPTS':'-s'} if 'pytest' in command else {}
    result=run_in_checkpoint(checkpoint,command,execution_dir,timeout=600,env=env,
        build_commands=candidate['build_commands'],source_paths=observed_paths,
        files=[(f['source'],f['destination']) for f in files])
    execution=result['execution']
    output=Path(execution['output']).read_text(errors='replace') if execution is not None else ''
    observed,unparsed=facts(output)
    assessment={'status':result['status'],'source_unchanged':result['sources']['unchanged'],
        'runner_command':command,'generated_command':candidate['command'],
        'returncode':execution['returncode'] if execution is not None else None,
        'facts':observed,'unparsed_fact_lines':unparsed,
        'expected_fact_names':[f['name'] for f in candidate['facts']],
        'observed_fact_names':[f['name'] for f in observed if 'name' in f],
        'build_returncodes':[b['returncode'] for b in result['builds']],
        'exit_status_is_not_bug_verdict':True}
    write_json(execution_dir/'assessment.json',assessment)
    print('executed',sid,arm,implementation,repetition,assessment['returncode'],len(observed),'facts',flush=True)
    return sid,arm,implementation,assessment['returncode']


def smoke(out):
    directory=out/'infrastructure/overlay_smoke';directory.mkdir(parents=True)
    script=directory/'probe.py';script.write_text('from pathlib import Path\nassert Path(__file__).read_text().startswith("from pathlib")\nprint("candidate_overlay_ok")\n')
    pointer=read_json(FR/'cases/S030/checkpoint.json')
    result=run_in_checkpoint({k:pointer[k] for k in ('image_id','head')},
        'python3 /app/tests/eviweave_overlay_probe.py',directory/'execution',
        source_paths=['/app/httpx/_models.py'],files=[(script,'/app/tests/eviweave_overlay_probe.py')])
    assert result['execution']['returncode']==0 and result['sources']['unchanged']
    print('real Docker candidate overlay passed',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['references','execute','smoke','dependencies'])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cases',nargs='+',default=COHORT)
    parser.add_argument('--arms',nargs='+',default=ARMS)
    parser.add_argument('--implementations',nargs='+',default=['delivered','reference'])
    parser.add_argument('--repetition',type=int,default=1)
    parser.add_argument('--checkpoint-set',choices=['original','dependencies'],default='original')
    parser.add_argument('--dependency-attempt',default='network_fetch_001')
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args();out=args.out.resolve()
    if args.operation=='smoke':smoke(out);return
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        if args.operation=='references':
            for row in pool.map(lambda sid:prepare_reference(sid,out),args.cases):print(row,flush=True)
        elif args.operation=='dependencies':
            for row in pool.map(lambda row:prepare_dependencies(*row,out,args.dependency_attempt),[(s,i) for s in args.cases for i in args.implementations]):print(row,flush=True)
        else:
            jobs=[(sid,arm,impl,args.repetition,out,args.checkpoint_set) for sid in args.cases for arm in args.arms for impl in args.implementations]
            for row in pool.map(execute,jobs):print(row,flush=True)


if __name__=='__main__':main()
