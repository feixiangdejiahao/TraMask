"""Recovered Promise reaction and corrected native callback are separate donors."""
import copy
from root_record_io import OBS, start, finish, receipt

d, reviews, raw = start('S012', 'B')
d['native_callback_version_audit'] = copy.deepcopy(reviews['B']['native_callback_version_audit'])
d['source_recovery'] = receipt(OBS / 'source_recovery/S012/attempt_stock_A001/report.json')
d['minimal_assembly']['proposal'] = 'Replace the explicit host-enqueued GenericJob trigger with an engine-generated resolved Promise.then reaction under the existing evaluation handle. Reuse the corrected traced-GcRefCell native callback and boolean state, cancel before drain, and retain the false side-effect decision through borrow().'
d['historical_joint_witness']['reason'] = 'Stock Promise reaction, active-handle native callback, and cancelled explicit-job suppression executed separately; no complete generated-reaction cancellation witness was found.'
d['assertion_preservation_scope'] = {'semantic_decision': 'cancelled queued side effect leaves boolean false',
    'byte_identical_assertion': False,
    'representation_change': 'Rc<Cell<bool>> get becomes executed donor Gc<GcRefCell<bool>> borrow for trace-compatible native capture',
    'classification': 'Trigger transfer with explicit representation adaptation; not pure Context repair'}
finish(d, raw, actions_checked=['s73_c0', 's84_c0', 's86_c0', 's93_c0', 's94_c0', 's186_c0', 's188_c0', 's196_c0', 's197_c0', 's202_c0'],
    extent='related_executed_promise_and_native_callback_components_with_retained_boolean_decision', notes=[
        'The recovered stock promise test executes new Promise(...resolve(undefined)).then(...), asserts count2 before run_jobs and count3 afterward.186→188 unfiltered1074PASS binds its actual execution; original/checkpoint/CAS source is identical.',
        'The original host GenericJob cancellation test and native callback unit complete197→202 with20named passing tests. They establish separate handle/cancel/drain and host-side effect components.',
        'Root found that the initially cited73 native Rc capture did not compile:84 reports Trace and tuple errors.86 replaces it with traced GcRefCell and correct tuple destructuring;93/94 clean the statements and196 formats the file. Only this corrected version is transferred.',
        'Select B three-unit route: original cancellation base, corrected native callback/state donor, and stock Promise reaction. Three fragments represent two donor units; one new generated-reaction/handle/cancel relation, zero new external primitive.',
        'The false side-effect oracle is retained semantically, with an explicit storage/access adaptation. A instead uses a JavaScript global and derives a new post-cancel zero Check; retain that distinct three-unit alternative rather than mixing its missing-factor count with B.',
        'The sole selected Verifier panic concerns generated Promise reaction cancellation; later job-kind assertions may not be reached. No assembled P/R run or automatic candidate has occurred.'
    ])
