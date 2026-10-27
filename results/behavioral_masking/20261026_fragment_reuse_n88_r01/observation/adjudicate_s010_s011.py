"""Keep scanner-input placement, check sensitivity and oracle ambiguity distinct."""
from root_record_io import start, finish, read, receipt, RUN
from pathlib import Path


def placement_role(d):
    d['missing_factors'][0]['role'] = 'Trigger'
    for f in d['required_factor_inventory']:
        if f.get('missing_factor_id') == d['missing_factors'][0]['factor_id']:
            f['role'] = 'Trigger'
    d['oracle_availability']['status'] = 'unresolved_indentation_vs_statement_continuation'
    d['oracle_availability']['available_to_blind_system'] = None
    d['historical_joint_witness'].update(reason='Executed source-layout components exist, but no trusted complete closing-only activation witness is established.')


d, reviews, raw = start('S010')
placement_role(d)
assist = read(RUN / 'observation/adjudication_assists/S010.json')
p = Path(assist['workspace_mechanism_receipt']['source']['path'])
d['check_sensitivity_audit'] = {'source': receipt(p),
    'scope': 'Read qualified final-P code, not an executed historical donor.',
    'finding': 'B602 issue lineno is assigned from context.get_lineno_for_call_arg("shell"). Original multiline target starts at3 but shell argument is5; assertNotIn((3,B602)) therefore does not observe its finding.',
    'necessary_change': 'Observe the shell argument or the full target statement range and preserve outside-control presence. Merely retaining call startline3 is insufficient.'}
d['minimal_assembly']['proposal'] = 'Transfer inline-begin placement from113 into multiline source75/76, with separate closing line, and repair the protected finding observation to cover the actual shell argument/statement. Keep outside control. Resolve dedent boundary before assigning expected suppression.'
finish(d, raw, actions_checked=['s75_c0', 's76_c0', 's113_c0', 's127_c0'], extent='related_layout_transfer_requires_check_repair_and_oracle_resolution', notes=[
    'Both reviews select sole official058 failure; all69F2P pass. Original75/76 hard Check is sensitive only to call startline3, while the B602 plugin reports the shell argument at5.',
    'A\'s observation-repair concern is confirmed by final-P source. B\'s proposal retains startline3 and only rebases the control, so it can still pass with an unsuppressed target finding; it is not a sufficient context-only candidate.',
    'Step76 explicitly names the original statement-wide test as ok; step127 includes109 functional tests. Step113 actually executes inline-begin nonretroactivity, supplying a related placement component.',
    'Directive/comment layout is scanner input, hence Trigger. The full last-argument/closing-line relation is newly composed, not absent merely because it was never run jointly.',
    'Issue automatic dedent versus statement-wide union remains unresolved at this exact boundary, as inS009. Preserve that uncertainty separately from the verified check-sensitivity defect.',
    'Two source units, one transferred inline placement, two new semantic changes including observation repair. No new P/R execution.'
], compatibility='unresolved_boundary_oracle_with_required_assertion_repair')

d, reviews, raw = start('S011')
placement_role(d)
d['minimal_assembly']['proposal'] = 'Use original functional test64 with full issue-ID/count/metric checks. Transfer multiline Popen layout from66 and move begin to the last argument; mechanically rebase control line numbers. Resolve exact closing-dedent semantics before requiring original suppression outcome.'
finish(d, raw, actions_checked=['s64_c0', 's66_c0', 's103_c0'], extent='related_layout_transfer_with_existing_sensitive_check_oracle_unresolved', notes=[
    'Select A\'s original hard functional test64. It requires exactly2 findings and full list[B603,B602], plus metrics, so an extra protected B602 is detected regardless of the shell-argument line.',
    'B uses printed multiline diagnostic66 as base and would require a new Check or transfer of64. The two constructions must not share a claim that the original hard assertion is unchanged.',
    'Step64 runs82tests OK;66 executes multiline-region and next-line probes with one outside B603; final103 runs302tests OK. These establish separate layout and hard-observation components.',
    'The new source layout is Trigger rather than prior environment Context. Expected control line-number changes are mechanical only if they continue observing the same calls.',
    'As inS009/S010, smaller indentation at the sole closing line conflicts with an unconditional assumption of active region. The expected boundary outcome remains unresolved.',
    'Two units, one transferred multiline component and one new placement relation. No assembled execution-positive result claimed.'
], compatibility='unresolved_task_oracle')
