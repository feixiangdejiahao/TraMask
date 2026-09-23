# Pilot Handbook: Discriminating Combination Coverage for Coding-Agent Tests

**Purpose:** Give this document to Codex to implement and run a small pilot that tests whether coding-agent validation misses bugs because relevant behaviors are tested separately but not exercised together in a discriminating way.

**Scope:** This is a pilot for the abstraction and extraction pipeline, not a benchmark-scale effectiveness claim.

---

# 1. Research question

The pilot asks:

> When existing coding-agent tests already exercise several relevant behaviors separately, can we automatically recover those behavioral dimensions, identify high-value missing interactions, and synthesize a combined test that exposes a real defect?

The central observation is:

```text
test(A) + test(B) does not imply test(A with B)
```

The missing unit is not necessarily a line, function, or file. It can be an **interaction between behavior dimensions at one interface**.

Examples:

```text
modified shortcut × associated text
magic command × quoted path
clone × multiple closures sharing one captured cell
```

A second, harder case is:

```text
the combination is executed,
but the chosen input/oracle cannot distinguish whether the interaction semantics worked
```

The Valibot recursive-transformation case is included only as an exploratory extension of this second form.

---

# 2. What this pilot must NOT assume

Do not provide the worker with:

- the official hidden-test failure;
- the evaluator's manual root-cause explanation;
- the exact missing combination;
- a hand-written executable task specification;
- a hand-written expected assertion for the target bug;
- gold/reference patch details.

The worker may use only information available to a normal coding agent:

```text
issue description
candidate repository
candidate patch
repository developer tests
agent-authored tests
agent-visible test output
```

The evaluator may use hidden/verifier information only after generation to determine whether a generated test found the known defect.

This separation is mandatory.

---

# 3. Pilot cases

Use the following cases.

## Core missing-combination cases

### P1 — Textual: special/function key × event phase

Trial:

`https://deepswe.datacurve.ai/data/v1.1/trials/textual-kitty-key-phases__pier74V`

Manual evaluator hypothesis:

```text
factor A: key syntax family = function/special key
factor B: event phase = release/repeat
missing joint execution: function/special key carrying event phase
```

Do not give this hypothesis to the worker.

---

### P2 — Textual: modified shortcut × associated text

Trial:

`https://deepswe.datacurve.ai/data/v1.1/trials/textual-kitty-key-phases__Rm7PhRr`

Manual evaluator hypothesis:

```text
factor A: modified shortcut
factor B: associated text present
missing joint execution: modified shortcut with associated text
```

The existing tests already contain a useful oracle for the shortcut behavior. The pilot should test whether the extraction pipeline can discover that the relevant factors live in separate tests.

---

### P3 — Textual: shifted key × modifier combination

Trial:

`https://deepswe.datacurve.ai/data/v1.1/trials/textual-kitty-key-phases__yQrLFSk`

Manual evaluator hypothesis:

```text
factor A: shifted-key alias generation
factor B: modifier set includes shift
missing discriminating value combination
```

This case is useful because the existing test already checks the alias, but its modifier value does not expose the faulty interaction.

---

### P4 — IPython: magic interface × quoted path representation

Trial:

`https://deepswe.datacurve.ai/data/v1.1/trials/ipython-session-bundle-replay__7iCJDcb`

Manual evaluator hypothesis:

```text
factor A: entry interface = IPython magic
factor B: path representation = quoted
missing joint execution: quoted path through the magic parser
```

---

### P5 — Tengo: Go-call entry × compound callable result

Trial:

`https://deepswe.datacurve.ai/data/v1.1/trials/tengo-callable-instance-isolation__wnUmNKQ`

Manual evaluator hypothesis:

```text
factor A: invocation entry = Go Call
factor B: returned structure contains callable/closure objects
interaction may expose a VM-frame bug
```

This is intentionally harder than P1–P4.

---

### P6 — Tengo: clone isolation × shared captured state

Trial:

`https://deepswe.datacurve.ai/data/v1.1/trials/tengo-callable-instance-isolation__izhrgFe`

Manual evaluator hypothesis:

```text
factor A: cloned callable instance
factor B: two closures share one captured local
factor C: sequential update-then-read relation
```

This case tests whether the method can represent an interaction as an object relationship and call sequence rather than only scalar input parameters.

---

## Exploratory discriminating-value case

### P7 — Valibot: recursive schema × transformation

Trial:

`https://deepswe.datacurve.ai/data/v1.1/trials/valibot-recursive-schema-composition__C43jvBU`

Manual evaluator hypothesis:

```text
recursive + pipe is already exercised
but the chosen transformation is observationally close to identity
therefore the test is not discriminating for transformation loss
```