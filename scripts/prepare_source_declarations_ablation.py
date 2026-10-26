"""Prepare outcome-blind source-declarations prompts; never dispatch a model."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prototypes.source_declarations_context import CHANGED_FIELDS, POLICY, transform, verify_declaration_sources
from relation_search.checkpoint import digest, read, start, write


def candidate_id(request):
    if len(request['offered']) != 1:
        raise ValueError('Source presentation ablation requires singleton requests')
    return next(iter(request['offered'].values()))['candidate']['id']


def select_request(semantic):
    """A ready request inventory is fixed before any provider outcomes."""
    selection = semantic/'semantic_selection.json'
    if not selection.exists():
        return None, 'source_requests_not_prepared'
    expected = read(selection)['offered_ids']
    rows = []
    for path in sorted((semantic/'requests').glob('request_[0-9][0-9][0-9].json')):
        request = read(path)
        cid = candidate_id(request)
        rows.append((hashlib.sha256(cid.encode()).hexdigest(), str(path), cid, request))
    if sorted(row[2] for row in rows) != sorted(expected):
        return None, 'source_request_inventory_incomplete'
    if not rows:
        return None, 'no_source_requests'
    _, path, cid, request = sorted(rows)[0]
    return (Path(path), cid, request), None


def prepare(ablation, output, frozen_root):
    ablation, output, frozen_root = Path(ablation).resolve(), Path(output).resolve(), Path(frozen_root).resolve()
    original = read(ablation/'stage.json')
    campaign = Path(original['campaign'])
    if digest(campaign/'configuration.json') != original['configuration_sha256']:
        raise ValueError('Original campaign configuration changed')
    for path, checksum in original['code_sha256'].items():
        if digest(path) != checksum:
            raise ValueError('Frozen paired ablation code changed')
    code = [Path(__file__), ROOT/'prototypes/source_declarations_context.py', ROOT/'relation_search/instrument.py']
    driver = frozen_root/'scripts/relation_search_semantics.py'
    provider = frozen_root/'relational_gap/provider.py'
    for path in (driver, provider):
        if digest(path) != original['code_sha256'][str(path)]:
            raise ValueError('Third arm must use the same frozen dispatch driver and provider')
    protocol = dict(policy=POLICY, ablation=str(ablation), ablation_stage_sha256=digest(ablation/'stage.json'),
        campaign=str(campaign), configuration_sha256=original['configuration_sha256'], cases=original['cases'],
        sample='first singleton candidate in SHA256(candidate.id) order per case, same first pair as context_ablation',
        per_case=1, max_requests=len(original['cases']), changed_prompt_fields=CHANGED_FIELDS,
        declarations='same local analysis_evidence; complete spans only, byte-checked containment deduplication',
        local_analysis_evidence='retained exactly', provider_calls=0, semantic_output_used_for_selection=False,
        feedback_into_main_campaign=False, code_sha256={str(path):digest(path) for path in code},
        frozen_driver=str(driver), frozen_driver_sha256=digest(driver), provider_sha256=digest(provider))
    start(output, protocol)
    for path in code:
        relative = path.relative_to(ROOT)
        destination = output/'algorithm_snapshot'/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and digest(destination) != digest(path):
            raise ValueError('Frozen converter snapshot changed')
        if not destination.exists():
            shutil.copyfile(path, destination)
    records, pending = [], []
    for case in original['cases']:
        semantic = campaign/case/'round_000/semantic'
        chosen, reason = select_request(semantic)
        if chosen is None:
            pending.append(dict(case=case, reason=reason))
            continue
        path, cid, request = chosen
        pair_path = ablation/case/'result.json'
        matched_pair = None
        if pair_path.exists():
            pairs = read(pair_path)['pairs']
            if not pairs or pairs[0]['candidate_id'] != cid or Path(pairs[0]['treatment_request']) != path:
                raise ValueError('SHA-first request differs from the paired context ablation')
            matched_pair = pairs[0]
            if digest(path) != matched_pair['treatment_request_sha256']:
                raise ValueError('Original treatment request changed')
        wire_path = semantic/'completions'/path.stem/'request.json'
        if not wire_path.exists():
            pending.append(dict(case=case, reason='selected_original_wire_not_materialized', candidate_id=cid))
            continue
        wire = read(wire_path)  # Inputs only: no response, completion or validation is opened.
        if wire['messages'] != [dict(role='system',content=request['system']),dict(role='user',content=request['prompt'])]:
            raise ValueError('Treatment wire does not match its prepared request')
        corpus_path = Path(request['source_prepared'])/'corpus.json'
        verified = verify_declaration_sources(request, read(corpus_path))
        changed, stats = transform(request)
        preview = copy.deepcopy(wire)
        preview['messages'][1]['content'] = changed['prompt']
        destination = output/case
        request_path = destination/'request.json'
        if request_path.exists() and read(request_path) != changed:
            raise ValueError('Prepared third-arm request changed')
        write(request_path, changed)
        write(destination/'wire_preview.json', preview)
        write(destination/'declaration_verification.json', verified)
        write(destination/'stats.json', stats)
        record = dict(case=case, candidate_id=cid, candidate_sha256=hashlib.sha256(cid.encode()).hexdigest(),
            treatment_request=str(path), treatment_request_sha256=digest(path),
            paired_control_request=matched_pair['control_request'] if matched_pair else None,
            paired_control_alignment='verified_first_pair' if matched_pair else 'same_frozen_sampling_rule_pair_pending',
            original_wire=str(wire_path), original_wire_sha256=digest(wire_path),
            corpus_sha256=digest(corpus_path), request=str(request_path), request_sha256=digest(request_path),
            wire_preview_sha256=digest(destination/'wire_preview.json'), model_settings={key:value for key,value in wire.items() if key!='messages'},
            verified_declarations=len(verified), stats=stats,
            command=[str(frozen_root/'.venv/bin/python'),str(driver),'complete','--input',str(request_path),
                     '--output',str(destination/'completion')])
        write(destination/'record.json', record)
        records.append(record)
    result = dict(status='ready' if not pending else 'pending_source_inputs', prepared=len(records),
        expected=len(original['cases']), pending=pending, records=records, provider_calls=0,
        total_original_prompt_bytes=sum(row['stats']['original_prompt_bytes'] for row in records),
        total_prompt_bytes=sum(row['stats']['prompt_bytes'] for row in records))
    write(output/'ready.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--ablation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frozen-root', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.ablation, args.output, args.frozen_root)
    print(json.dumps({key:value for key,value in result.items() if key!='records'}))
