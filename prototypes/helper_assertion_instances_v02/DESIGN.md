# Open helper-call terms

The unit remains one source-backed oracle-helper call and the parent C test
remains intact. Requiring every argument to be a literal/formal was therefore
stronger than scope preservation needs: C can already contain the local setup,
module constant or existing builder that the generated call references.

This isolated adapter attaches a lexical environment to each call. Every free
reference records its actual binding identity, source declaration, helper
argument port and resolution precision. Argument calls are retained as code,
with effects marked unknown; they are never executed to compute an oracle.
The same v3 reconstruction kernel still constructs D.

For variable occurrences aligned at the same helper argument port in A and C,
the adapter may propose an explicit A-binding to C-binding correspondence. A
reference in B follows that correspondence only when it refers to the actual
A binding. The name spelling is irrelevant: two distinct `x` bindings can
correspond without a claim that their values are equal. If spelling is equal,
the environment substitution changes binding provenance while the token stays
`x`. After composition every output reference is resolved again inside the
complete C source. It must resolve to the transported origin, including the
explicit C endpoint of a correspondence. Missing B-only locals and accidental
capture by a same-named C local are rejected.

For example, A/B may share `small = 1` and call `verify(small, 2)` and
`verify([small], [2])`, while C contains `large = 3; verify(large, 6)`.
The new call is `verify([large], [6])`; its `large` reference is checked against
C's existing declaration. This establishes lexical provenance, not the
semantic correctness of lifting `subject` to lists. That remains a gate question.

`core.extract/compose` are independently runnable. `generate.generate` uses
the same Budget and bounded search through explicit extraction, composition
and novelty callbacks; their defaults retain the original adapter's behavior.
The novelty callback includes actual binding identities in the host AST key,
so equal token spelling in different local environments is not an automatic
"already present" result. The evidence includes A/B/C calls, full parent tests,
helper definitions, lexical declarations, explicit correspondences and effect
unknowns. It does not label the three calls as independent tests.

Limits remain explicit. Lexical identity is not value/state equivalence; calls
can mutate globals, arguments or later assertions. Dynamic rebinding, aliasing,
unknown receivers and unresolved external names remain unknown. An unresolved
reference is transportable only when the output retains its recorded lexical
context; this is not proof of its runtime declaration. Inline binders, unresolved
helper parameter binding and uninstantiated parameter rows remain unsupported.
The current kernel still rejects A/C with entirely identical syntax even when
their environments differ. Cross-parent A/B variables with separate identities
are not inferred equivalent from matching names. Syntactic novelty may also
miss distinctions caused solely by state at different call positions.

All validation uses invented Python/Go/TypeScript examples. A test builder
contains an unconditional exception to demonstrate that analysis never invokes
it. No pilot, holdout, reference code, execution results or model calls inform
this adapter.
