"""Write explicit root decisions and immutable source receipts, not infer labels."""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent


def read(path):
    return json.loads(path.read_text())


def receipt(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def start(cid, primary='A'):
    raw = {who: (OBS / f'reviewer_{who}/{cid}.json').read_bytes() for who in ['A', 'B']}
    reviews = {who: json.loads(value) for who, value in raw.items()}
    if any(r['case_id'] != cid for r in reviews.values()) or reviews['A']['trial'] != reviews['B']['trial']:
        raise ValueError('independent_review_identity_mismatch')
    base = reviews[primary]
    d = {key: copy.deepcopy(base[key]) for key in ['case_id', 'trial', 'task', 'known_case',
        'target_operation', 'required_factor_inventory', 'agent_base_units', 'missing_factors', 'oracle_availability']}
    d.update(schema_version='fragment-observation-adjudication.v1', status='complete',
             adjudicator='Codex /root', reviews={})
    d['minimal_assembly'] = {
        'proposed_source_units': base['minimal_assembly']['distinct_historical_source_units_including_base'],
        'proposed_transferred_fragments': base['minimal_assembly']['transferred_fragments'],
        'new_semantic_elements': base['minimal_assembly']['new_semantic_elements'],
        'new_external_primitive_knowledge': base['minimal_assembly'].get('new_external_primitive_knowledge'),
        'source_proposals': {who: copy.deepcopy(r['minimal_assembly']) for who, r in reviews.items()},
        'execution_validated_minimum': None}
    d['historical_joint_witness'] = {'complete_assertion_witness': False}
    d['execution'] = {'status': 'not_executed_in_this_study', 'manual_assembly_success': False, 'blind_result': False}
    return d, reviews, raw


def finish(d, raw, *, actions_checked, notes, extent, compatibility='source_supported_proposal'):
    cid = d['case_id']
    target = OBS / f'adjudicated/{cid}.json'
    if target.exists():
        raise FileExistsError('Use an explicit preserved scientific revision, not this writer')
    sources = read(OBS / f'sources/{cid}.json')['sources']
    history = {a['id']: a for a in read(RUN / f'public_inputs/{cid}/history.json')['actions']}
    d['root_source_checks'] = {'action_receipts': [{k: history[aid][k] for k in
        ['id', 'step_id', 'call_index', 'tool_call_id', 'command_sha256', 'observation_content_sha256']}
        for aid in actions_checked], 'issue': sources['issue'],
        'scope': 'Root inspected the cited original source/output and actual Verifier failure; no new candidate execution.'}
    d['adjudication_notes'] = notes
    d['fragment_compatibility'] = {'status': compatibility,
        'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']} for f in d['missing_factors']],
        'executed_joint_compatibility': False}
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    p = Path(sources['archived_verifier_stdout']['path'])
    content = p.read_text()
    position = content.rfind('===== FAILURES')
    if position < 0:
        raise ValueError('No archived failure section; inspect source before choosing excerpt')
    d['original_failure_receipt'] = {'source': receipt(p), 'start_char': position,
                                    'excerpt': content[position:position + 8000]}
    labels = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'] = {'missing_factor_count': len(labels),
        'missing_exact': labels.count('Exact Executed Fragment'),
        'missing_related': labels.count('Related Executed Components'),
        'missing_absent': labels.count('Absent'), 'missing_unresolved': labels.count(None),
        'has_missing_exact_fragment': 'Exact Executed Fragment' in labels,
        'all_missing_factors_exact': bool(labels) and all(x == 'Exact Executed Fragment' for x in labels),
        'all_missing_factors_have_executed_components': bool(labels) and all(x in
            ['Exact Executed Fragment', 'Related Executed Components'] for x in labels),
        'historical_support_extent': extent,
        'complete_historical_joint_witness': d['historical_joint_witness']['complete_assertion_witness'],
        'manual_execution_validated': False, 'blind_execution_validated': False}
    d['remaining_work_for_goal'] = ['Complete all88 source adjudications and stock-source coverage audit before freeze',
        'Execute automatically frozen candidates and source-unit rerun controls on P/R, with repetitions and feasible ablations']
    for who, value in raw.items():
        dst = OBS / f'frozen_reviews/{who}/{cid}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open('xb') as stream:
            stream.write(value)
        d['reviews'][who] = {'path': str(dst.relative_to(RUN)), 'sha256': receipt(dst)['sha256']}
    with target.open('x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(cid, extent)


def finish_revision(d, raw, *, reason, actions_checked, notes, extent, recovery_paths=()):
    """Preserve the complete prior record/reviews before an explicit root revision."""
    cid = d['case_id']
    target = OBS / f'adjudicated/{cid}.json'
    previous_raw = target.read_bytes()
    previous = json.loads(previous_raw)
    previous_hash = hashlib.sha256(previous_raw).hexdigest()
    archive = OBS / f'adjudicated/revisions/{cid}_{previous_hash}.json'
    if archive.exists():
        raise FileExistsError('This prior canonical version has already been revised')
    suffix = '_revision_' + previous_hash[:12]
    destinations = {who: OBS / f'frozen_reviews/{who}/{cid}{suffix}.json' for who in raw}
    if any(p.exists() for p in destinations.values()):
        raise FileExistsError('Revision review receipt already exists')
    for who, value in raw.items():
        row = json.loads(value)
        if row['case_id'] != cid or row['trial'] != d['trial']:
            raise ValueError('Revision review identity mismatch')
    history = {a['id']: a for a in read(RUN / f'public_inputs/{cid}/history.json')['actions']}
    action_receipts = [{k: history[aid][k] for k in ['id', 'step_id', 'call_index',
        'tool_call_id', 'command_sha256', 'observation_content_sha256']} for aid in actions_checked]
    recovery_receipts = [receipt(p) for p in recovery_paths]
    d['scientific_revision'] = {'previous_record': {'path': str(archive),
        'bytes': len(previous_raw), 'sha256': previous_hash}, 'reason': reason,
        'previous_counts': previous['counts'], 'prior_reviews_preserved': True}
    d['adjudication_notes'] = copy.deepcopy(d.get('adjudication_notes', previous.get('adjudication_notes', []))) + notes
    checks = d.setdefault('root_source_checks', copy.deepcopy(previous.get('root_source_checks', {})))
    if isinstance(checks, list):
        checks = {'prior_checks': checks, 'action_receipts': [
            a for block in checks for a in block.get('action_receipts', [])]}
        d['root_source_checks'] = checks
    by_action = {a['id']: a for a in checks.get('action_receipts', [])}
    by_action.update({a['id']: a for a in action_receipts})
    checks['action_receipts'] = list(by_action.values())
    checks['revision_source_recovery'] = recovery_receipts
    checks['scope'] = 'Root inspected recovered source and historical run correspondence; no new candidate execution.'
    labels = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'].update(missing_factor_count=len(labels),
        missing_exact=labels.count('Exact Executed Fragment'),
        missing_related=labels.count('Related Executed Components'),
        missing_absent=labels.count('Absent'), missing_unresolved=labels.count(None),
        has_missing_exact_fragment='Exact Executed Fragment' in labels,
        all_missing_factors_exact=bool(labels) and all(x == 'Exact Executed Fragment' for x in labels),
        all_missing_factors_have_executed_components=bool(labels) and all(x in
            ['Exact Executed Fragment', 'Related Executed Components'] for x in labels),
        historical_support_extent=extent)
    d['fragment_compatibility']['factor_mappings'] = [
        {'factor_id': f['factor_id'], 'mapping': f['compatibility']} for f in d['missing_factors']]
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open('xb') as stream:
        stream.write(previous_raw)
    d['reviews'] = {}
    for who, value in raw.items():
        dst = destinations[who]
        with dst.open('xb') as stream:
            stream.write(value)
        d['reviews'][who] = {'path': str(dst.relative_to(RUN)), 'sha256': receipt(dst)['sha256']}
    payload = json.dumps(d, ensure_ascii=False, indent=2) + '\n'
    temporary = target.with_suffix('.revision.tmp')
    with temporary.open('x') as stream:
        stream.write(payload)
    temporary.replace(target)
    print(cid, 'revision', extent)
