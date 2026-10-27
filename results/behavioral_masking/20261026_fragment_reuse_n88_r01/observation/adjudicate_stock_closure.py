"""Root resolutions of the finite stock-source lead audit and receipt corrections."""
import copy
from pathlib import Path
from root_record_io import OBS, read, start, finish_revision

RESOLUTIONS = {
    'S007': 'Stock JSON tests execute nonempty results parsing and decisions. They strengthen related output observation, but do not supply the empty-results relation. Retain the two-unit authored-helper construction and do not import its --exit-zero invocation flag.',
    'S013': 'Stock ordinary converter.structure rejects a required TypedDict integer with invalid input. Its actual exception checks reinforce a related rejection component; they do not assert partial_structure.value is None. Retain the selected exact162 probe plus attrs required-field None oracle, two units.',
    'S016': 'The five inspected query/object navigation stock files contain neither raw HTML head/body normalization nor the alternative nested-list ownership rule. Keep the selected raw-script normalization Check repair; generic lookup syntax is not another semantic donor.',
    'S017': 'Stock object projection and map/array lookup do not establish inner HTML list ownership. The exact nested CLI stimulus remains historical; the correct structural Check remains absent from inspected executed validation.',
    'S020': 'Stock OpenApi.test.ts hard-compares responses200.content.application/json.schema after OpenApi.fromApi, and195→197 explicitly completes the selected files with82passes. This supplies an additional Related metadata Check path. Keep the selected two-unit construction using correct printed145/158 metadata; a stock-hard-oracle variant uses a third unit. The stock ordinary HTTP schema is not an exact SSE union oracle.',
    'S025': 'The apparent natural-sort stock donor is Agent-added and contains the same wrong file7-before-file007 tie expectation. It is not a new correct oracle. The patch hunk has307lines including3context, hence304added; the collector correction is preserved separately.',
    'S026': 'B removed an undefined navigation reference from selected IDs. This is a receipt correction; the independently checked primary factors and source-unit counts are unchanged.',
    'S027': 'The /*! text in the stock docStub is an expected diagnostic annotation, not executed block documentation. Fourteen ordinary block-comment examples do not exercise the required block-doc input. Retain bounded Absent Trigger.',
    'S028': 'Stock merge-base tests check commit graph ancestry and TestResetMerge checks unstaged reset protection. Neither supplies overlap intervals or conflict expectations for the new multi-line text merge operation.',
    'S029': 'The stock cookie tests cover path matching, clearing and deletion; the inspected examples do not assert retention and ordering of two matching same-name cookies. Keep the missing selected Check Absent.',
    'S033': 'Ordinary Box maxWidth stock examples do not supply the finite-max fractional-grid joint. Preserve root Related components and the new finite-max/gap positioning relation; do not treat generic numeric width assertions as the complete oracle.',
    'S034': 'The stock column-align-self-stretch case gives parent width7 and no child width, then hard-compares the child border of width7.132 selects this ordinary test and reports73passes plus2known expected failures. This strengthens Related allocated-width support but still uses an ordinary flex child rather than a fractional grid. Keep the selected three-unit candidate and the separate historical complete finite-max witness baseline.',
    'S036': 'Actual stock TestClose writes, closes, successfully drains buffered data, and only then obtains one terminal read error. It supplies a concrete same-closed-receiver repeated-read sequence, beyond generic Read syntax; it does not test a second read after the first terminal error. Keep root Related classification, original two-unit construction, and the newly derived terminal-persistence relation. The UDPSession donor is an alternative component, not an exact MuxStream oracle.',
    'S038': 'Stock listeners code preserves one logic wrapper across resetContext and remount, but128 has only aggregate failed/passed totals and no selected-body receipt. Record that possible exact relation as execution-unresolved. Root retains Related support for the separately verified disabled-construction and enabled-mount components; this does not claim the retained-wrapper cross-reset joint executed. A/B null applies to that more specific unverified stock relation.',
    'S055': 'B removes superseded54 fragment IDs and proposes a two-unit stock route. Root retains the three-unit A construction, because the equality child54 was index-pruned and95 independently establishes an entered failing predicate. Selected nested-negation and entered-failure factors remain Exact; their profiler joint remains unexecuted.',
    'S061': 'Stock deriv and function-registration tests do not cover invalid-semver ordering. sort_test.go is Agent-added and already accounted for. Preserve the task-derived validity rule and actual lexical components without inventing a stock invalidity oracle.',
    'S066': 'B corrected a stock unit ID to distinguish it from the authored base. The actual uppercase option donor, lowercase aggregate donor, original full-layout Check and three-unit root construction remain unchanged.',
    'S075': 'Stock literal undefined and conversion fallback tests do not decide whether a present undefined map entry suppresses a destructuring default. The already present undefined input is not counted again as a missing donor. Preserve the existing Related Check mapping and new task-specific relation.',
    'S082': 'The stock Browser runner fixture constructs a runner without start or onFinish; onGlobalError must immediately set finished=true.174 actually runs this file within273passing tests. This supplies a Related pre-start lifecycle condition for the Process.abort proposal, not an exact cross-runner operation. Keep the original reference kill-count conflict unresolved.',
    'S086': 'The stock preserve-all-locals benchmark is not historically invoked and has no trap/decoder Check; host float parameters are not declared float locals at a trap. Coredump test files are Agent additions whose decoder reads operands without asserting zero. Preserve Related observation support and Absent zero-count Check.',
    'S087': 'Coredump files are Agent-added. Stock benchmark drops operands without trapping or decoding, and host float calls do not supply the omitted stack-empty oracle. Original decoded frame is already in the base and does not count as a new missing donor. Retain Absent Check.'
}

