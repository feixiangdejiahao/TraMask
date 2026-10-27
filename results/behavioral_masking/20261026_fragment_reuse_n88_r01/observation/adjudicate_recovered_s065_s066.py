"""Scientific revisions backed by restored stock sources and both reviewers."""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent


def read(p):
    return json.loads(p.read_text())


def receipt(p):
    raw = p.read_bytes()
    return {'path': str(p), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


for cid in ['S065', 'S066']:
    reviews = {r: read(OBS / f'reviewer_{r}/{cid}.json') for r in ['A', 'B']}
    expected = ['Related Executed Components'] if cid == 'S065' else ['Exact Executed Fragment'] * 2
    assert all([f['provenance_class'] for f in row['missing_factors']] == expected for row in reviews.values())
    primary = reviews['B'] if cid == 'S065' else reviews['A']
    sources = read(OBS / f'sources/{cid}.json')['sources']
    actions = {x['id']: x for x in read(RUN / f'public_inputs/{cid}/history.json')['actions']}
    frozen = {}
    for who in ['A', 'B']:
        suffix = '_source_recovery_001' if cid == 'S065' else ''
        dst = OBS / f'frozen_reviews/{who}/{cid}{suffix}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open('xb') as stream:
            stream.write((OBS / f'reviewer_{who}/{cid}.json').read_bytes())
        frozen[who] = {'path': str(dst.relative_to(RUN)), 'sha256': receipt(dst)['sha256']}
    d = {k: copy.deepcopy(primary[k]) for k in ['case_id', 'trial', 'task', 'known_case',
        'target_operation', 'required_factor_inventory', 'agent_base_units',
        'missing_factors', 'oracle_availability']}
    d.update(schema_version='fragment-observation-adjudication.v1', status='complete',
             adjudicator='Codex /root', reviews=frozen)
    d['minimal_assembly'] = {
        'proposed_source_units': primary['minimal_assembly']['distinct_historical_source_units_including_base'],
        'proposed_transferred_fragments': primary['minimal_assembly']['transferred_fragments'],
        'new_semantic_elements': primary['minimal_assembly']['new_semantic_elements'],
        'new_external_primitive_knowledge': 0,
        'source_proposals': {r: copy.deepcopy(x['minimal_assembly']) for r, x in reviews.items()},
        'execution_validated_minimum': None,
    }
    d['historical_joint_witness'] = {'complete_assertion_witness': False}
    d['execution'] = {'status': 'not_executed_in_this_study',
                      'manual_assembly_success': False, 'blind_result': False}
    notes = d['adjudication_notes'] = []
    if cid == 'S065':
        old = OBS / f'adjudicated/{cid}.json'
        old_receipt = receipt(old)
        archive = OBS / f'adjudicated/revisions/{cid}_before_stock_recovery_{old_receipt["sha256"]}.json'
        archive.parent.mkdir(parents=True, exist_ok=True)
        with archive.open('xb') as stream:
            stream.write(old.read_bytes())
        # The archived record still references its original immutable frozen
        # review files. The new record uses new review names; no old receipt breaks.
        d['scientific_revision'] = {'previous_record': receipt(archive),
            'reason': 'Newly recovered stock test source establishes a previously unobserved executed related Check; prior complete record and original frozen reviews retained.',
            'previous_classification': 'Absent', 'current_classification': 'Related Executed Components'}
        notes.extend([
            {'topic': 'corrected historical availability', 'resolution': 'Recovered tests/test_result/test_result_bind.py is byte-identical in original image, qualified P and uniform CAS. Ordinary test_lash_failure asserts Failure5.lash(factory)==Failure6.101 explicitly runs tests/test_result and reports31PASS, no skips; original/P collect-only manifests both contain the same31nodes including this test.'},
            {'topic': 'what the donor proves', 'resolution': 'Failure-side lash must invoke the callback and return its changed container. This is an actually executed semantic result relation, stronger than the earlier Result documentation read8. It does not directly test Validated, a tuple payload or returning Valid.'},
            {'topic': 'Related rather than Exact', 'resolution': 'Map Result failure-side delegation to Invalid((1,)).lash(lambda e:Valid(2)) using the task interface contract. Correct expected Valid2 is a new application of the executed rule. The primary trigger and callback were already executed in95/110 with the wrong no-op oracle.'},
            {'topic': 'assembly and original classification', 'resolution': 'Two source units, one transferred Check rule, one new cross-container relation. Only the old expected result changes; this remains Assertion Repair Required. Neither a context repair nor a completed P/R detection is established.'},
        ])
        checked = ['s8_c0', 's95_c0', 's101_c0', 's110_c0']
        extent = 'executed_Result_callback_return_Check_reused_via_new_Validated_mapping'
    else:
        assert not (OBS / f'adjudicated/{cid}.json').exists()
        notes.extend([
            {'topic': 'recovered exact option donor', 'resolution': 'Stock keywordCase converts-keywords-to-uppercase test passes upper and asserts full uppercase SQL. Original/P/CAS sources, helper and runner configs match; BigQuery unconditionally registers it through behavesLikeSqlFormatter.132 runs all27suites with5735PASS; the2skips are in unrelated DuckDB tests. No named line was retained by tail, so execution is bound through complete suite and source/config identity.'},
            {'topic': 'successful lowercase operation', 'resolution': '89 defines lowercase aggregate preserve test and initially fails parsing.90 repairs parser promotion and reruns that exact file: complete lowercase PRESERVE output, named keywordCase preserve PASS and7/7PASS. The final history therefore contains an actually executed lowercase aggregate formatting path, not only a parse-failing input.'},
            {'topic': 'factor role disagreement', 'resolution': 'Lowercasing the source aggregate token changes the formatter input, so root follows A Trigger role. Upper option is Context. Both missing factors have Exact executed sources; B initially called the source casing Context.'},
            {'topic': 'minimal proposed composition', 'resolution': 'Start with92/132 full AGGREGATE-and-nested-GROUP-BY test. Change only source AGGREGATE to aggregate and add historical upper option; retain its complete uppercase output oracle. Three source units, two transferred factors, zero newly invented semantic ingredients. Their joint behavior has not yet been executed.'},
        ])
        checked = ['s89_c0', 's90_c0', 's92_c0', 's132_c0']
        extent = 'exact_lowercase_exclusive_keyword_and_upper_option_with_retained_full_oracle'
    d['fragment_compatibility'] = {'status': 'source_supported_proposal',
        'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']}
                            for f in d['missing_factors']], 'executed_joint_compatibility': False}
    recovery = OBS / f'source_recovery/{cid}/attempt_001/report.json'
    d['source_recovery'] = receipt(recovery)
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    path = Path(sources['archived_verifier_stdout']['path'])
    raw = path.read_text()
    start = raw.rfind('===== FAILURES')
    d['original_failure_receipt'] = {'source': receipt(path), 'start_char': start,
                                    'excerpt': raw[start:start + 5500]}
    d['root_source_checks'] = {'action_receipts': [{k: actions[x][k] for k in
        ['id', 'step_id', 'call_index', 'tool_call_id', 'command_sha256', 'observation_content_sha256']}
        for x in checked], 'issue': sources['issue'], 'recovered_stock_source': receipt(recovery),
        'scope': 'Root read stock test bodies, historical actual outputs, recovery correspondence and independent revisions; no new candidate execution.'}
    classes = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'] = {'missing_factor_count': len(classes),
        'missing_exact': classes.count('Exact Executed Fragment'),
        'missing_related': classes.count('Related Executed Components'),
        'missing_absent': classes.count('Absent'), 'missing_unresolved': classes.count(None),
        'has_missing_exact_fragment': 'Exact Executed Fragment' in classes,
        'all_missing_factors_exact': bool(classes) and all(x == 'Exact Executed Fragment' for x in classes),
        'all_missing_factors_have_executed_components': bool(classes) and all(x in
            ['Exact Executed Fragment', 'Related Executed Components'] for x in classes),
        'historical_support_extent': extent, 'complete_historical_joint_witness': False,
        'manual_execution_validated': False, 'blind_execution_validated': False}
    d['remaining_work_for_goal'] = ['Complete remaining source adjudications and stock-source coverage audit before freeze',
        'Execute frozen blind candidates and historical controls; recovered source is not an automatic detection result']
    destination = OBS / f'adjudicated/{cid}.json'
    with destination.open('w' if cid == 'S065' else 'x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(cid, extent)
