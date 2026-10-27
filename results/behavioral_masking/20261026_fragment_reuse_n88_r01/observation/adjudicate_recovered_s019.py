"""Default-option state is exact; its conditional-schema joint remains untested."""
from root_record_io import OBS, start, finish, receipt

d, reviews, raw = start('S019', 'B')
d['minimal_assembly']['proposal'] = 'Remove the explicit mode:put option from the original two parser calls, retaining schema, missing/present dependent values, ZodError expectation and formatter controls.'
d['historical_joint_witness']['reason'] = 'Stock omitted-options parsing and authored requiredIf with explicit put were executed separately; their joint was not.'
recovery = OBS / 'source_recovery/S019/attempt_stock_A001/report.json'
d['source_recovery'] = receipt(recovery)
d['option_state_correspondence'] = {
    'wrapper': receipt(recovery.parent / 'checkpoint/files/src/schema/actions/zodSchemer/zodSchemer.ts'),
    'inner': receipt(recovery.parent / 'checkpoint/files/src/schema/actions/zodSchemer/parser/item.ts'),
    'stock_test': receipt(recovery.parent / 'original/files/src/schema/actions/zodSchemer/parser/item.unit.test.ts'),
    'mapping': 'ZodSchemer.parser defaults options to{} and passes them unchanged to itemZodParser; directly calling the inner function without options reaches the same{} state.',
    'historical_joint_execution': False}
finish(d, raw, actions_checked=['s156_c0', 's161_c0', 's174_c0', 's180_c0'],
    extent='exact_executed_default_option_state_with_retained_conditional_check', notes=[
        'Stock item.unit.test.ts calls itemZodParser(schema) without options and actually parses values with hard results.156 explicitly reports all4 item tests and212total passing. Original/checkpoint/CAS stock source is identical.',
        'Authored161 requires the missing dependent field to throw under explicit put.174 removes an unsupported update-mode test and has a separate typecheck error;180 later actually runs all8tests successfully.',
        'A classifies the whole public-default conditional scenario Related; B isolates the missing option state as Exact. Root adopts B factor boundary: wrapper default{} is passed unchanged into the same inner parser whose omitted-options state was actually executed.',
        'No claim is made that the public requiredIf/default joint ran historically. Two units, one transferred context condition, zero new semantic ingredients; the combined application still requires execution.',
        'Original target values and rejection/assertion semantics are retained. This is a source-supported Context-only proposal, not yet a four-cell P/R success.'
    ])
