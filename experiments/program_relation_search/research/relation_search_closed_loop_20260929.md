# Executed relation-search loop, 2026-09-29

The Python prototype now executes feedback between search rounds. This document
describes implementation and observed behavior, not a claim of research novelty
or improved issue-resolution rate.

## Flow

1. `prepare` builds a source-only candidate pool with the existing constructors.
   It retains the entire pool, selects a bounded batch by seed/operator rotation,
   and freezes the input hashes and actual algorithm files. No evaluation labels
   participate in selection. Input edits remain separate from instrumentation so
   an optional oracle stage can still inspect the original program proposal.
2. `emit` attaches pure-read probes and emits three separate process snapshots:
   original source controls, instrumented source profiles with unchanged inputs,
   and generated candidates. Helpers are added after harness inference.
3. `run` executes those phases in that order in the offline candidate repository.
   JUnit or equivalent reports record execution independently of probe traces.
   A completed stage has a receipt covering its artifacts with SHA-256 hashes.
4. `feedback` registers actual source-profile events before generated events,
   restores the previous Frontier, and saves the updated state. A reported pass
   or failure without a trace is remembered as executed but contributes no shape.
   Materialization failures are remembered as attempted, not executed. These
   distinctions prevent silent reruns and invented coverage.
5. The next profile-guided round adds compatible original-source edits only to
   measured retained parents whose original controls and seed profiles passed.
   It retains all earlier candidates in the pool. Instrumentation and semantic
   expected-value edits never become input-combination edits. New combinations
   must execute and receive their own observations and semantic assessment.

`retained` means one of at most two representatives of a measured shape. It is
not identical to strict novelty; `new_profiles` records strict novelty. State
from a failing original control can be logged for diagnosis but cannot provide
an expansion parent. Source profiles with no usable measurement cannot justify
profile-guided expansion. Properties or unsafe getters remain unknown.

The explicitly labelled `rotation` control uses the same constructors, probes,
controls, seed profiles, and input budget, but may extend all actually executed
parents with valid source controls, without requiring shape-based retention.
It does not forge measured feedback for unsupported probes.

## N03 real execution control

Inputs: the unchanged complete prepared corpus at
`results/relational_gap_20260928/batch7/N03/`. The same bounded constructors are
used for both arms; no case-specific candidate or target assertion was selected.
Both arms used two rounds, limit 8, pool 64, group size 8, and one worker.

| Recorded quantity | Profile arm | Rotation arm |
|---|---:|---:|
| Generated test executions | 10 | 10 |
| Instrumented source-profile executions | 10 | 10 |
| Original-control executions | 6 | 6 |
| Total test executions | 26 | 26 |
| Execution wall time, seconds | 35.587 | 35.508 |
| Second-round new measured shapes | 0 | 0 |

Both arms constructed and executed the same candidate IDs. The first round
produced four valid-source parents; the second round constructed and executed
two combinations from those real parents. Failed old source controls were
retained in the evidence and excluded from expansion. Test execution wall time
includes the Docker execution stages, not candidate construction or model time.

This is a successful integration control. It shows **no measured search benefit**
for profile selection on this small N03 pool. The raw generated failures are not
all automatically classified as correct bug detections.

Artifacts:

- `results/relation_search_20260929/closed_loop/N03_profile_v1/`
- `results/relation_search_20260929/closed_loop/N03_rotation_v1/`
- `results/relation_search_20260929/closed_loop/N03_comparison_v1.json`

Each round contains `prepared`, `emitted`, `executed`, and `feedback.json`.
Unlike the older standalone N03 proof, source profiles here really execute in
their own preceding process. The two saved snapshots differ only in `oracle.py`,
which neither arm invoked. The comparison records that difference explicitly.
Subsequent no-model driver snapshots exclude that unused module.

## Reproduction and batch interface

The following runs a new no-model campaign over every prepared case directory
in the supplied source root. It does not claim semantic oracle completion:

```sh
.venv/bin/python scripts/run_relation_search.py batch --source results/relational_gap_20260928/batch7 --output results/relation_search_20260929/unified_profile --strategy profile --rounds 2 --limit 128 --pool 512 --include-baseline --workers 2 --group-size 16 --timeout 180
```

Use `loop` with a single case source directory for one case; use `--strategy
rotation` and a different output directory for the control. Each strategy
instruments and executes seed profiles. Compare the recorded total executions,
including controls and seeds, rather than only the candidate limit.

The individual `prepare`, `emit`, `run`, and `feedback` commands remain
available. A coordinator may insert a source-only cached semantic assertion
stage between prepare and emit. The emitter instruments the final candidate
list, and feedback follows `source_prepare` to recover original input identity.
The semantic stage must preserve program-candidate selection and provenance.

Repeating an unchanged command verifies and reuses completed stages. Changing
the source, configuration, or algorithm requires a new output directory.
Interrupted groups without a completed Docker result are preserved and use a
new attempt directory; completed results are normalized without rerunning tests.
`source_pool.json`, attempted IDs, executed IDs, Frontier state, reports, and
traces remain explicit checkpoint artifacts.

## Scope and limitations

- Python pure-read probes are implemented. Go and TypeScript candidates can be
  generated and executed, but no dynamic profile is fabricated for them. Their
  second profile-guided round can enumerate remaining original candidates; it
  cannot claim measured-profile-driven extension without actual events.
- The resource representation constructor now changes a producer and **all
  supported percent-interpolation consumers of the same lexical binding**
  together. Rebinding starts a different resource. Other string encodings and
  nested closures remain outside that bounded constructor; this is not a proof
  that every possible representation route is preserved.
- Source controls and generated tests use separate processes in one offline
  container, with test-file snapshots restored between phases. The adapter does
  not promise complete filesystem rollback of arbitrary subject-side effects.
- Passing controls and shape novelty do not establish oracle correctness.
  Independent contract review remains separate from search feedback.
