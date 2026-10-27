"""Informed source adjudications; never input to automatic blind generation."""
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
    return {'path': str(path), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


for case in ['S025', 'S026', 'S027', 'S028']:
    reviews = {role: read(OBS / f'reviewer_{role}/{case}.json') for role in ['A', 'B']}
    a, b = reviews['A'], reviews['B']
    sources = read(OBS / f'sources/{case}.json')['sources']
    actions = {x['id']: x for x in read(RUN / f'public_inputs/{case}/history.json')['actions']}
    frozen = {}
    for role in ['A', 'B']:
        src = OBS / f'reviewer_{role}/{case}.json'
        dst = OBS / f'frozen_reviews/{role}/{case}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            assert dst.read_bytes() == src.read_bytes()
        else:
            dst.write_bytes(src.read_bytes())
        frozen[role] = {'path': str(dst.relative_to(RUN)), 'sha256': receipt(dst)['sha256']}
    d = {
        'schema_version': 'fragment-observation-adjudication.v1',
        'case_id': case, 'trial': a['trial'], 'task': a['task'],
        'known_case': a.get('known_case'), 'status': 'complete',
        'adjudicator': 'Codex /root', 'reviews': frozen,
        'target_operation': copy.deepcopy(a['target_operation']),
        'required_factor_inventory': copy.deepcopy(a['required_factor_inventory']),
        'agent_base_units': copy.deepcopy(a['agent_base_units']),
        'missing_factors': copy.deepcopy(a['missing_factors']),
        'oracle_availability': copy.deepcopy(a['oracle_availability']),
        'minimal_assembly': {
            'proposed_source_units': a['minimal_assembly']['distinct_historical_source_units_including_base'],
            'proposed_transferred_fragments': a['minimal_assembly']['transferred_fragments'],
            'new_semantic_elements': a['minimal_assembly']['new_semantic_elements'],
            'new_external_primitive_knowledge': a['minimal_assembly'].get('new_external_primitive_knowledge'),
            'source_proposals': {r: copy.deepcopy(x['minimal_assembly']) for r, x in reviews.items()},
            'execution_validated_minimum': None,
        },
        'historical_joint_witness': {'complete_assertion_witness': False},
        'execution': {'status': 'not_executed_in_this_study',
                      'manual_assembly_success': False, 'blind_result': False},
        'adjudication_notes': [],
        'remaining_work_for_goal': ['Complete and freeze all88 informed adjudications before blind generation',
                                   'Execute frozen automatic candidates and historical-unit controls independently'],
    }
    notes = d['adjudication_notes']

    if case == 'S025':
        f = d['missing_factors'][0]
        f['provenance_class'] = 'Related Executed Components'
        f['source_fragments'] = copy.deepcopy(b['missing_factors'][0]['source_fragments'])
        f['absent_semantic_primitive'] = 'The equal-numeric-run decision for7 versus007 and its fallthrough to raw path tie-break are not established by an executed historical oracle; derive them from Issue.'
        for item in d['required_factor_inventory']:
            if item.get('role') == 'Check' and not item.get('present_in_base'):
                item['history_provenance'] = 'Related Executed Components'
        d['oracle_availability']['historical_check_provenance'] = 'Related Executed Components'
        d['minimal_assembly'].update(proposed_source_units=2, proposed_transferred_fragments=1,
            issue_only_alternative={'source_units': 1, 'transferred_fragments': 0, 'new_semantic_elements': 1},
            derived_joint_relations=['Equal numeric runs fall through to raw path order, placing file007 beforefile7.'])
        notes.extend([
            {'topic': 'agreement on actual miss', 'resolution': 'The original natural test already contains both filenames and passes the wrong expected order. Neither trigger nor context is missing; repair is Check-only.'},
            {'topic': 'partial provenance', 'resolution': 'A finds the complete correct comparison absent. B identifies actual test_sort_path with full ordered-output assertion. Root inspected its full body, not just the --sort flag. This supplies a specific path-order component, while numeric equality and fallback applicability still require the Issue. Related does not mean the full correct rule was executed.'},
            {'topic': 'source count', 'resolution': 'Two named tests support the donor version. Correcting solely from Issue needs only the original test and remains a one-unit alternative. No executed minimality or successful P/R result is claimed.'},
        ])
        checked = ['s67_c0', 's100_c0']
        extent = 'related_path_order_component_with_absent_numeric_tie_oracle_derived_from_issue'

    elif case == 'S026':
        d['alternative_focal_observation'] = {k: copy.deepcopy(b[k]) for k in
            ['target_operation', 'agent_base_units', 'missing_factors', 'oracle_availability', 'minimal_assembly']}
        notes.extend([
            {'topic': 'different focal failures', 'resolution': 'A selects missing-import diagnostics; B selects ambiguous embedding. Both are actual archived failures. Retain A predeclared missing-import primary and B distinct alternative, without combining their factor labels.'},
            {'topic': 'source and oracle', 'resolution': 'Root inspected original55 PackageNotImported assertion,85 actual math.Sin acceptance probe and147 passing checker run. Issue explicitly requires file-import resolution. Transfer math.Sin while retaining the parametric package-not-imported relation.'},
            {'topic': 'input carrier', 'resolution': 'In this trajectory the /*! expected-warning comment is itself consumed through doc.Text(); the declaration preceding it has a generic description. Map the bracketed symbol and interpolated qualifier together. Do not invent an independently executed // input reference.'},
            {'topic': 'execution scope', 'resolution': 'The full historical fixture includes unrelated expectations and stdlib acceptance contrary to the reference contract. A proposed focal declaration is a narrower preselected scope and must be reported as such; no full-file P/R pass is claimed.'},
        ])
        checked = ['s55_c0', 's85_c0', 's147_c0']
        extent = 'exact_resolvable_stdlib_link_transfer_to_existing_missing_import_oracle'

    elif case == 'S027':
        d['alternative_focal_observation'] = {k: copy.deepcopy(b[k]) for k in
            ['target_operation', 'agent_base_units', 'missing_factors', 'oracle_availability', 'minimal_assembly']}
        notes.extend([
            {'topic': 'different focal failures', 'resolution': 'Retain A predeclared ordinary-block-comment failure as primary. B independently finds a different genuine missing-import failure with an Exact aliased-import donor. Report primary-focal and any-task historical availability separately; do not lose B positive reuse proposal or silently substitute it for the primary.'},
            {'topic': 'false block-comment donor', 'resolution': 'Raw48 parses a /*! lint expectation through go/ast and prints it. It does not execute ordinary block documentation through brokenDocLink. The expectation directive remains separate from // FuncDoc input84; changing that input to /*...*/ introduces previously untested carrier syntax.'},
            {'topic': 'alternative compatibility', 'resolution': 'B transfers actual mymath/math import pattern from positive_qualified.go to mstrings/strings in the existing unimported-strings fixture. It preserves native strings diagnostic and supplies a dummy use for compilation. This is a two-unit Exact context proposal for another actual task defect, still unexecuted.'},
        ])
        d['historical_joint_witness']['other_task_failure_has_exact_transfer_proposal'] = True
        checked = ['s48_c0', 's84_c0', 's117_c0']
        extent = 'primary_block_doc_trigger_absent_other_task_import_alias_context_exact'

    elif case == 'S028':
        notes.extend([
            {'topic': 'agreement', 'resolution': 'Both reviewers locate repeated-line context in actual helper74 but no partially overlapping multiline replacement stimulus. Generic single-line conflicts and identical-range repeated-line conflicts do not supply that missing range structure.'},
            {'topic': 'retained obligations', 'resolution': 'Keep complete ContentConflict worktree setup, ErrMergeConflicts, MERGE_HEAD, markers and index-stage checks. New offset replacement runs are semantic input generation; repeated-line context alone is not enough.'},
            {'topic': 'historical versus submitted tests', 'resolution': '127 explicitly runs and passes TestMergeContentConflict.145 temporarily restores the test file, runs it, then removes it. Final source absence does not erase actual historical execution.'},
            {'topic': 'failure count', 'resolution': 'Archived suite parent plus two failed child tests are three result rows, not three independently established defects. Primary is the repeated-line complex-overlap child.'},
        ])
        checked = ['s62_c0', 's74_c0', 's127_c0', 's145_c0']
        extent = 'exact_repeated_context_but_partial_overlap_multiline_stimulus_absent'

    d['fragment_compatibility'] = {
        'status': 'source_supported_proposal',
        'factor_mappings': [{'factor_id': f['factor_id'], 'mapping': f['compatibility']}
                            for f in d['missing_factors']],
        'executed_joint_compatibility': False,
    }
    d['oracle_availability']['independent_source_receipts'] = [sources[k] for k in
        ['issue', 'verifier_test', 'reference_solution']]
    stdout_path = Path(sources['archived_verifier_stdout']['path'])
    stdout = stdout_path.read_text()
    start = stdout.rfind('===== FAILURES')
    assert start >= 0
    d['original_failure_receipt'] = {'source': receipt(stdout_path), 'start_char': start,
                                    'excerpt': stdout[start:start + 4200]}
    d['root_source_checks'] = {
        'actions': [{k: actions[x][k] for k in ['id', 'step_id', 'call_index', 'tool_call_id',
                                               'command_sha256', 'observation_content_sha256']}
                    for x in checked],
        'issue': sources['issue'],
        'scope': 'Root inspected primary commands, output and task contract; no new candidate execution.',
    }
    classes = [f['provenance_class'] for f in d['missing_factors']]
    d['counts'] = {
        'missing_factor_count': len(classes),
        'missing_exact': classes.count('Exact Executed Fragment'),
        'missing_related': classes.count('Related Executed Components'),
        'missing_absent': classes.count('Absent'),
        'missing_unresolved': classes.count(None),
        'has_missing_exact_fragment': 'Exact Executed Fragment' in classes,
        'all_missing_factors_exact': bool(classes) and all(x == 'Exact Executed Fragment' for x in classes),
        'all_missing_factors_have_executed_components': bool(classes) and all(x in
            ['Exact Executed Fragment', 'Related Executed Components'] for x in classes),
        'historical_support_extent': extent,
        'complete_historical_joint_witness': False,
        'manual_execution_validated': False, 'blind_execution_validated': False,
    }
    with (OBS / f'adjudicated/{case}.json').open('x') as stream:
        json.dump(d, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(case, extent)
