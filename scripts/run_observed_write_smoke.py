"""Two deterministic offline overlay smoke groups, sharing one Docker slot."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search.checkpoint import digest,read,write
from combination_testing.test_reports import parse_report
from scripts.run_relational_gap_case import run_case


def prepare(overlay,output):
    output.mkdir(parents=True,exist_ok=False)
    groups=read(overlay/'summary.json')['groups']
    selected,audit=[],[]
    for case in sorted({group['case'] for group in groups}):
        chosen=False
        for group in sorted((g for g in groups if g['case']==case),key=lambda g:g['manifest']):
            mapped={}
            for phase in group['phases']:
                queries=read(phase['instrumentation'])['queries']
                mapped[phase['role']]={json.dumps([q['source_q_span'],q['source_allocation_span']],sort_keys=True) for q in queries}
            common=mapped.get('control',set())&mapped.get('generated',set())
            manifest=read(group['manifest'])
            source=Path(manifest['observation_overlay']['source_manifest'])
            baseline=source.parent.parent.parent/'executed'/source.parent.name
            available=(baseline/'execution.json').is_file()
            eligible=bool(common) and available
            audit.append(dict(case=case,manifest=group['manifest'],common_mapped_q=len(common),
                              baseline_available=available,eligible=eligible))
            if eligible and not chosen:
                copy=output/case/'baseline'
                copy.parent.mkdir(parents=True,exist_ok=True)
                shutil.copytree(baseline,copy)
                selected.append(dict(case=case,manifest=group['manifest'],manifest_sha256=digest(group['manifest']),
                    source_manifest=str(source),source_manifest_sha256=digest(source),
                    baseline_original=str(baseline),baseline_copy=str(copy.resolve()),
                    baseline_files_sha256={str(p.relative_to(copy)):digest(p) for p in copy.rglob('*') if p.is_file()},
                    common_mapped_q=len(common)))
                chosen=True
    protocol=dict(selection='per case lexicographically first group with shared mapped control/generated q and existing baseline execution',
        target_labels_used=False,provider_calls=0,max_concurrent_new_containers=1,
        max_project_experiment_containers=4,selected=selected,all_groups=audit,
        overlay_seal_sha256=digest(overlay/'seal.json'),script_sha256=digest(Path(__file__)))
    write(output/'protocol.json',protocol)
    return protocol


def run(output):
    protocol=read(output/'protocol.json')
    summaries=[]
    for selection in protocol['selected']:
        case=selection['case']
        manifest_path=Path(selection['manifest'])
        if digest(manifest_path)!=selection['manifest_sha256']:
            raise ValueError('Frozen smoke manifest changed')
        for relative,checksum in selection['baseline_files_sha256'].items():
            if digest(Path(selection['baseline_copy'])/relative)!=checksum:
                raise ValueError('Frozen baseline changed')
        command=subprocess.run(['docker','ps','--format','{{.ID}} {{.Names}}'],check=True,
                               text=True,capture_output=True)
        active=[line for line in command.stdout.splitlines() if line.split()[1].startswith('relational-gap-')]
        write(output/case/'pre_dispatch_containers.json',dict(project_experiments=active,
                other_container_count=len(command.stdout.splitlines())-len(active)))
        if len(active)>=protocol['max_project_experiment_containers']:
            summaries.append(dict(case=case,status='deferred_no_slot'))
            break
        manifest=read(manifest_path)
        for mount in manifest['mounts']:
            if digest(mount['source'])!=mount['sha256']:
                raise ValueError('Frozen overlay mount changed')
        execution=output/case/'execution'
        result=run_case(case,manifest['command'],mounts=manifest['mounts'],timeout=manifest['timeout'],
            output=execution,registry=ROOT/'data/relational_gap_v1/registry.json')
        comparisons=[]
        for phase in manifest['phases']:
            role=phase['role']
            items=manifest['controls'] if role=='control' else manifest.get('profile_obligations',[]) if role=='source_profile' else manifest['obligations']
            report=parse_report(execution/role,phase['report'],
                read(execution/role/'result.json') if (execution/role/'result.json').exists() else result,
                selected_names=[row['id'] for row in items])
            write(execution/role/'normalized.json',report)
            baseline=read(Path(selection['baseline_copy'])/role/'normalized.json')
            outcomes=lambda value:sorted((row['id'],row['status']) for row in value['tests'])
            trace=execution/role/'observed_writes.jsonl'
            events=[json.loads(line) for line in trace.read_text().splitlines()] if trace.is_file() else []
            observed=[row for row in events if row['kind']=='assertion_read']
            valid=[row for row in observed if row['status']=='observed_within_instrumented_code'
                   and row.get('source_q_span') and row.get('source_allocation_span')
                   and row.get('source_last_observed_writer')]
            comparisons.append(dict(role=role,outcomes_unchanged=outcomes(baseline)==outcomes(report),
                baseline_counts=baseline['counts'],overlay_counts=report['counts'],
                baseline_errors=baseline['errors'],overlay_errors=report['errors'],
                observed_reads=len(observed),valid_mapped_reads=len(valid),
                unknown_reasons=dict(Counter(row['reason'] for row in observed if row['status']=='unknown')),
                events=len(events),trace_sha256=digest(trace) if trace.is_file() else None))
        summaries.append(dict(case=case,status='executed',phases=comparisons,
            correctness_evaluated=False,execution=str(execution.resolve())))
        write(output/'summary.json',summaries)
        print(json.dumps(summaries[-1]),flush=True)
    write(output/'summary.json',summaries)
    write(output/'seal.json',dict(files_sha256={str(p.relative_to(output)):digest(p)
        for p in sorted(output.rglob('*')) if p.is_file() and p.name!='seal.json'}))
    return summaries


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--overlay',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.stage=='prepare':
        print(json.dumps({'selected':[dict(case=r['case'],manifest=r['manifest']) for r in prepare(args.overlay,args.output)['selected']]}))
    else:
        run(args.output)
