"""Test a uniform compiler-directed observation projection on paired reports.

The cohort is every report supplied in the input directory. Prior runtime
results and evaluation labels are never read by this component. A projection
must pass another paired compile and a fresh complete-program review before
native execution. This is a bounded construction experiment, not a detector.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import checkpoint,compact_admission,type_observer_projection
from relation_search.checkpoint import read,digest
from scripts import run_test_admission as admission
from scripts import inspect_typescript_candidate as compiler
from scripts.run_expected_slot_search import context_review
from scripts.run_contract_repair_search import Budget,execute,write,frozen,verify,native_runner


VERSION='paired-compiler-projection-component.v1'


def prepare(args):
    root=args.output;root.mkdir(parents=True,exist_ok=False);cases=[]
    for report_path in sorted(args.reports.glob('*/executed/types.json')):
        report_root=report_path.parent.parent;prior=read(report_root/'prepared.json')
        artifact=Path(prior['artifact']['path']).parent
        source=artifact.parent.parent/'prepared'
        candidates=read(source/'candidates.json')['candidates']
        if len(candidates)!=1:raise ValueError('One fixed input program is required')
        plan=read(report_root/'plan.json')
        generated=next(row for row in plan['phases'] if row['role']=='generated')
        files=[row for row in generated['files'] if row['target']==plan['target']]
        if len(files)!=1:raise ValueError('Ambiguous generated source')
        mount=next(row for row in prior['mounts'] if row['target']==files[0]['staged'])
        if digest(mount['source'])!=mount['sha256']:raise ValueError('Changed emitted source')
        inputs={name:frozen(source/name) for name in ('corpus.json','frontend.json','candidates.json','case.json','selection.json','issue.md')}
        inputs.update(compiler_report=frozen(report_path),emitted_source=frozen(Path(mount['source'])))
        cases.append(dict(case=prior['case'],source=str(source.resolve()),inputs=inputs))
    if not cases:raise ValueError('No paired compiler reports')
    for module in (type_observer_projection,compact_admission):admission._preload_local_imports(module)
    protocol=dict(version=VERSION,cases=cases,algorithm=admission._loaded_sources(),
        cohort='every_report_in_the_supplied_directory',gate='compact',source_enrichment=True,
        max_model_calls=len(cases),max_total_tokens=300000,max_prompt_bytes=96000,
        review_output_tokens=16384,thinking='enabled',reasoning_effort='high',
        timeout=180,deadline_utc=args.deadline_utc,
        runtime_outcomes_read_for_projection=False,native_feedback_sent_to_provider=False,
        evaluator_truth_used=False,created_utc=datetime.now(timezone.utc).isoformat())
    write(root/'prepared.json',protocol);write(root/'seal.json',frozen(root/'prepared.json'))
    return dict(cases=len(cases),prepared=frozen(root/'prepared.json'))


def emit(candidate,source,directory,protocol):
    prepared=directory/'prepared';prepared.mkdir(parents=True,exist_ok=False)
    for name in ('corpus.json','frontend.json','case.json','selection.json','issue.md'):
        (prepared/name).symlink_to((source/name).resolve())
    checkpoint.write(prepared/'candidates.json',dict(candidates=[candidate]))
    checkpoint.write(prepared/'prepare.json',dict(files_sha256={path.name:digest(path) for path in prepared.iterdir() if path.is_file()}))
    checkpoint.seal(prepared,dict(status='single_fixed_projected_program_pending_validation'))
    native_runner.emit_batch(SimpleNamespace(input=prepared,output=directory/'emitted',
        timeout=protocol['timeout'],group_size=1,isolate_go_compilation=True,
        dependency_packages_root=ROOT/'data/relational_gap_v1_dependency_packages'))
    artifacts=sorted((directory/'emitted').glob('group_*/manifest.json'))
    if len(artifacts)!=1:raise ValueError('Projection did not emit one program')
    return artifacts[0].parent


def run(args):
    root=args.input;verify(read(root/'seal.json'));protocol=read(root/'prepared.json')
    admission.verify_seal(protocol['algorithm']);budget=Budget(root,protocol);results=[]
    for entry in protocol['cases']:
        directory=root/'cases'/entry['case']/'candidate_0001'
        if (directory/'outcome.json').exists():
            results.append(read(directory/'outcome.json'));continue
        for receipt in entry['inputs'].values():verify(receipt)
        inputs=entry['inputs'];source=Path(entry['source'])
        corpus=read(inputs['corpus.json']['path']);frontend=read(inputs['frontend.json']['path'])
        candidate=read(inputs['candidates.json']['path'])['candidates'][0]
        report=read(inputs['compiler_report']['path']);emitted=Path(inputs['emitted_source']['path']).read_text()
        projection=type_observer_projection.project(corpus,frontend,candidate,report,emitted)
        chosen=projection.pop('candidate');write(directory/'projection.json',projection)
        outcome=dict(case=entry['case'],projection=projection,alert=None)
        if chosen is not None:
            write(directory/'selected_program.json',chosen)
            artifact=emit(chosen,source,directory/'native',protocol)
            compiler.prepare(artifact,directory/'compiler_recheck')
            checked=compiler.run(directory/'compiler_recheck',protocol['timeout'])
            write(directory/'compiler_recheck/outcome.json',checked);outcome['compiler_recheck']=checked
            errors=[r for r in checked.get('new_diagnostics',[]) if r['category']=='Error']
            if checked['status']=='compiler_completed' and not errors:
                corpus,enrichment=admission._enrich(corpus,frontend,{chosen['id']:chosen},str(source/'corpus.json'),directory,0)
                write(directory/'enrichment.json',enrichment)
                review=context_review(corpus,frontend,chosen,(source/'issue.md').read_text(),protocol)
                request=review.pop('request');write(directory/'review/analysis.json',review)
                if request:
                    request=admission._configure_request(request,SimpleNamespace(thinking='enabled',output_token_limit=16384,reasoning_effort='high'))
                    write(directory/'review/request.json',request)
                    content,receipt=budget.call(request,directory/'review')
                    decision=(compact_admission.decide(request,content,finish_reason=receipt.get('finish_reason')) if content is not None else dict(status='unknown',alarm_eligible=False))
                else:decision=dict(status=review['status'],alarm_eligible=False)
                write(directory/'review/decision.json',decision);outcome['review']=decision
                if decision.get('alarm_eligible'):
                    native=execute(chosen,source,corpus,directory/'native',protocol)
                    outcome['native']=native
                    if native['controlled_failure']:
                        outcome['alert']=dict(program=frozen(directory/'selected_program.json'),native=frozen(directory/'native/native_outcome.json'),validity='pending_independent_audit')
        write(directory/'outcome.json',outcome);results.append(outcome)
        print(json.dumps(dict(case=entry['case'],projection=projection,alert=bool(outcome['alert']))),flush=True)
    admission.verify_seal(protocol['algorithm'])
    summary=dict(version=VERSION,results=results,**budget.totals(),completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json',summary)
    return dict(cases=len(results),projected=sum(r['projection']['status']=='projected' for r in results),alerts=sum(bool(r['alert']) for r in results),**budget.totals())


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('stage',choices=['prepare','run'])
    p.add_argument('--reports',type=Path);p.add_argument('--output',type=Path);p.add_argument('--input',type=Path)
    p.add_argument('--deadline-utc',default='2026-10-03T20:00:00Z');a=p.parse_args()
    print(json.dumps(prepare(a) if a.stage=='prepare' else run(a)))
