# Source-backed assertion instances

This is a representation adapter for the existing test-analogy kernel, not a
new oracle rule. A parent test can contain many independently identified calls
to a helper that evaluates the subject and checks its expected result. Treating
the entire parent body as one term hides these examples from A/B/C selection.

`extract(corpus)` obtains each call from existing `helper_assertions` metadata.
It checks that the call is one direct expression statement of its actual parent
test, verifies the helper's lexical binding against its recorded definition,
and retains the exact statement bytes. The record contains its original parent
test ID, a distinct instance ID, and input/expected ports mapped through the
helper's existing formal/actual bindings. Identical input and expected values
have separate source spans and roles; they are not matched by string search.

`compose(corpus, A, B, C)` calls the unchanged v3 aligned analogy kernel on
these single-statement terms. A/B/C may have the same parent test ID but must
have distinct instance IDs. Its ordinary emitter candidate replaces **only
C's statement** in a clone of the actual parent test. Imports, other statements,
fixtures and surrounding scope stay in place. A full clone of the original
parent remains the source control. For example, source calls
`verify(1, 2)`, `verify([1], [2])`, and `verify(3, 6)` can produce
`verify([3], [6])` without manufacturing a helper or a test fixture.

Admission is deliberately narrow: known literals and original caller parameters
are supported, along with syntactically closed Go composite literals, pointers
to those literals, and unshadowed-in-this-file predeclared type conversions.
Map keys are value expressions; bare struct field keys are treated as labels
only for inline structs or an unambiguous same-file top-level struct definition.
Rebound formals, caller locals, arbitrary argument calls, nested control flow,
unresolved helper argument binding, and uninstantiated parameter rows are
explicitly unsupported. No helper/API name is built into this adapter.

These checks do **not** prove purity, the runtime shape of caller parameters,
cross-file shadowing of Go predeclared names, or absence of helper/global state.
Replacing C may affect later assertions in the preserved parent. Helpers may
mutate shared parameters, and transported expected values may be semantically
wrong. The candidate is therefore still a hypothesis requiring the existing
semantic admission and source-control checks. It never executes the subject to
invent an expected result. Unsupported cases are coverage gaps, not passes.

`generate(corpus, budget=Budget(), refine=...)` is the independent helper-only
driver. It uses instance IDs for triple distinctness and parent test IDs for
retrieval priority, source evidence and emission. It keeps the same default
128-output/2000-attempt/top-10 budget. Input representations are cached once;
groups take up to 64 instances by parent-test round robin, A/C use skeleton
neighbors, B neighbors rotate syntax shapes, and search rotates A focuses.
Output selection rotates parents and C call locations. Existing statements are
excluded by host AST with trivia removed and the existing restricted local
alpha normalization; candidates deduplicate by parent, C span and replacement.
Internal term-keyed substitutions are removed before JSON serialization.

`gate_evidence` presents the exact A/B/C calls, their true parent IDs, complete
parent tests, helper definitions and source argument/observation ports. It says
explicitly that three instances may occur in one test, and asks for the validity
of the whole edited parent. This is an alternative unit-granularity experiment:
it neither adds full-body proposals to the budget nor modifies the original
v3 driver, main CLI or experiments.

The synthetic tests enumerate all three-instance permutations, verify Python,
Go and TypeScript generation/emission, Unicode and reordered keyword spans,
same-value dual roles, Go aggregate/cast boundaries, helper shadowing, explicit
unsupported cases, and deterministic extraction limits. They use no pilot,
holdout, production execution, model service or reference patch.
