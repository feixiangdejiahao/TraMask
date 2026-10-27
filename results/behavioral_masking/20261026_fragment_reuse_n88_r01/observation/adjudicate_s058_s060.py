"""Source-only root adjudication after independent A/B review; not blind input."""
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


for cid in ['S058', 'S059', 'S060']:
    reviews = {r: read(OBS / f'reviewer_{r}/{cid}.json') for r in ['A', 'B']}
    a, b = reviews['A'], reviews['B']
    primary = b if cid == 'S060' else a
    sources = read(OBS / f'sources/{cid}.json')['sources']
    assist_path = OBS / f'adjudication_assists/{cid}.json'
    assist = read(assist_path)
    actions = {x['id']: x for x in read(RUN / f'public_inputs/{cid}/history.json')['actions']}
    frozen = {}
    for role in ['A', 'B']:
        src = OBS / f'reviewer_{role}/{cid}.json'
        dst = OBS / f'frozen_reviews/{role}/{cid}.json'
        assert receipt(src)['sha256'] == assist['review_receipts'][role]['sha256']
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open('xb') as stream:
            stream.write(src.read_bytes())
        frozen[role] = {'path': str(dst.relative_to(RUN)), 'sha256': receipt(dst)['sha256']}
    d = {k: copy.deepcopy(primary[k]) for k in ['case_id', 'trial', 'task', 'known_case',
        'target_operation', 'agent_base_units', 'required_factor_inventory',
        'missing_factors', 'oracle_availability']}
    d.update(schema_version='fragment-observation-adjudication.v1', status='complete',
             adjudicator='Codex /root', reviews=frozen)
    ma = primary['minimal_assembly']
    d['minimal_assembly'] = {
        'proposed_source_units': ma['distinct_historical_source_units_including_base'],
        'proposed_transferred_fragments': ma['transferred_fragments'],
        'new_semantic_elements': ma['new_semantic_elements'],
        'new_external_primitive_knowledge': ma.get('new_external_primitive_knowledge'),
        'source_proposals': {r: copy.deepcopy(x['minimal_assembly']) for r, x in reviews.items()},
        'execution_validated_minimum': None,
    }
    d['historical_joint_witness'] = {'complete_assertion_witness': False}
    d['execution'] = {'status': 'not_executed_in_this_study',
                      'manual_assembly_success': False, 'blind_result': False}
    d['adjudication_assist'] = receipt(assist_path)
    d['original_failure_assertion'] = copy.deepcopy(assist['original_failure_assertion_checked'])
    notes = d['adjudication_notes'] = []

    if cid == 'S058':
        d['alternative_focal_observation'] = {k: copy.deepcopy(b[k]) for k in
            ['target_operation', 'agent_base_units', 'missing_factors', 'oracle_availability', 'minimal_assembly']}
        d['historical_joint_witness']['other_task_failure_has_exact_check_transfer_proposal'] = True
        notes.extend([
            {'topic': 'different actual failures', 'resolution': 'Retain A clean-report formatting failure as predeclared primary. B independently selects registered-union FirstFirst failure, also present in archived execution. Its two-unit Exact Check proposal remains a separate alternative; primary and any-task availability must both be reported.'},
            {'topic': 'reachability', 'resolution': '31 defines clean summary and invalid local-method union declarations, but compilation fails.32 fixes declarations and later recursion repair permits final71 uncached analyze-tag suite to execute both.31 alone is not proof of execution.'},
            {'topic': 'primary Check', 'resolution': 'Existing clean test requires only nonempty String. Add the Issue-required newline predicate before report is reassigned to Dirty. Generic Contains syntax elsewhere does not provide the missing multiline obligation.'},
            {'topic': 'alternative Check', 'resolution': 'Union members both consume Ident; existing Analyze call discards its report.29 independently asserts HasType(ConflictFirstFirst) for Ident|Ident. Transferring that exact decision preserves the existing union input; it has not been executed in this study.'},
        ])
        checked = ['s29_c0', 's31_c0', 's32_c0', 's71_c0']
        extent = 'primary_multiline_check_absent_other_actual_union_failure_has_exact_check_donor'

    elif cid == 'S059':
        d['alternative_focal_observation'] = {k: copy.deepcopy(b[k]) for k in
            ['target_operation', 'agent_base_units', 'missing_factors', 'oracle_availability', 'minimal_assembly']}
        d['fragment_compatibility'] = {
            'status': 'new_fault_routing_and_original_baseline_oracle_repair_required',
            'mapping': 'Transfer actually exercised WAL Sync failure and callback-error checks into the real DB wait harness; route the fault to the DB-created WAL after Open and derive failed-wait expectations.',
            'unimplemented_condition': 'record.syncErrorFile is private to the record test; directly constructing NewLogWriter does not inject a fault into the DB-created WAL.',
            'original_base_issue': 'Final TestWaitForDurability retains high>=seqNum+2 after a two-key batch. The highest durable key should be seqNum+1; this independent assertion can reject R even before the proposed error scenario.',
            'required_control': 'Freeze exact full test version and independently repair/account for this extra Check, or predeclare a smaller original request/check block and retain full-unit failure. No such execution or scope repair is claimed here.',
            'executed_joint_compatibility': False,
        }
        d['minimal_assembly']['additional_baseline_obligation'] = 'Source proposal counts do not include repair of original exclusive-high watermark assertion. No valid portable full-unit assembly minimum is established.'
        notes.extend([
            {'topic': 'different actual failures', 'resolution': 'A selects WaitForDurability nil after sync failure. B selects prematurely ready next-sequence notification. Preserve the error and readiness proposals separately, not as one required-factor set.'},
            {'topic': 'specific lower-level components', 'resolution': '190 actually injects syncErrorFile into LogWriter and checks injectedErr;196 injects commitEnv error and checks Commit and callback. These are Related support for a real DB failure, not an executed DB fault route.'},
            {'topic': 'base version and independent wrong oracle', 'resolution': '118 removes invalid far-future-success expectation from117 but leaves high>=seqNum+2.244 passes the authored suite. Root identified this unrelated watermark expectation in the full source; source compatibility remains unresolved rather than assuming the original full base passes R.'},
            {'topic': 'alternative boundary relation', 'resolution': 'Discarded Notify(100) proves creation only. Far-future waiter blocking and two-key seqNum+1 arithmetic are components, but first-not-durable after a one-key commit and two-phase notification require a new joint relation. The wrong high>=seqNum+2 assertion cannot supply the oracle.'},
        ])
        checked = ['s117_c0', 's118_c0', 's190_c0', 's196_c0', 's244_c0']
        extent = 'related_error_components_but_new_DB_routing_and_full_base_watermark_oracle_problem'

    elif cid == 'S060':
        # The public, pre-existing map_top_down implementation makes the task's
        # traversal requirement precise independently of the hidden Reference.
        d['witness_status'] = 'task_and_public_traversal_semantics_support_actual_failure'
        d['oracle_availability'].update(
            expected='Top-down processing reduces ABC at the mixed root, then reduces fully qualifying DE suffix subtree to Range(d,e).',
            historical_check_provenance='Related Executed Components',
            available_to_blind_system=True,
            adjudicated_reason='Issue requires top-down final pass. Public original OptimizedExpr.map_top_down at6 calls f(expr), then recursively visits children of the returned expression. Thus the rebuilt DE child is a complete qualifying two-alternative choice. Root partial-run threshold3 is respected; child full-choice reduction uses its separate rule.')
        for factor in d['missing_factors']:
            if factor['role'] == 'Context':
                factor['role'] = 'Trigger'
                factor['role_resolution'] = 'The AST operand graph is target input, not external runtime state.'
        for factor in d['required_factor_inventory']:
            if factor.get('factor_id') == 'F2':
                factor['role'] = 'Trigger'
        d['minimal_assembly'].update(proposed_source_units=2,
            new_external_primitive_knowledge=0,
            derived_joint_relations=['Compose partial triple, barrier and fully qualifying pair in right-associated AST.',
                                     'Apply public top-down traversal to full-pair rule inside reconstructed suffix.'],
            count_resolution='Partial-three base and full-two donor are two named units. Opposite partial-two assertion is conflict evidence, not a required third donor.')
        d['alternative_base_proposal'] = {k: copy.deepcopy(a[k]) for k in
            ['agent_base_units', 'missing_factors', 'oracle_availability', 'minimal_assembly']}
        d['fragment_compatibility'] = {
            'status': 'semantic_oracle_resolved_private_helper_portability_unresolved',
            'mapping': 'Primary uses B positive partial-three base plus independently executed full-two reduction; compose mixed AST and derive complete expected AST under required top-down rule.',
            'reference_compatibility': 'Historical test directly calls private coalesce_expr, present in P but absent in R, which exposes coalesce on OptimizedRule. Do not silently replace this target with a public pipeline and call it unchanged. A portable adaptation would need separate accounting.',
            'alternative_base_validity': 'A partial-two negative oracle is contradicted by the same explicit top-down semantics and may fail on R. It remains an alternative source record, not a qualified original-pass control.',
            'executed_joint_compatibility': False,
        }
        d['original_failure_assertion_definition'] = copy.deepcopy(assist['verifier_assertion_definition_checked'])
        notes.extend([
            {'topic': 'oracle dispute resolved', 'resolution': 'The oracle rests on Issue plus existing public map_top_down, not on Reference agreement alone.6 visibly applies transformation before descending into transformed Choice children. Partial-run>=3 concerns the current mixed choice; suffix DE is a fully qualifying child and obeys the full-choice reduction rule.'},
            {'topic': 'delivered mechanism', 'resolution': 'P flattens the choice, maps coalesce_expr over individual alternatives, then rebuilds the chain without visiting its reconstructed suffix choices. This omits the required child application. R map_top_down(try_coalesce) corroborates the independently justified reading.'},
            {'topic': 'historical oracle version', 'resolution': '28 initially writes a tail2 Range expectation;29 changes it to unchanged before any recorded execution. The initial text is not an executed correct witness.194 reports17 coalescer tests, not15.'},
            {'topic': 'primary base', 'resolution': 'Use independently predeclared B positive partial-three base for canonical composition. A proposed negative partial-two base has a conflicting oracle under the resolved task semantics and is retained with that limitation. Neither base has new P/R evidence.'},
            {'topic': 'source versus execution', 'resolution': 'Public traversal source supplies the interpretation of top-down but is not itself counted as an executed validation fragment. Actual partial-three and full-two tests supply Related components; complete mixed-shape expectation remains newly composed.'},
        ])
        checked = ['s6_c0', 's28_c0', 's29_c0', 's194_c0']
        extent = 'related_partial_and_full_choice_components_with_task_resolved_top_down_oracle'

    if 'fragment_compatibility' not in d:
        d['fragment_compatibility'] = {
            'status': 'source_supported_proposal',
            'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']}
                                for f in d['missing_factors']],
            'executed_joint_compatibility': False,
        }
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    d['root_source_checks'] = {
        'action_receipts': [{k: actions[x][k] for k in ['id', 'step_id', 'call_index',
            'tool_call_id', 'command_sha256', 'observation_content_sha256']} for x in checked],
        'issue': sources['issue'],
        'scope': 'Primary commands, source versions and actual outputs checked. No new candidate or subject test executed.',
    }
    classes = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'] = {
        'missing_factor_count': len(classes),
        'missing_exact': classes.count('Exact Executed Fragment'),
        'missing_related': classes.count('Related Executed Components'),
        'missing_absent': classes.count('Absent'), 'missing_unresolved': classes.count(None),
        'has_missing_exact_fragment': 'Exact Executed Fragment' in classes,
        'all_missing_factors_exact': bool(classes) and all(x == 'Exact Executed Fragment' for x in classes),
        'all_missing_factors_have_executed_components': bool(classes) and all(x in
            ['Exact Executed Fragment', 'Related Executed Components'] for x in classes),
        'historical_support_extent': extent, 'complete_historical_joint_witness': False,
        'manual_execution_validated': False, 'blind_execution_validated': False,
    }
    d['remaining_work_for_goal'] = ['Complete and freeze all88 informed observations',
        'Resolve uniform public workspace-source access before generator freeze',
        'Execute independent automatic candidates and original-unit controls; source proposals are not detections']
    with (OBS / f'adjudicated/{cid}.json').open('x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(cid, extent)
