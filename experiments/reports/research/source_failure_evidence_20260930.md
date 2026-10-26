> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/source_failure_evidence_20260930.md) · [旧路径映射](../../../results/path_map.tsv)

# Source failure evidence, 2026-09-30

`experimental/source_failure_evidence.py` is an independent Go prototype. It
does not change production evidence, generate tests, invoke models, execute a
repository, or consult outcomes. It treats source behavior as evidence, never
as the required behavior of the program under test.

The small algorithm has two finite fixed points:

1. Seed calls of `Fail`, `FailNow`, `Error`, `Errorf`, `Fatal`, and `Fatalf` on a
   bare formal whose declaration is exactly `*testing.T`, with an import proving
   the standard testing package. Local bindings that shadow or write the receiver
   deny this proof. Resolve only unique top-level functions in the same directory
   and source package. Propagate possible failure reachability along these
   supported static calls.
2. At calls that can reach a seed, collect their enclosing source `if` and switch
   conditions. Track syntactic formal dependencies through direct local value
   definitions. Propagate only these condition dependencies through each call's
   actual/formal mapping until the finite formal sets stop growing.

For example, `if a != b { emit(t, message) }` followed by
`emit(t, message) { t.Log(message); t.FailNow() }` yields condition dependencies
`{a,b}` in the caller and an empty condition set in `emit`. Passing a value to a
diagnostic message does not make it a checked value. Renaming all functions and
parameters does not supply or alter their roles.

Every source fact retains byte spans, function source SHA, complete declarations,
call argument bindings, condition expressions, branch polarity, case patterns,
and syntax operand positions. Grouped formals and a variadic tail are preserved;
the tail does not cause the complete function to be rejected. Recursion is a
finite graph, not repeated source expansion. The order of binary operands does
**not** determine which is expected or actual.

The existing source grammar/AST utilities and corpus edit replay are reused.
Generic `Index.resolve` is not used because its Go package-name match is not an
import-path proof. Generic `Unit` parameter extraction also drops the second name
of `a,b interface{}`; this prototype reads every named formal field. `Flow` is
not used to classify failure predicates because its control/may-effect slices
would mix purposes. The dedicated dependency calculation follows conditions,
not all values passed to a failure wrapper.

Scope is intentionally restricted. Methods, imported-package dispatch,
interfaces, local closures, receiver aliases, heap effects, return-flow and path
feasibility are not resolved. Loop/select/scheduled-call scopes retain explicit
unknowns and are not traversed with an outer parameter environment. Early
returns do not produce a complete path condition: later checks retain lexical
order and complete source, not a runtime order or dominance proof. A false
`can_reach_failure` means no supported evidence was found, not that failure is
impossible. `partial_unknown` and the original unknown spans remain available.

The lexical implementation was corrected against independent counterexamples:
grouped var/const names, range binders and type aliases must deny a same-spelling
testing receiver/static callee; local short declarations in blocks and
if/switch initializers must not escape their scope. Ordinary initializer
assignments do persist. Parallel assignments read the old environment.

The tests cover the real structural pattern of a custom equality helper:
nil/type prerequisites, a type switch, local comparisons, recursive helper
calls, a variadic diagnostic wrapper, and a terminal standard testing sink.
Other tests cover all six sink methods, renaming, fake Fail objects, nonstandard
testing imports, ambiguity, recursion without a seed, exact UTF-8 locations,
scope shadows and bodyless assembly declarations. Validation:

```text
.venv/bin/python -m pytest -q tests/test_source_failure_evidence.py tests/test_local_helper_evidence.py tests/test_go_assertion_helper.py
94 passed (31 source-failure + 38 local-helper + 25 older Go-helper tests)
```

Live local helper version v3 fixes the same Go declaration-name omissions.
Historical local-helper v1/v2 census snapshots are preserved and do not acquire
this fix retroactively.

The direct source-only P5/P6 check finds, without package-path exceptions:

| Source function | Failure condition formal dependencies | Relevant source evidence |
|---|---|---|
| `NoError` | `err` | `err != nil` reaches `failExpectedActual` |
| `Nil` / `NotNil` | `v` | `!isNil(v)` / `isNil(v)` reaches the wrapper |
| `IsType` | `actual, expected` | `reflect.TypeOf(expected) != reflect.TypeOf(actual)` |
| `Equal` | `actual, expected` | nil/type prerequisites, type cases, comparisons and recursive calls |
| `failExpectedActual` | empty | diagnostic output followed by `t.FailNow()` |

The complete `Equal` check inventory includes its earlier `Nil`, `NotNil` and
`IsType` calls. `msg` is not a failure predicate merely because it is passed to
the diagnostic wrapper. These are implementation-dependent source facts; the
analysis does not assert that this custom package is correct or automatically
establish an expected argument port.

APIs:

```python
from experimental.source_failure_evidence import analyze, analyze_corpus

facts = analyze(list_of_Source_objects)
facts = analyze_corpus(corpus, candidate=None)
# With a candidate, replay program edits, strip probes, then reparse the source.
facts = analyze_corpus(corpus, candidate)
```

The result contains `functions`, `sinks`, `calls`, `conditions`, `checks` and
`unknowns`. A separate outcome-blind census/import locator is provided
in `scripts/census_source_failure_evidence.py`; it maps actual imported calls
to declarations using source paths and sealed Go module roots. That import
proof is separate from this prototype's same-package graph.

```text
.venv/bin/python scripts/census_source_failure_evidence.py --paired results/relation_search_20260930_finite_templates/paired_inputs_v3 --output results/source_failure_evidence_20260930/paired_v3_census_v1
```

The output directory must be new; previous snapshots are not overwritten.

The fixed cohort census completed with an immutable seal in the directory above.
It read the existing 17-case/50-member selection without model completions,
execution results or target labels. The selected inventory contains eight
candidate-specific unproved custom adapter call sites in four members (P5/P6),
covering 72 local-helper call instances. All eight now have source import,
declaration, actual/formal, failure sink, control-predicate and finite path
evidence. Deduplicating declarations gives only two APIs: `NoError` and `Equal`.
These repeated instances are not independent tasks or defects, and the existing
adapter inventory is not a full-source assertion truth set.

`NoError` contributes `err != nil`; `Equal` contributes 55 lexical conditions
across its supported reachable checks and retains four relevant unknowns. Neither
API is promoted to a proved assertion contract, and all expected ports remain
unknown. The census audits exact byte spans, declaration/source SHA and each
shortest path against canonical calls. No provider or subject call was made.

The separately saved `scripts/audit_source_failure_evidence.py` imports only
stdlib modules and independently verifies JSON, byte identity, SHA and path
transport. It does not recompute binding or failure semantics. Its v2 record is
`results/source_failure_evidence_20260930/evaluation/paired_v3_census_v1_audit_v2.json`,
bound to the auditor SHA. It verifies 84 sealed files, 53 input references,
15 code snapshots, 3,084 source extents and eight canonical failure paths.
Six additional corruption/callee/path/SHA tests passed separately. The original
census and first audit are unchanged.

Workspace verification before the standalone auditor was added:
`2790 passed, 30 subtests passed, 2 warnings` in
66.82 seconds; the warnings are pre-existing invalid escape literals. The log is
preserved at `results/source_failure_evidence_20260930/evaluation/workspace_pytest.log`.
The six standalone auditor tests passed afterward. This checks implementation and
source provenance, not semantic correctness or coverage of the 17 target gaps.

No result here demonstrates improved oracle correctness, defect detection,
combination recall, or issue resolution. Those require separate validation of
generated tests and patch outcomes.
