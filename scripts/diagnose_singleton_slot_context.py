"""Remove only source_context from all frozen enabled singleton requests.

No prompt regeneration, model-output filtering, new candidates or retries.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search.checkpoint import digest,read,write
from scripts.run_singleton_expected_slots_diagnostic import checked,wire_payload,run


def without_context(request):
    if request.get('thinking')!='enabled' or 'reasoning_effort' in request:
        raise ValueError('Expected enabled request with default reasoning effort')
    old=json.loads(request['prompt'])
    if 'source_context' not in old:
        raise ValueError('Original request has no source_context')
    if json.dumps(old,ensure_ascii=False,separators=(',',':')) != request['prompt']:
        raise ValueError('Original prompt serialization is not the frozen canonical format')
    changed_fields=dict(old)
    removed=changed_fields.pop('source_context')
    prompt=json.dumps(changed_fields,ensure_ascii=False,separators=(',',':'))
    changed=dict(request,prompt=prompt,id=hashlib.sha256(prompt.encode()).hexdigest(),
        prompt_bytes=len(request['system'].encode())+len(prompt.encode()))
    before,after=wire_payload(request),wire_payload(changed)
    if {k:v for k,v in before.items() if k!='messages'} != {k:v for k,v in after.items() if k!='messages'}:
        raise ValueError('Non-prompt provider parameter changed')
    if before['messages'][0]!=after['messages'][0] or any(changed_fields[k]!=v for k,v in old.items() if k!='source_context'):
        raise ValueError('A field other than source_context changed')
    difference=''.join(difflib.unified_diff(
        json.dumps(old,ensure_ascii=False,sort_keys=True,indent=2).splitlines(True),
        json.dumps(changed_fields,ensure_ascii=False,sort_keys=True,indent=2).splitlines(True),
        fromfile='original_enabled_prompt',tofile='without_source_context'))
    return changed,removed,difference


def prepare(source,output):
    old=checked(source/'execution_protocol.json',read(source/'execution_protocol.seal.json')['sha256'])
    checked(source/'protocol.json',old['preparation_protocol_sha256'])
    checked(source/'summary.json',old['preparation_summary_sha256'])
    if old['parent_denominator']!=32 or old['request_limit']!=14:
        raise ValueError('Expected the exact same 32 parents and 14 requests')
    output.mkdir(parents=True,exist_ok=False)
    records=[]
    for original in old['records']:
        row=dict(original)
        if 'request' in original:
            request=checked(original['request'],original['request_sha256'])
            changed,removed,difference=without_context(request)
            path=output/'requests'/Path(original['request']).name
            write(path,changed)
            copied=output/'original_requests'/path.name
            copied.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(original['request'],copied)
            removed_path=output/'prompt_changes'/f'{path.stem}.removed.json'
            write(removed_path,dict(removed_source_context=removed,
                unchanged_prompt_fields_sha256=hashlib.sha256(changed['prompt'].encode()).hexdigest(),
                original_system_sha256=hashlib.sha256(request['system'].encode()).hexdigest()))
            diff_path=removed_path.with_suffix('.diff')
            diff_path.write_text(difference)
            expected=output/'expected_wire_payloads'/path.name
            write(expected,wire_payload(changed))
            row.update(request=str(path.resolve()),request_sha256=digest(path),
                expected_wire_payload=str(expected.resolve()),expected_wire_payload_sha256=digest(expected),
                original_context_request=str(copied.resolve()),original_context_request_sha256=digest(copied),
                original_prompt_bytes=request['prompt_bytes'],prompt_bytes=changed['prompt_bytes'],
                prompt_diff=str(diff_path.resolve()),prompt_diff_sha256=digest(diff_path),
                removed_context=str(removed_path.resolve()),removed_context_sha256=digest(removed_path),
                baseline_completion=str(source/'completions'/path.stem))
        records.append(row)
    code={}
    for relative in set(old['code_sha256'])|{'scripts/diagnose_singleton_slot_context.py'}:
        path=output/'algorithm_snapshot'/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,path)
        code[relative]=digest(ROOT/relative)
    preparation=dict(created_utc=datetime.now(timezone.utc).isoformat(),
        source_protocol=str((source/'execution_protocol.json').resolve()),
        source_protocol_sha256=digest(source/'execution_protocol.json'),
        intervention='Delete only the source_context JSON field from the already frozen prompt.',
        prompts_regenerated_from_current_frontend=False,
        system_and_other_prompt_fields_identical=True,
        selection='all 14 frozen enabled requests in original order; no outcome-based inclusion',
        original_unsupported_parents_retained=True,code_sha256=code)
    write(output/'protocol.json',preparation)
    write(output/'protocol.seal.json',dict(sha256=digest(output/'protocol.json')))
    write(output/'summary.json',dict(finished=True,frozen_parent_count=32,prepared_requests=14,
        provider_calls=0,records=records))
    write(output/'summary.seal.json',dict(sha256=digest(output/'summary.json')))
    protocol=dict(old,records=records,created_utc=datetime.now(timezone.utc).isoformat(),
        preparation_protocol_sha256=digest(output/'protocol.json'),
        preparation_summary_sha256=digest(output/'summary.json'),
        code_sha256=code,max_workers=2,launch_window_seconds=600,retries=0,
        authorization='Existing user authorization for all 17 trials and provider; coordinator explicitly authorized this source-context-only ablation.',
        selection=preparation['selection'],provider_parameters_changed=False,
        changed_parameters={'prompt':'source_context field removed; every other field and system identical'},
        correctness_evaluated=False)
    write(output/'execution_protocol.json',protocol)
    write(output/'execution_protocol.seal.json',dict(sha256=digest(output/'execution_protocol.json')))
    return dict(requests=14,parents=32,external_model_calls=0,
        protocol_sha256=digest(output/'execution_protocol.json'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.stage=='prepare':
        if args.source is None:parser.error('--source is required for prepare')
        result=prepare(args.source,args.output)
    else:
        result=run(args.output)
    print(json.dumps(result),flush=True)
