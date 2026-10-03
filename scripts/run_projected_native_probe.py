"""Execute every statically rechecked projection as an offline construction probe.

No semantic gate or external model is invoked. Native failures remain unverified
construction results. This component emits no detector alerts. Independent
complete-program audits must be recorded separately.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search.checkpoint import read
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import execute,write,frozen,verify


VERSION='all-rechecked-projections-native-probe.v1'


def prepare(args):
    root=args.output;root.mkdir(parents=True,exist_ok=False)
    census=read(args.census/'prepared.json');summary=read(args.census/'summary.json')
    source={(r['case'],r['occurrence']):r for r in census['items']};items=[];excluded=[]
    for row in summary['items']:
        if row.get('projection',{}).get('status')!='projected':continue
        compiled=row['projected_compile']
        if compiled['status']!='compiler_completed':
            excluded.append(dict(case=row['case'],occurrence=row['occurrence'],reason='compiler_unavailable'));continue
        report=read(compiled['report']['path']);generated=next(p for p in report['phases'] if p['role']=='generated')
        if (report['configuration']['parse_errors'] or generated['options_diagnostics']
                or any(d['category']=='Error' for d in report['new_diagnostics'])):
            excluded.append(dict(case=row['case'],occurrence=row['occurrence'],reason='new_or_configuration_type_errors'));continue
        prior=source[row['case'],row['occurrence']]
        directory=args.census/'cases'/row['case']/row['occurrence']
        items.append(dict(case=row['case'],occurrence=row['occurrence'],source=prior['source'],
            candidate=frozen(directory/'projected_program.json'),compiler_report=compiled['report'],inputs=prior['inputs']))
    admission._preload_local_imports(sys.modules['scripts.run_contract_repair_search'])
    protocol=dict(version=VERSION,items=items,excluded=excluded,census=frozen(args.census/'summary.json'),
        algorithm=admission._loaded_sources(),timeout=180,external_model_calls=0,reported_alerts=0,
        native_output_role='Construction result only, never expected-value evidence.',
        selection='Every projection with a completed compiler recheck and zero new/configuration errors.',
        evaluation_labels_used=False,created_utc=datetime.now(timezone.utc).isoformat())
    write(root/'prepared.json',protocol);write(root/'seal.json',frozen(root/'prepared.json'))
    return dict(programs=len(items),excluded=len(excluded),prepared=frozen(root/'prepared.json'))


def run(args):
    root=args.input;verify(read(root/'seal.json'));protocol=read(root/'prepared.json')
    admission.verify_seal(protocol['algorithm']);results=[]
    for item in protocol['items']:
        directory=root/'cases'/item['case']/item['occurrence']
        if (directory/'outcome.json').exists():results.append(read(directory/'outcome.json'));continue
        for receipt in (item['candidate'],item['compiler_report'],*item['inputs'].values()):verify(receipt)
        candidate=read(item['candidate']['path']);source=Path(item['source']);corpus=read(source/'corpus.json')
        native=execute(candidate,source,corpus,directory/'native',protocol)
        outcome=dict(case=item['case'],occurrence=item['occurrence'],candidate=item['candidate'],native=native,
            semantic_validity='unconfirmed',alert=False)
        write(directory/'outcome.json',outcome);results.append(outcome)
        print(json.dumps(dict(case=item['case'],occurrence=item['occurrence'],controlled_failure=native['controlled_failure'],alert=False)),flush=True)
    admission.verify_seal(protocol['algorithm'])
    summary=dict(version=VERSION,items=results,external_model_calls=0,reported_alerts=0,
        completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json',summary)
    return dict(programs=len(results),controlled_failures=sum(r['native']['controlled_failure'] for r in results),reported_alerts=0)


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('stage',choices=['prepare','run'])
    p.add_argument('--census',type=Path);p.add_argument('--output',type=Path);p.add_argument('--input',type=Path)
    a=p.parse_args();print(json.dumps(prepare(a) if a.stage=='prepare' else run(a)))