for cid, resolution in RESOLUTIONS.items():
    d = read(OBS / f'adjudicated/{cid}.json')
    proposed, reviews, raw = start(cid)
    paths = []
    for who in ['A', 'B']:
        review = reviews[who]
        recovery = review.get('source_recovery_audit', {})
        for rec in recovery.get('source_receipts', []):
            p = Path(rec.get('path', ''))
            if '/source_recovery/' in str(p) and p.name == 'report.json' and p not in paths:
                paths.append(p)
        closing = review.get('stock_leads_closure_review_B', {})
        if closing.get('report'):
            p = Path(closing['report'])
            if p not in paths:
                paths.append(p)
    d['stock_source_closure'] = {
        'status': 'named_leads_adjudicated', 'resolution': resolution,
        'source_recovery_reports': [str(p) for p in paths],
        'independent_review_source_notes': {who: copy.deepcopy({
            k: reviews[who][k] for k in ['source_recovery_audit', 'stock_leads_closure_review_B',
                'workspace_visible_candidate_components', 'alternative_target_evidence']
            if k in reviews[who]}) for who in ['A', 'B']},
        'new_candidate_execution': False,
        'scope': 'Concrete previously identified stock-source leads; no claim of exhaustive unrecorded history.'}
    if cid == 'S082':
        for key in ['required_factor_inventory', 'agent_base_units', 'missing_factors', 'minimal_assembly']:
            d[key] = copy.deepcopy(proposed[key])
        d['minimal_assembly']['proposal'] = 'Remove only synthetic Process runner onFinish initialization, mapping the executed Browser pre-start no-callback lifecycle into the original abort unit. Keep its operations/checks and separately qualify reference repeated-kill behavior.'
        extent = 'related_executed_prestart_runner_lifecycle_with_reference_baseline_conflict'
    else:
        extent = d['counts'].get('historical_support_extent', 'prior_root_factor_classification_retained_after_stock_lead_closure')
    # Updated review proposals are preserved without overwriting root-selected
    # source counts or merging different focal failures.
    d['minimal_assembly']['closing_source_proposals'] = {
        who: copy.deepcopy(reviews[who]['minimal_assembly']) for who in ['A', 'B']}
    if cid == 'S038':
        d['stock_source_closure']['specific_cross_reset_execution'] = 'unresolved'
        d['stock_source_closure']['verified_lower_bound'] = 'Related separate disabled-construction and enabled-mount components'
    actions = []
    for p in paths:
        report = read(p)
        for aid in report.get('runner_ids', []):
            if isinstance(aid, str) and aid.startswith('s') and '_c' in aid and aid not in actions:
                actions.append(aid)
        binding = report.get('historical_execution_correspondence', {})
        if isinstance(binding, dict):
            for key in ['start_action', 'completion_action']:
                aid = binding.get(key)
                if isinstance(aid, str) and aid not in actions:
                    actions.append(aid)
    finish_revision(d, raw,
        reason='Complete the independently reviewed finite stock-source lead audit and bind final review versions; retain prior scientific records.',
        actions_checked=actions, notes=[resolution], extent=extent, recovery_paths=paths)
