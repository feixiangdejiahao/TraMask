# Helper expected literal slots, 2026-09-30

`experimental/helper_expected_slots.py` adds an independent oracle interface for
one already generated, fixed Go combination candidate. It generates no new
inputs or candidate combinations. It invokes neither a model nor a subject.
The main request generator and production custom-call validator are unchanged.

The interface reuses the restricted `HelperIndex` analysis: a unique same-package
helper has a source-proven `*testing.T` parameter, one failure comparison between
a bare formal and an observation derived from other parameters, and no use of
that formal outside the check/diagnostic. The helper's source, comparison and
prerequisite guards remain visible. This role is a source hypothesis, **not** a
correctness contract or a proof of a safe semantic edit.

Every concrete call has its own expected argument span. The existing argument
must already be a Go scalar literal. Identifiers, opaque calls such as
`saveAndReturn()`, scalar wrappers, containers, ambiguous helpers and unsupported
helper shapes remain read-only. Replacing an effectful argument with a literal
would remove an operation, so it is not allowed.

The original complete test, complete program-modified test, issue contract,
input edits/import bindings, every original assertion, every discovered helper
call, and complete referenced helper declarations are supplied together. The
model must decide every editable ordinary/helper slot jointly. Omission or
unknown does not mean preserve. If a necessary change falls outside the slots,
the complete candidate remains unknown. Required behavior comes from the issue
and validation evidence, never from copying the buggy patch's output.

Only a new scalar literal can be supplied; there is no test-body or assertion-
body response field. The independent validator regenerates the inventory and
checks original source/candidate hashes. Ordinary assertion revisions additionally
reuse the existing operand guard. For a helper, the validator replaces precisely
its literal source span and reconstructs the expected-only complete test bytes.
It never edits the callee, other actual arguments, helper declaration, comparison
operator or failure body.

When a slot lies inside an existing program replacement, its bytes are spliced
into that replacement. Otherwise its position is mapped back to the untouched
original source. Multiple call slots are applied separately in descending byte
order; their full reconstructed test must match the candidate preview exactly.
This covers inserted calls and repeated equal call text without combining their
expected values. A fresh revision retains a semantic hypothesis flag and can be
passed to the existing executor; it is not declared correct by this validator.

`HelperIndex` received necessary generic source fixes before this interface was
frozen. Go var/const/type/range declaration names must deny a shadowed testing
receiver or a pseudo-pure import/builtin. Changing a failure comparison changes
its failure branch's control, so an opaque subject action there is unsupported
even when it does not consume the expected value. Pure local string/byte
diagnostic formatting is supported only with exact standard import bindings;
standard `bytes.Replace`/`ReplaceAll` return a separate result. A local overwritten
in the failure branch is denied if read afterward or taken by address anywhere
in the helper. These are finite syntactic boundaries, not a heap/CFG isolation
proof. Existing snapshots retain their historical helper implementation.

Original helper prerequisite error/Fatal guards and all helper source are frozen.
Ordinary Go predicate-method slots are read-only in this literal-only interface.
It therefore **narrows some ordinary capabilities while adding helper ports**;
it is not an equivalent extension of the singleton interface. The census reports
ordinary increases/decreases separately and keeps the original ordinary baseline
when selecting candidates that previously had no interface.

APIs:

```python
from experimental.go_assertion_helper import HelperIndex
from experimental.helper_expected_slots import inventory, prepare_request, apply_response

index = HelperIndex(corpus)  # Optional original index shared within a source case.
rows = inventory(corpus, frontend, program_candidate, index=index)
prepared = prepare_request(corpus, frontend, program_candidate, issue, index=index)
request = prepared['request']  # None for unknown/no-slot/over-budget source.
result = apply_response(request, model_payload, corpus, frontend)
# result.status: preserve, adapt, or unknown.
# result.candidate: executor input for preserve/adapt, otherwise None.
```

The index is rebound after modifying the source owner; per-candidate resolution
state is fresh. Declarations below the changed test receive their shifted byte
spans. It does not reuse a previous variant's equal-length call binding.

Validation after the final code changes:

```text
.venv/bin/python -m pytest -q tests/test_helper_expected_slots.py tests/test_helper_expected_slots_review.py tests/test_go_assertion_helper.py tests/test_helper_expected_slots_census.py
76 passed (26 interface + 13 independent review + 33 helper + 4 census tests)
```

Tests exercise UTF-8 spans, distinct repeated calls, helper/ordinary joint
decisions, whole-call program replacements, inserted calls, reordered callees,
shifted declarations, opaque original/new expressions, failure-control effects,
local address escape, retained prerequisites, source/record tampering, malformed
answers and a complete-source budget that never truncates code.

The completed source census over all 4,502 fixed candidates found 30 new helper
ports, all in N05 and all from one source helper declaration. The new literal-only
interface also loses 555 previously eligible Go candidates, so it does not replace
the production interface. Eight source-selected fresh requests produced four
independently correct whole-test revisions and four length/empty-content unknowns.
All eight combinations fail with old expectations; all four revisions pass native
execution, with all original controls passing. This repairs four old-expectation
alarms in that fixed component cohort, not a target gap or the 16/17 main score.
See [the separate evaluation](helper_expected_slots_evaluation_20260930.md) for
selection, source review, paired execution and capability loss. No prior model
answer is used to make a port eligible.
