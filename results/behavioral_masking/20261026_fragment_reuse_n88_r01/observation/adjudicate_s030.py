"""Resolve S030 against actual assertion site, preserving invalidated review."""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent
reviews = {k: json.loads((OBS / f'reviewer_{k}/S030.json').read_text()) for k in ['A', 'B']}
b = reviews['B']
sources = json.loads((OBS / 'sources/S030.json').read_text())['sources']
results = json.loads(Path(sources['archived_verifier_results']['path']).read_text())
failures = [t for t in results['results']['tests'] if t['status'] == 'failed']
assert len(failures) == 5
assert all('assert response.is_closed is True' in t['message'] for t in failures)
frozen = {}
for role in reviews:
    raw = (OBS / f'reviewer_{role}/S030.json').read_bytes()
    dest = OBS / f'frozen_reviews/{role}/S030.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    assert not dest.exists()
    dest.write_bytes(raw)
    frozen[role] = {'path': str(dest.relative_to(RUN)), 'sha256': hashlib.sha256(raw).hexdigest()}
d = {
    'schema_version': 'fragment-observation-adjudication.v1', 'case_id': 'S030',
    'trial': b['trial'], 'task': b['task'], 'known_case': b.get('known_case'),
    'status': 'complete', 'adjudicator': 'Codex /root', 'reviews': frozen,
    **{k: copy.deepcopy(b[k]) for k in ['target_operation', 'required_factor_inventory',
                                      'agent_base_units', 'missing_factors', 'oracle_availability']},
    'fragment_compatibility': {
        'status': 'source_supported_proposal', 'cross_unit_transfer_support': True,
        'mapping': 'Keep original malformed body parameter and raisesDecodingError. Transfer actual3-byte IteratorByteStream wrapper and add closed-state assertion after error.',
        'executed_joint_compatibility': False,
    },
    'minimal_assembly': {
        'proposed_source_units': 2, 'proposed_transferred_fragments': 2,
        'new_semantic_elements': 1, 'new_external_primitive_knowledge': 0,
        'source_proposals': {k: copy.deepcopy(v['minimal_assembly']) for k, v in reviews.items()},
        'execution_validated_minimum': None,
        'source_unit_count_note': 'B finds streaming wrapper and closure decision in one actual valid-stream named unit. A uses an additional earlier malformed-stream probe; three units are not required by the smaller source proposal.',
    },
    'historical_joint_witness': {'complete_assertion_witness': False},
    'execution': {'status': 'not_executed_in_this_study', 'manual_assembly_success': False, 'blind_result': False},
    'root_source_checks': [
        {'source': sources['archived_verifier_results'], 'finding': 'All5 failures are closedFalse at line381 after successful pytest.raises. None shows the alleged missing DecodingError.'},
        {'source': sources['verifier_test'], 'finding': 'Actual failing test wraps malformed body in a live stream, checks rejection, then checks closure.'},
        {'actions': ['s54_c0', 's112_c0', 's118_c0'], 'finding': 'Separate malformed buffered input and valid streaming closure tests actually execute. The complete exceptional-close relation is not historical.'},
    ],
    'adjudication_notes': [
        {'topic': 'corrected factual disagreement', 'resolution': 'Root found B misread failing test names as framing acceptance. B reread only primary sources and corrected its review. Prior review remains hash-preserved and explicitly invalidated; its EOF-only candidate is not retained as an established explanation.'},
        {'topic': 'final agreement', 'resolution': 'A and corrected B agree on live streaming Context Exact plus exceptional closure Check Related. Their source-unit counts differ because B locates both transferred components in one valid-stream unit.'},
        {'topic': 'semantics', 'resolution': 'Do not change malformed bytes merely to reproduce a failure label. The actual missed effect is resource cleanup after a correctly detected parser error. Streaming setup without the new lifecycle observation cannot expose this omission.'},
    ],
    'review_correction': copy.deepcopy(b['revision_history']),
    'counts': {
        'missing_factor_count': 2, 'missing_exact': 1, 'missing_related': 1, 'missing_absent': 0,
        'missing_unresolved': 0, 'has_missing_exact_fragment': True, 'all_missing_factors_exact': False,
        'all_missing_factors_have_executed_components': True,
        'history_evidence_extent': 'exact_streaming_wrapper_and_related_exceptional_cleanup_relation',
        'cross_unit_transfer_support': True, 'manual_validated_assembly': False, 'automatic_validated_assembly': False,
    },
    'remaining_work_for_goal': ['Finish all88 informed cases and freeze', 'Independently execute blind candidates and controls'],
}
d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in ['issue', 'verifier_test', 'reference_solution']]
with (OBS / 'adjudicated/S030.json').open('x') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
    f.write('\n')
print('S030 source adjudication complete; five assertion sites verified')
