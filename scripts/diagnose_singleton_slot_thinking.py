"""Paired enabled-thinking control over every frozen v3 expected-slot request.

The sole wire change is thinking disabled -> enabled. No labels or completions
are used to include requests. The existing bounded runner and adapter are reused.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search.checkpoint import digest,read,write
from scripts.run_singleton_expected_slots_diagnostic import checked,wire_payload,run


def change_thinking(request):
    if request.get('thinking') != 'disabled' or 'reasoning_effort' in request:
        raise ValueError('Expected unchanged disabled baseline with default reasoning effort')
    changed = dict(request,thinking='enabled')
    before,after = wire_payload(request),wire_payload(changed)
    if {k:v for k,v in before.items() if k!='thinking'} != {k:v for k,v in after.items() if k!='thinking'}:
        raise ValueError('Unexpected wire difference')
    return changed


def prepare(source,output):
    original = checked(source/'execution_protocol.json',read(source/'execution_protocol.seal.json')['sha256'])
    checked(source/'protocol.json',original['preparation_protocol_sha256'])
    checked(source/'summary.json',original['preparation_summary_sha256'])
    if original['parent_denominator'] != 32 or original['request_limit'] != 14:
        raise ValueError('Expected the same frozen 32 parents and 14 requests')
    output.mkdir(parents=True,exist_ok=False)
    records=[]
    for parent in original['records']:
        row=dict(parent)
        if 'request' in parent:
            old=checked(parent['request'],parent['request_sha256'])
            changed=change_thinking(old)
            target=output/'requests'/Path(parent['request']).name
            write(target,changed)
            wire=output/'expected_wire_payloads'/target.name
            write(wire,wire_payload(changed))
            original_copy=output/'original_requests'/target.name
            original_copy.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(parent['request'],original_copy)
            row.update(request=str(target.resolve()),request_sha256=digest(target),thinking='enabled',
                expected_wire_payload=str(wire.resolve()),expected_wire_payload_sha256=digest(wire),
                original_disabled_request=str(original_copy.resolve()),
                original_disabled_request_sha256=digest(original_copy),
                baseline_completion=str(source/'completions'/target.stem))
        records.append(row)
    code={}
    for relative in set(original['code_sha256'])|{'scripts/diagnose_singleton_slot_thinking.py'}:
        target=output/'algorithm_snapshot'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,target)
        code[relative]=digest(ROOT/relative)
    preparation=dict(created_utc=datetime.now(timezone.utc).isoformat(),
        source_execution_protocol=str((source/'execution_protocol.json').resolve()),
        source_execution_protocol_sha256=digest(source/'execution_protocol.json'),
        sole_wire_change={'thinking':{'before':'disabled','after':'enabled'}},
        system_prompt_source_identical=True,source_inventory_selected_without_outcomes=True,
        labels_or_response_values_used_for_selection=False,
        adapter_change='Postfreeze input-overlap exclusion only; paired 14 old responses checked locally identical.',
        adapter_change_audit=str((ROOT/'results/relation_search_20260929/singleton_expected_slots_postfreeze_fix_v1/audit.json').resolve()),
        adapter_change_audit_sha256=digest(ROOT/'results/relation_search_20260929/singleton_expected_slots_postfreeze_fix_v1/audit.json'),
        code_sha256=code)
    write(output/'protocol.json',preparation)
    write(output/'protocol.seal.json',dict(sha256=digest(output/'protocol.json')))
    summary=dict(finished=True,frozen_parent_count=32,prepared_requests=14,records=records,provider_calls=0)
    write(output/'summary.json',summary)
    write(output/'summary.seal.json',dict(sha256=digest(output/'summary.json')))
    execution=dict(original,created_utc=datetime.now(timezone.utc).isoformat(),records=records,
        preparation_protocol_sha256=digest(output/'protocol.json'),
        preparation_summary_sha256=digest(output/'summary.json'),
        selection='all 14 requests from frozen v3; exact original order; 18 unsupported parents retained',
        authorization='Existing user authorization for all 17 trials and provider; coordinator authorized this thinking-only control.',
        code_sha256=code,max_workers=2,launch_window_seconds=600,retries=0,
        thinking='enabled',provider_parameters_changed=True,
        changed_parameters={'thinking':{'before':'disabled','after':'enabled'}},
        correctness_evaluated=False)
    write(output/'execution_protocol.json',execution)
    write(output/'execution_protocol.seal.json',dict(sha256=digest(output/'execution_protocol.json')))
    return dict(requests=14,parents=32,external_model_calls=0,protocol_sha256=digest(output/'execution_protocol.json'))


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.stage=='prepare':
        if args.source is None:
            parser.error('--source is required for prepare')
        result=prepare(args.source,args.output)
    else:
        result=run(args.output)
    print(json.dumps(result),flush=True)
