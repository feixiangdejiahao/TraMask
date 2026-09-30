# Local helper source evidence, 2026-09-30

This independent prototype computes local helper bindings and per-call argument
instances from the complete candidate-modified test. It makes no model request,
executes no subject code, and changes no sealed production evidence or oracle
interface. API: `experimental.local_helper_evidence.analyze(corpus, candidate)`.

The earlier `experimental/go_assertion_helper.py` handles same-package named Go
helpers with a restricted standard `testing.T` failure guard. The new prototype
reuses its Go parameter parser only. Its additional scope is Python local `def`,
Go local function literals, and TypeScript local arrow/function expressions.
Existing `Flow` assertion adapters and slicing are reused; no helper name or
parameter name determines an assertion role.

For each supported direct call, the result retains the local declaration span,
formal spans, call span, each actual argument's source span, and the helper's
assertions. The observed operand's slice identifies formal dependencies; those
formals are bound separately to this call's actual arguments. Thus two calls of
the same helper do not share an expected argument slot.

A candidate expected argument boundary additionally requires a supported
assertion adapter, a bare expected formal, and no other occurrence of that
formal in the complete helper body. The check includes nested closures. Imported
Go testify and TypeScript vitest/Jest adapters must not be shadowed or written
in any enclosing lexical scope. Intrinsic Python `assert` is supported;
unresolved Python assertion methods and unproved custom assertion packages
retain unknown ports. These are syntactic candidate boundaries, **not** a proof
of expected correctness, execution, value isolation, or safe editing.

Unsupported defaults, splats, keyword binding, arity, reassignment, conditional
declarations/calls, differing immediate lexical scopes, decorators, async defs,
and class members retain explicit unknown evidence. This restricted analysis
does not provide sound or complete full-language resolution. Conservative
same-spelling checks can deny a port even when a deeper analysis could prove it.

The tests include three-language positive examples, UTF-8 byte positions,
candidate edits, independent repeated calls, parameter reordering, unsupported
call shapes, shadowing, runtime-probe removal, parse errors, outer framework
receiver writes, closure capture, and a local class scope boundary. Validation:

```text
.venv/bin/python -m pytest -q tests/test_local_helper_evidence.py tests/test_go_assertion_helper.py
58 passed (33 new local-helper tests + 25 existing Go-helper tests)
```

The outcome-blind census reads all offered concrete members from the existing
paired cohort, never model responses, subject results, target labels, hidden
verifiers, or reference patches. It saves input/code SHA, source outputs, and a
seal. The earlier v1 snapshot is retained; the boundary fixes are in v2:

`results/relation_search_20260930_finite_templates/local_helper_evidence_census_v2/`

| Quantity | Result |
|---|---:|
| Existing paired cases / offered members | 17 / 50 |
| Members with a discovered local helper-name call | 11 |
| Local declarations / helper-name calls | 22 / 52 |
| Calls with supported source bindings | 43 |
| Instantiated supported assertion records | 75 |
| Exact old evidence calls with empty bindings now bound | 8 |
| Candidate expected argument ports in this cohort | 0 |

The eight recovered evidence calls are N02:4, P5:2, P6:2. This is a source-support
result, not target recall or a test-correctness result. N08 contributes three
resolved calls and nine calls outside the supported immediate scope.

In the actual P5/P6 source, `require` imports the repository-owned
`github.com/d5/tengo/v2/require`, **not** testify. The local `eval` declaration,
each call's three argument spans, `expr`/`params` dependencies, and the bare
formal occurrence in `require.Equal(t, expected, actual)` are computed. However,
the assertion adapter's role is not established from this custom package's
implementation, so the prototype does not expose its expected ports. Adding a
repository path exception would be fitting the case and is deliberately absent.
General source-backed custom adapter analysis or explicitly reviewed adapter
registration is a separate unresolved step.

No new expected value, combination test, detection improvement, or issue
resolution improvement is claimed by this module or census.
