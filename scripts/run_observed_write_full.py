"""Frozen full-overlay validation, one dedicated offline Docker slot."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search.checkpoint import digest,read,write
from combination_testing.test_reports import parse_report
from scripts.run_relational_gap_case import run_case


def files(root):
    return {str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def prepare(overlay,smoke,output):
    output.mkdir(parents=True,exist_ok=False)
    prior=read(smoke/'protocol.json')
    reused={r['source_manifest']:r for r in prior['selected']}
    selected=[]
    groups=sorted(read(overlay/'summary.json')['groups'],key=lambda g:g['manifest'])
    for group in groups:
        manifest=read(group['manifest'])
        source=Path(manifest['observation_overlay']['source_manifest'])
        baseline=source.parent.parent.parent/'executed'/source.parent.name
        if not (baseline/'execution.json').is_file():
            raise ValueError('Uninstrumented baseline missing: '+str(baseline))
        folder=output/group['case']/source.parent.name
        folder.mkdir(parents=True)
        shutil.copytree(baseline,folder/'baseline')
        reused_from=None
        if str(source) in reused:
            previous=reused[str(source)]
            if previous['manifest_sha256']!=digest(group['manifest']):
                raise ValueError('Smoke overlay changed')
            reused_from=smoke/group['case']/'execution'
            shutil.copytree(reused_from,folder/'execution')
        selected.append(dict(case=group['case'],group=source.parent.name,
            output=str(folder.resolve()),manifest=group['manifest'],manifest_sha256=digest(group['manifest']),
            source_manifest=str(source),source_manifest_sha256=digest(source),
            baseline_original=str(baseline),baseline_files_sha256=files(folder/'baseline'),
            reused_execution_from=str(reused_from.resolve()) if reused_from else None,
            reused_execution_files_sha256=files(folder/'execution') if reused_from else None))
    scripts=[Path(__file__),ROOT/'scripts/run_relational_gap_case.py',ROOT/'vendor/replay/container_replay.py']
    protocol=dict(version=1,extension_of=str(smoke.resolve()),
        differs_from_initial_smoke='all 32 supplied groups, including zero-mapped-q groups; directory order; reuse the two completed smoke executions',
        selection='all supplied overlay groups sorted by manifest path; no target or outcome filtering',
        max_project_experiment_containers=5,dedicated_new_concurrency=1,
        per_container=dict(cpus=2,memory_gib=8,network='none'),
        deadline_utc='2026-09-29T08:12:36+00:00',provider_calls=0,
        selected=selected,overlay_seal_sha256=digest(overlay/'seal.json'),
        initial_smoke_protocol_sha256=digest(smoke/'protocol.json'),
        initial_smoke_seal_sha256=digest(smoke/'seal.json'),
        code_sha256={str(p.relative_to(ROOT)):digest(p) for p in scripts})
    write(output/'protocol.json',protocol)
    write(output/'protocol.seal.json',dict(sha256=digest(output/'protocol.json')))
    return dict(groups=len(selected),reused=sum(bool(r['reused_execution_from']) for r in selected))


def compare(selection,manifest):
    folder=Path(selection['output']);execution=folder/'execution'
    result=read(execution/'execution.json')
    comparisons=[]
    for phase in manifest['phases']:
        role=phase['role']
        items=manifest['controls'] if role=='control' else manifest.get('profile_obligations',[]) if role=='source_profile' else manifest['obligations']
        report=parse_report(execution/role,phase['report'],
            read(execution/role/'result.json') if (execution/role/'result.json').exists() else result,
            selected_names=[row['id'] for row in items])
        # Keep native and copied artifacts unchanged; normalization is separate.
        write(folder/'comparison_reports'/role/'normalized.json',report)
        baseline=read(folder/'baseline'/role/'normalized.json')
        outcomes=lambda value:sorted((row['id'],row['status']) for row in value['tests'])
        trace=execution/role/'observed_writes.jsonl'
        events=[json.loads(line) for line in trace.read_text().splitlines()] if trace.is_file() else []
        observed=[row for row in events if row['kind']=='assertion_read']
        valid=[row for row in observed if row['status']=='observed_within_instrumented_code'
               and row.get('source_q_span') and row.get('source_allocation_span') and row.get('source_last_observed_writer')]
        comparisons.append(dict(role=role,outcomes_unchanged=outcomes(baseline)==outcomes(report),
            baseline_counts=baseline['counts'],overlay_counts=report['counts'],
            baseline_errors=baseline['errors'],overlay_errors=report['errors'],
            baseline_outcomes=outcomes(baseline),overlay_outcomes=outcomes(report),
            observed_reads=len(observed),valid_mapped_reads=len(valid),events=len(events),
            unknown_reasons=dict(Counter(row['reason'] for row in observed if row['status']=='unknown')),
            trace_sha256=digest(trace) if trace.is_file() else None))
    record=dict(case=selection['case'],group=selection['group'],status='executed',
        reused_execution_from=selection['reused_execution_from'],phases=comparisons,
        correctness_evaluated=False,execution=str(execution.resolve()))
    write(folder/'comparison.json',record)
    write(folder/'evidence_sha256.json',dict(execution=files(execution),
          baseline=selection['baseline_files_sha256']))
    return record


def run(output):
    protocol=read(output/'protocol.json')
    if digest(output/'protocol.json')!=read(output/'protocol.seal.json')['sha256']:
        raise ValueError('Frozen extension protocol changed')
    deadline=datetime.fromisoformat(protocol['deadline_utc'])
    summaries=[]
    for selection in protocol['selected']:
        folder=Path(selection['output'])
        if (folder/'comparison.json').exists():
            record=read(folder/'comparison.json')
            evidence=read(folder/'evidence_sha256.json')
            if files(folder/'execution')!=evidence['execution'] or files(folder/'baseline')!=evidence['baseline']:
                raise ValueError('Completed comparison evidence changed')
            summaries.append(record)
            continue
        if digest(selection['manifest'])!=selection['manifest_sha256']:
            raise ValueError('Overlay manifest changed')
        if files(folder/'baseline')!=selection['baseline_files_sha256']:
            raise ValueError('Baseline changed')
        manifest=read(selection['manifest'])
        execution=folder/'execution'
        if selection['reused_execution_from']:
            if files(execution)!=selection['reused_execution_files_sha256']:
                raise ValueError('Reused smoke evidence changed')
        elif not (execution/'execution.json').exists():
            if execution.exists():
                raise ValueError('Incomplete execution requires explicit live-process audit')
            while True:
                remaining=(deadline-datetime.now(timezone.utc)).total_seconds()
                if remaining<manifest['timeout']+120:
                    write(output/'stopped.json',dict(reason='remaining_deadline_budget',pending=selection))
                    write(output/'summary.json',summaries)
                    return
                current=subprocess.run(['docker','ps','--format','{{.ID}} {{.Names}}'],check=True,text=True,capture_output=True)
                active=[line for line in current.stdout.splitlines() if line.split()[1].startswith('relational-gap-')]
                write(folder/'pre_dispatch_containers.json',dict(project_experiments=active,
                    other_container_count=len(current.stdout.splitlines())-len(active)))
                if len(active)<protocol['max_project_experiment_containers']:break
                time.sleep(5)
            for mount in manifest['mounts']:
                if digest(mount['source'])!=mount['sha256']:raise ValueError('Overlay mount changed')
            run_case(selection['case'],manifest['command'],mounts=manifest['mounts'],timeout=manifest['timeout'],
                     output=execution,registry=ROOT/'data/relational_gap_v1/registry.json')
        record=compare(selection,manifest)
        summaries.append(record)
        write(output/'summary.json',summaries)
        print(json.dumps(dict(case=record['case'],group=record['group'],
            reused=bool(record['reused_execution_from']),
            outcomes_unchanged=all(row['outcomes_unchanged'] for row in record['phases']),
            valid_mapped_reads=sum(row['valid_mapped_reads'] for row in record['phases']),
            unknown_reads=sum(row['observed_reads']-row['valid_mapped_reads'] for row in record['phases']))),flush=True)
    write(output/'summary.json',summaries)
    write(output/'seal.json',dict(files_sha256={str(p.relative_to(output)):digest(p)
         for p in sorted(output.rglob('*')) if p.is_file() and p.name!='seal.json'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--overlay',type=Path)
    parser.add_argument('--smoke',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.stage=='prepare':print(json.dumps(prepare(args.overlay,args.smoke,args.output)))
    else:run(args.output)
