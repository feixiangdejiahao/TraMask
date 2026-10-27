"""Two independently reviewed recoveries of executed stock tests."""
from root_record_io import start, finish, receipt, OBS


def recovery_receipts(cid):
    base = OBS / f'source_recovery/{cid}/attempt_stock_A001'
    return [receipt(base / 'report.json'),
            receipt(base / 'original/files/vm_test.go'),
            receipt(base / 'checkpoint/files/vm_test.go')]


d, reviews, raw = start('S073')
d['stock_source_recovery'] = {'receipts': recovery_receipts('S073'),
    'original_and_checkpoint_source_identical': True,
    'historical_execution': 's78_c0 full go test ./...: root package0.966s, not cached. Later88/91cached outputs corroborate unchanged test membership only.',
    'new_test_execution': False}
d['historical_joint_witness'].update(reason='Stock sibling-local sharing and the authored cloned composite execute separately; no full cloned shared-local witness is established.')
d['minimal_assembly']['proposal'] = 'Retain outer global n10 and original clone/Go-call sequence. Create both original +1/+2 mutators inside a factory with one local n10 and return their original array. Keep return assertions11/13; explicitly change final clone global-n assertion13 to10 because mutation now targets local capture.'
finish(d, raw, actions_checked=['s43_c0', 's52_c0', 's55_c0', 's78_c0', 's88_c0', 's91_c0'], extent='exact_recovered_shared_local_context_with_related_clone_check', notes=[
    'Both independent reviews now locate stock TestAssignment with two mutators and a reader sharing one factory local; cumulative expected6 is hard-asserted. This strengthens the Context from related single-closure components to an Exact executed condition.',
    'Root verifies original/checkpoint vm_test.go SHA256 equality and the complete literal. Recovery itself executes no test. Historical78 is the fresh full root-package execution;88/91 are cached and not the primary reachability proof.',
    'Base source43 initially has incorrect seed-based expectations;52 corrects them and explicitly reports this named test PASS even though other tests fail;55 selected suite passes.',
    'Preserving local aliasing through Clone is a newly combined relation. The original global13 tail assertion becomes wrong after moving mutation to a local; explicitly change it to10 rather than claiming all assertions remain unchanged.',
    'Two logical units, one transferred shared-local condition, one new scope-adjusted Check. Known T13 case remains marked and is not a fresh independent discovery.',
    'No assembled P/R execution has been performed in this study.'
])

d, reviews, raw = start('S076')
d['stock_source_recovery'] = {'receipts': recovery_receipts('S076'),
    'original_and_checkpoint_source_identical': True,
    'historical_execution': 's221_c0 go test ./... -count=1: root package1.102s.',
    'new_test_execution': False}
d['missing_factors'][0]['role'] = 'Trigger'
for f in d['required_factor_inventory']:
    if f.get('missing_factor_id') == d['missing_factors'][0]['factor_id']:
        f['role'] = 'Trigger'
d['historical_joint_witness'].update(reason='Stock tests construct present undefined map/array elements; authored destructuring tests separately execute defaults and UndefinedValue observations. No present-undefined-plus-default correct witness found within S076.')
d['minimal_assembly']['proposal'] = 'In the original present-map renaming-default row, change {x:10} to {x:undefined} and expected10 to tengo.UndefinedValue; preserve default50, binding and expectRun helper.'
d['minimal_assembly']['source_granularity'] = 'Three semantic source units: original default/present-value row; stock present-undefined collection row; authored missing-value UndefinedValue observation row. Distinct rows count separately even when they share a Go test function.'
finish(d, raw, actions_checked=['s99_c0', 's101_c0', 's103_c0', 's105_c0', 's163_c0', 's221_c0'], extent='exact_recovered_undefined_trigger_with_related_default_check', notes=[
    'Select A\'s map row; B independently locates the equivalent array present-undefined stock row. Both establish that explicit undefined inside a present source collection was historically executed.',
    'The collection literal is input to destructuring, hence Trigger rather than Context. Binding/default syntax stays the same; the source value and expected result change.',
    'The stock enum.find map row has present keyc:undefined; the full default-preservation expectation still derives from the issue rule that only missing keys activate defaults. The stock filter result does not itself assert that default rule.',
    'Definition99 initially fails out redeclaration;101 corrects out,103 has a malformed helper declaration,105 removes it and selected suite passes.163 prints final test bodies;221 uncached full suite passes.',
    'Count three logical units and two transferred fragments, including the independent undefined observation row. B\'s two-unit count groups distinct array rows; root keeps uniform row granularity.',
    'S075\'s separate diagnostic is not a donor for S076. Source recovery changes this case\'s provenance without adding any new historical execution or claiming a successful repair.'
])
