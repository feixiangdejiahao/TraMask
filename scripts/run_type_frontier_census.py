"""Compile every emitted TypeScript test in a frozen search frontier.

No provider call or subject-test execution occurs. Candidate selection uses
language and emission availability only. Native outcomes and truth labels are
not inputs. Observation projections are compiled again as separate programs.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import type_observer_projection
from relation_search.candidate_edit_transport import verify_emission
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts import inspect_typescript_candidate as compiler
from scripts.run_type_projection_component import emit
from scripts.run_contract_repair_search import write,frozen,verify


VERSION='typescript-emitted-frontier-census.v2'


def prepare(args):
    root=args.output;root.mkdir(parents=True,exist_ok=False);items=[]
    for manifest in sorted(args.frontier.glob('cases/*/candidate_*/native/emitted/group_*/manifest.json')):
        artifact=manifest.parent;source=artifact.parent.parent/'prepared'
        corpus=read(source/'corpus.json')
        if corpus['language']!='typescript':continue
        candidates=read(source/'candidates.json')['candidates']
        if len(candidates)!=1:raise ValueError('One candidate per emitted group required')
        case=read(manifest)['case'];directory=artifact.parent.parent.parent.name
        item=dict(case=case,occurrence=directory,source=str(source.resolve()),artifact=str(artifact.resolve()),
                  inputs={name:frozen(source/name) for name in ('corpus.json','frontend.json','candidates.json','case.json','selection.json','issue.md')})
        item['inputs'].update(manifest=frozen(manifest),phase_plan=frozen(artifact/'phase_plan.json'))
        items.append(item)
    if not items:raise ValueError('No emitted TypeScript programs')
    admission._preload_local_imports(type_observer_projection)
    protocol=dict(version=VERSION,items=items,algorithm=admission._loaded_sources(),
        projection_version=type_observer_projection.VERSION,timeout=180,
        selection='Every emitted TypeScript program, ordered by source path.',
        label_selection=False,native_outcomes_read=False,external_model_calls=0,
        exact_emitted_test_ast_required=True,
        subject_test_execution=False,projection_semantics='new weaker test; validity remains unconfirmed',
        created_utc=datetime.now(timezone.utc).isoformat())
    write(root/'prepared.json',protocol);write(root/'seal.json',frozen(root/'prepared.json'))
    return dict(programs=len(items),prepared=frozen(root/'prepared.json'))


def emitted_source(prepared,report):
    plan=read(Path(prepared)/'plan.json');p=read(Path(prepared)/'prepared.json')
    phase=next(row for row in plan['phases'] if row['role']=='generated')
    file=next(row for row in phase['files'] if row['target']==report['target'])
    mount=next(row for row in p['mounts'] if row['target']==file['staged'])
    return Path(mount['source']).read_text()


def run(args):
    root=args.input;verify(read(root/'seal.json'));protocol=read(root/'prepared.json')
    admission.verify_seal(protocol['algorithm']);results=[]
    for item in protocol['items']:
        directory=root/'cases'/item['case']/item['occurrence']
        if (directory/'result.json').exists():
            results.append(read(directory/'result.json'));continue
        for receipt in item['inputs'].values():verify(receipt)
        outcome=dict(case=item['case'],occurrence=item['occurrence'])
        source=Path(item['source']);corpus=read(source/'corpus.json');frontend=read(source/'frontend.json')
        candidate=read(source/'candidates.json')['candidates'][0]
        transport=verify_emission(corpus,candidate,Path(item['artifact']));outcome['original_transport']=transport
        if transport['status']!='matched':
            outcome['original_compile']=dict(status='program_transport_mismatch',new_diagnostics=[])
            write(directory/'result.json',outcome);results.append(outcome);continue
        original=directory/'original'
        if not (original/'prepared.json').exists():compiler.prepare(Path(item['artifact']),original)
        if (original/'outcome.json').exists():compiled=read(original/'outcome.json')
        else:
            compiled=compiler.run(original,protocol['timeout']);write(original/'outcome.json',compiled)
        outcome['original_compile']=compiled
        if compiled['status']=='compiler_completed':
            report=read(compiled['report']['path'])
            projection=type_observer_projection.project(corpus,frontend,candidate,report,emitted_source(original,report))
            chosen=projection.pop('candidate');outcome['projection']=projection
            if chosen:
                write(directory/'projected_program.json',chosen)
                artifact=emit(chosen,source,directory/'projected',protocol)
                transport=verify_emission(corpus,chosen,artifact);outcome['projected_transport']=transport
                if transport['status']=='matched':
                    recheck=directory/'recheck';compiler.prepare(artifact,recheck)
                    checked=compiler.run(recheck,protocol['timeout']);write(recheck/'outcome.json',checked)
                else:checked=dict(status='program_transport_mismatch',new_diagnostics=[])
                outcome['projected_compile']=checked
        write(directory/'result.json',outcome);results.append(outcome)
        print(json.dumps(dict(case=item['case'],occurrence=item['occurrence'],new_errors=len(compiled.get('new_diagnostics',[])),projection=outcome.get('projection'))),flush=True)
    admission.verify_seal(protocol['algorithm'])
    summary=dict(version=VERSION,items=results,external_model_calls=0,subject_test_execution=False,
                 completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json',summary)
    return dict(programs=len(results),projections=sum(r.get('projection',{}).get('status')=='projected' for r in results))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('stage',choices=['prepare','run'])
    p.add_argument('--frontier',type=Path);p.add_argument('--output',type=Path);p.add_argument('--input',type=Path)
    a=p.parse_args();print(json.dumps(prepare(a) if a.stage=='prepare' else run(a)))
