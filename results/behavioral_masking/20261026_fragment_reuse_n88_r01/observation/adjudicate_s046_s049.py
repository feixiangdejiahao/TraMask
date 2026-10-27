"""Informed oracle adjudication; retain all four cases and exclude false positives."""
from pathlib import Path
import copy
import hashlib
import json

OBS = Path(__file__).resolve().parent
RUN = OBS.parent


def load(p):
    return json.loads(p.read_text())


def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def receipt(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(RUN)), 'sha256': hashlib.sha256(raw).hexdigest()}


audit = {
    'schema_version': 'fragment-oracle-audit.v1', 'date': '2026-10-26',
    'scope': 'S046 array ambiguity and S047 bare-switch version conflict; supplements shared binding-of audit',
    'root_primary_checks': [
        {'case': 'S046', 'actions': ['s53_c0', 's96_c0'], 'finding': 'Actual Babel probe accepts using[x]=y as expression; actual Meriyah diagnostic also prints ExpressionStatement. Object-pattern rejection alone does not establish an array-declaration interpretation.'},
        {'case': 'S047', 'actions': ['s38_c0', 's49_c0', 's50_c1'], 'finding': 'Acorn rejects bare switch using; archived2025 Test262 source explicitly marks case/default using as a parse error. These source reads are oracle evidence, not executed SUT tests.'},
        {'case': 'S048', 'actions': ['s39_c0'], 'finding': 'Archived Babel lookahead declines ordinary using-of for-of declaration interpretation. This corroborates the common ambiguity conflict.'},
    ],
    'primary_external_sources': [
        {'url': 'https://tc39.es/proposal-explicit-resource-management/#sec-let-and-const-declarations',
         'version': 'Stage3 June15,2024', 'finding': 'Using grammar permits binding identifiers, not binding patterns. Array-member assignment can instead parse as an expression.'},
        {'url': 'https://tc39.es/proposal-explicit-resource-management/#sec-switch-statement',
         'version': 'Stage3 June15,2024', 'finding': 'Older proposal supports resource declarations within switch scope.'},
        {'url': 'https://tc39.es/ecma262/multipage/ecmascript-language-statements-and-declarations.html#sec-switch-statement-static-semantics-early-errors',
         'version': 'Living specification displayed2027; archived2025 Test262 gives the same restriction',
         'finding': 'Current case/default early errors prohibit direct using declarations.'},
    ],
    'task_interpretation': 'Issue names destructuring diagnostics and broadly says any scope, but does not explicitly redefine ambiguous member assignments or select a proposal version. It also states script-global acceptance and rejection inconsistently. Treat these additional failures as contract/version uncertainty, not automatic independent confirmation.',
    'consequence': 'Do not promote S046 alternative array rejection or S047 switch acceptance to a trusted repair solely from Verifier/reference agreement. The common for-of binding-of conflict is independently established by archived Test262 and both specification generations.',
    'blind_boundary': 'No cross-case or external oracle audit is added to generator inputs.',
}
save(OBS / 'oracle_audits/meriyah_other_failures.json', audit)

