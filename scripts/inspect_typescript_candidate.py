"""Obtain paired TypeScript compiler diagnostics for one emitted source test."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search.checkpoint import read,digest
from scripts.run_relational_gap_case import run_case
from scripts.run_contract_repair_search import write,frozen


def prepare(artifact,output):
    output.mkdir(parents=True,exist_ok=False)
    manifest=read(artifact/'manifest.json');plan=read(artifact/'phase_plan.json')
    phases=[row for row in plan['phases'] if row['role'] in {'control','generated'}]
    targets={file['target'] for row in phases for file in row['files']}
    if len(targets)!=1:raise ValueError('This component requires one target test source')
    if not next(iter(targets)).endswith(('.ts','.tsx')):raise ValueError('Not a TypeScript test source')
    needed={file['staged'] for row in phases for file in row['files']}
    mounts=[row for row in manifest['mounts'] if row['target'] in needed]
    for row in mounts:
        if digest(row['source'])!=row['sha256']:raise ValueError('Frozen emitted source changed')
    names=[row['test_name'] for row in manifest['obligations']]
    worker=ROOT/'scripts/compare_typescript_programs.cjs'
    comparison=dict(target=next(iter(targets)),test_names=names,
                    phases=[dict(role=row['role'],files=row['files']) for row in phases])
    write(output/'plan.json',comparison)
    mounts.extend([dict(source=str(worker.resolve()),target='.type_analysis/worker.cjs',sha256=digest(worker)),
                   dict(source=str((output/'plan.json').resolve()),target='.type_analysis/plan.json',sha256=digest(output/'plan.json'))])
    protocol=dict(artifact=frozen(artifact/'manifest.json'),case=manifest['case'],mounts=mounts,
        worker=frozen(worker),program_execution=False,
        command='node .type_analysis/worker.cjs .type_analysis/plan.json /replay-logs/types.json')
    write(output/'prepared.json',protocol)
    return protocol


def run(root,timeout):
    protocol=read(root/'prepared.json')
    for row in protocol['mounts']:
        if digest(row['source'])!=row['sha256']:raise ValueError('Frozen compiler input changed')
    execution=run_case(protocol['case'],protocol['command'],mounts=protocol['mounts'],timeout=timeout,
        output=root/'executed',registry=ROOT/'data/relational_gap_v1/registry.json')
    report=root/'executed/types.json'
    if report.exists():
        result=read(report);return dict(status=result['status'],version=result['typescript_version'],
            new_diagnostics=result['new_diagnostics'],report=frozen(report))
    return dict(status='unknown_compiler_environment',execution=execution)


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('stage',choices=['prepare','run'])
    p.add_argument('--artifact',type=Path);p.add_argument('--output',type=Path);p.add_argument('--input',type=Path)
    p.add_argument('--timeout',type=int,default=180);args=p.parse_args()
    result=prepare(args.artifact,args.output) if args.stage=='prepare' else run(args.input,args.timeout)
    print(json.dumps(result,indent=2))
