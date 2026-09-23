# Continuous observation windows

This prototype changes the unit given to the same ABC analogy kernel. A unit
ends at an existing assertion capsule: native assertions, recognized standard
assertions and source-resolved oracle-helper calls all use the same interface.
The beginning is the earliest direct statement reached by the corpus's local
value/may-effect dependencies, plus its expected-definition fallback. Every
statement between that point and the observation is included, with exact source
bytes and gaps. Go reporting guards remain complete `if` statements; nested
control flow is never flattened.

This addresses an open-call limitation. Separate A/B tests can each define a
local `x`, while C defines `y`. In a call-only term the B binding is unavailable
in C. In the window `x = 1; verify(x, 2)` the declaration and use form one unit,
so the existing restricted local-binding correspondence can transport the
whole edit to `y = 3; verify(y, 6)`. No new expected-value generator is added.

`extract.extract` returns source window records. `generate.generate` reuses
the same 128-output/2000-attempt/top-10 instance driver, parent-fair group limit,
neighbor order and output selection. `compose.compose` calls the unchanged v3
alignment/analogy kernel, using the fixed residual-first insertion order. The
alternative insertion order is not searched in this prototype. The generated
edit replaces only C's exact window span; parent code before and after it stays
unchanged. Native and helper assertions are not combined into separate budgets.

C statements not classified as dependencies are protected. Residual gaps stay
in original order exactly once under the kernel's reconstruction checks. A gap
may also be a common alignment anchor, but its entire source unit, including
trailing trivia, must match the output byte for byte. The witness records its
source and output statement positions. Modified, dropped or reordered gaps are
rejected. Internal references must bind inside the generated window; external
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

All validation is source-only and uses invented examples. No subject outputs,
reference patch, pilot/holdout results or model calls determine the proposal.