for case in ['S046', 'S047', 'S048', 'S049']:
    reviews = {k: load(OBS / f'reviewer_{k}/{case}.json') for k in ['A', 'B']}
    a, b = reviews['A'], reviews['B']
    sources = load(OBS / f'sources/{case}.json')['sources']
    frozen = {}
    for role in reviews:
        src = OBS / f'reviewer_{role}/{case}.json'
        dst = OBS / f'frozen_reviews/{role}/{case}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        assert not dst.exists()
        dst.write_bytes(src.read_bytes())
        frozen[role] = receipt(dst)
    factors = []
    if case != 'S047':
        f = copy.deepcopy((b if case == 'S049' else a)['missing_factors'][0])
        f.update(factor_id='F1', role='Trigger',
                 semantic_condition='Introduce ordinary for(using of of...) token sequence in the selected unambiguous using-loop base.',
                 necessity_basis='conditional_benchmark_witness_only_not_established_bug',
                 provenance_class='Absent' if case == 'S048' else 'Related Executed Components',
                 audit_status='historical_component_audit_complete_but_semantic_transfer_invalid')
        f['compatibility'] = {
            'status': 'unresolved_oracle_conflict',
            'mapping': 'Standalone/classic-for identifier spelling can be observed, but using-of lookahead changes parse class in the proposed target. This is not a semantics-preserving alpha-renaming.',
            'preserved_semantics': None, 'execution_support': None,
        }
        if case == 'S049':
            f['source_kind'] = 'executed_external_parser_probe_not_SUT'
        factors.append(f)
    factors.append({
        'factor_id': 'F2' if factors else 'F1', 'role': 'Check',
        'semantic_condition': 'An independently justified reason to require declaration kind using for the ambiguous ordinary using-of loop.',
        'necessity_basis': 'required_to_establish_bug', 'provenance_class': None,
        'audit_status': 'unresolved_oracle_conflict', 'source_fragments': [],
        'compatibility': {'status': 'unresolved_oracle_conflict', 'mapping': None,
                          'preserved_semantics': None, 'execution_support': None},
        'reason': 'Independent grammar/Test262 evidence supports identifier using and computed member-expression RHS. Missing trustworthy bug definition is not equivalent to an Absent-but-valid historical oracle.',
    })
    d = {
        'schema_version': 'fragment-observation-adjudication.v1',
        'case_id': case, 'trial': a['trial'], 'task': a['task'], 'known_case': a.get('known_case'),
        'status': 'complete', 'adjudicator': 'Codex /root', 'reviews': frozen,
        'witness_status': 'oracle_conflict_no_independently_confirmed_focal_bug',
        'target_operation': {
            'operation': 'Parse for (using of of [1,2]) {} with next enabled.',
            'benchmark_required_effect': 'ForOfStatement.left is a using declaration binding of.',
            'required_effect': None,
            'independently_supported_behavior': 'Ordinary for-of assigns to identifier using; RHS is computed member access of[1,2].',
            'delivered_patch_effect': 'left.kind is undefined; this mismatch alone does not demonstrate a semantic bug.',
            'focal_failure_selection': 'Retain common actual binding-of mismatch selected by A; S046 B alternative and other actual failures are preserved separately.',
            'verifier_receipts': [sources[k] for k in ['verifier_test', 'archived_verifier_results']],
        },
        'required_factor_inventory': copy.deepcopy(a['required_factor_inventory']),
        'inventory_scope': 'Conditional benchmark-requested witness; not a set of requirements for an established true bug. Canonical missing_factors supersedes reviewer role/trust labels.',
        'agent_base_units': copy.deepcopy(a['agent_base_units']),
        'missing_factors': factors,
        'oracle_availability': {
            'expected': None, 'benchmark_expected': 'left.kind using',
            'historical_check_provenance': None, 'available_to_blind_system': None,
            'trusted_bug_oracle': False, 'independent_behavioral_error_established': False,
            'conflict': 'Archived Agent-time Test262 explicitly excludes using-of lookahead from ordinary using declaration. Issue provides no clear override.',
            'audits': [receipt(OBS / 'oracle_audits/meriyah_using_of.json'), receipt(OBS / 'oracle_audits/meriyah_other_failures.json')],
            'own_history_note': 'S047 has the exact Test262 read and SUT probe; cross-case evidence for other trajectories is evaluator-only, never a donor in their public histories.',
        },
        'fragment_compatibility': {'status': 'unresolved_oracle_conflict',
            'cross_unit_transfer_support': False, 'executed_joint_compatibility': False,
            'reason': 'Executed token/AST components do not justify preserving declaration-kind expectations across the grammar boundary.'},
        'minimal_assembly': {
            'proposed_source_units': None, 'proposed_transferred_fragments': None,
            'new_semantic_elements': None, 'execution_validated_minimum': None,
            'status': 'no_valid_known_assembly_for_focal_benchmark_requirement',
            'conditional_component_units': {'S046':2, 'S047':1, 'S048':1, 'S049':2}[case],
            'source_proposals': {k: copy.deepcopy(v['minimal_assembly']) for k,v in reviews.items()},
            'proposal_status': 'Retained for provenance audit; disputed expectations are not approved valid tests.',
        },
        'historical_joint_witness': {'complete_assertion_witness': False,
            'target_and_observer_already_executed': case == 'S047'},
        'execution': {'status': 'not_executed_in_this_study', 'manual_assembly_success': False, 'blind_result': False},
        'source_assist': receipt(OBS / f'adjudication_assists/{case}.json'),
        'adjudication_notes': [
            {'topic': 'witness trust', 'resolution': 'Archived failure proves a benchmark mismatch, not an independently established bug. Both final review narratives acknowledge the conflict; positive-sounding runtime_confirmed labels in B do not override its oracle caveat.'},
            {'topic': 'provenance versus oracle', 'resolution': 'Retain actually executed components and absent input conditions descriptively. Null Check represents unresolved validity; do not count this as evidence that inventing a new correct Check can repair a known bug.'},
            {'topic': 'cohort and blind evaluation', 'resolution': 'Retain trajectory in88 and still attempt blind generation. Benchmark-only discrimination on this expectation is not a valid positive. Other independently justified task defects may be evaluated separately under the frozen phase2 rule.'},
        ],
        'remaining_work_for_goal': ['Finish all88 observations and freeze', 'Blind candidates and independent semantic evaluation, including explicit oracle-conflict dispositions'],
    }
    if case == 'S046':
        d['alternative_focal_observation'] = {k: copy.deepcopy(b[k]) for k in ['target_operation', 'missing_factors', 'oracle_availability', 'minimal_assembly']}
        d['alternative_focal_status'] = 'unresolved_task_specific_array_diagnostic_contract; mere ban on declaration destructuring does not prove using[a]=arr is a declaration'
    if case == 'S047':
        d['other_archived_failure'] = {'behavior':'bare switch case using declaration',
            'status':'unresolved_task_or_proposal_version_contract',
            'reason':'Archived2025 Test262 rejects it,2024 proposal permitted switch scope; task wording does not select a version clearly.'}
    cls = [f['provenance_class'] for f in factors]
    d['counts'] = {
        'missing_factor_count':len(cls), 'missing_exact':cls.count('Exact Executed Fragment'),
        'missing_related':cls.count('Related Executed Components'), 'missing_absent':cls.count('Absent'),
        'missing_unresolved':cls.count(None), 'has_missing_exact_fragment':False,
        'all_missing_factors_exact':False, 'all_missing_factors_have_executed_components':False,
        'history_evidence_extent':'benchmark_condition_components_recorded_but_focal_bug_oracle_conflicts',
        'cross_unit_transfer_support':False, 'manual_validated_assembly':False, 'automatic_validated_assembly':False,
        'eligible_for_trusted_witness_census':False, 'retained_in_88_denominator':True,
    }
    save(OBS / f'adjudicated/{case}.json', d)
    print(case, 'oracle_conflict retained in cohort')
