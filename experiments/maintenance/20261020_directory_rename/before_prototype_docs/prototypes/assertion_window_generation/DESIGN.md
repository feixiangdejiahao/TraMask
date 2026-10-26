# Continuous observation windows

This prototype changes the unit given to the same ABC analogy kernel. A, B
and C are three distinct source windows, which may belong to the same parent
test. A window ends at the complete direct parent statement containing an
existing assertion capsule. Native assertions, recognized standard assertions
and source-resolved oracle-helper calls use the same interface. The beginning
is the earliest direct statement reached by the corpus's local value/may-effect
dependencies, plus lexical expected-definition links that retain conditional
may-definitions. Every intervening statement is included with its exact bytes.
Go reporting guards remain complete `if` statements; nested control flow is
never flattened. An enclosing control statement can also include code after
the particular assertion. This is not a minimal or complete semantic slice.

This addresses an open-call limitation. Separate A/B tests can each define a
local `x`, while C defines `y`. In a call-only term the B binding is unavailable
in C. In the window `x = 1; verify(x, 2)` the declaration and use form one unit,
so the existing restricted local-binding correspondence can transport the
whole edit to `y = 3; verify(y, 6)`. No new expected-value generator is added.

`extract.extract` returns source window records. Default grouping uses the
file, enclosing lexical scope, parent parameter list and assertion predicate;
it does not require a shared observed call. C neighbors are ordered by syntax
skeleton similarity, while B neighbors rotate skeleton classes. Search rotates
A focuses. `generate.generate` reuses the 128-output/2000-attempt/top-10 instance
driver, including its parent-fair group limit and output selection. At least
one unit's parent must be a retrieval seed. Observation-dependence priority is
a separate variant, not the default window order. `compose.compose` calls the unchanged v3
alignment/analogy kernel, using the fixed residual-first insertion order. The
alternative insertion order is not searched in this prototype. The generated
edit replaces only C's exact window span; parent code before and after it stays
unchanged. Native and helper assertions are not combined into separate budgets.

C statements not classified as dependencies are protected. Residual gaps stay
in original order exactly once under the kernel's reconstruction checks. A gap
may also be a common alignment anchor, but its entire source unit, including
trailing trivia, must match the output byte for byte. The witness records its
source and output statement positions. Modified, dropped or reordered gaps are
rejected. Exactly-once preservation concerns the original C source occurrence,
not the number of runtime effects: B additions or substituted expressions can
introduce another similar operation. Internal references must bind inside the generated window; external
references retain their source identity or explicit parent-parameter slot.
Unresolved same-file globals remain explicitly unknown. Scope/arity checks run
on the full edited source, and the gate sees the complete parent and helpers.

This is an approximate source window, not a sound semantic slice. Aliases,
globals, fixtures and helper effects can escape the local graph. Including
intervening statements preserves their original C occurrence but does not prove
that B additions commute with them. Definitions can be live after the window:
`y = [3]; verify(y, [6])` may reconstruct correctly yet invalidate a retained
later `assert isinstance(y, int)`. Such a proposal remains a hypothesis for
whole-parent admission, not a valid test claim. The synthetic suite includes
this counterexample. Nested binders and repeated definitions can prevent the
restricted alpha correspondence. The current anchor spelling can also reject
an otherwise plausible `xs.append` to `ys.append` receiver renaming.

Extraction and composition checks are source-only; their unit tests use
invented examples. No subject outputs, reference patch, pilot/holdout results
or model calls determine the constructed proposal. Source reconstruction proves
syntax provenance, not oracle correctness; see the [finite-example boundary](../notes/test_edit_oracle_boundary.md).
The gate must assess the complete edited parent. AST novelty checks only remove
matching windows within the compared group, not semantically equivalent tests.
Unsupported or unsearched combinations remain coverage gaps.

`balanced.py` is a separate representation ablation. It changes only the
refinement callback to the existing v4 balanced-delimiter representation, with
its existing flat fallback. It keeps the same search, analogy kernel, parent
preservation checks, budgets and gate. Flat and balanced candidates are not
pooled. Neither representation establishes embedded-language semantics.

`predicate_free.py` is a separate grouping ablation. It removes only predicate
equality from the group key, retaining the same lexical scope and parameter
interface. Extraction, composition, neighbor-order policy, budgets and gate
requirements remain unchanged; the default grouping is unchanged. A larger
eligible pairing space can crowd out other proposals under fixed budgets, so
candidate counts need not increase. Neither validity nor effectiveness follows
from removing this constraint.
