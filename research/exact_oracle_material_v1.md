# Exact oracle material census, version 1

This offline study is fixed before its first full-pool census. It does not change
the running primary experiment or call a provider. It reads candidate programs,
source frontends, frozen input requests and existing source-only ranks, never
provider answers, reference implementations or evaluation labels.

The question is how many semantic budget slots are spent on exactly repeated
material. It does not claim that equal text implies equal behavior under all test
framework reflection, or that different inputs have equivalent semantics.

## Two identities

`program_key` requires the same case, corpus/frontend, base test, original owner,
and byte-identical complete owner after validated `_program_edits`. This weak
identity is for accounting only. Different history owners and different base
tests are never merged, even if their text is identical.

`material_key` additionally requires exact, order-preserving equality of:

1. Canonical edits, including source spans, before/after text and roles. Different
   edit decompositions can change analysis seeds and editable assertion holes.
2. Added imports, including donor/source origins and aliases.
3. Complete original assertions, their positions, observed expressions and the
   existing expected-slot eligibility result.
4. Source control test IDs and extra source contexts.
5. Runtime probe/control/setup information, instrumentation status and execution
   lane. This is deliberately conservative: changed log metadata need not change
   business behavior, but this study does not discard it to improve savings.
6. Original impact obligations when supplied to the oracle renderer.
7. Every unrecognized candidate field. Only an explicit reviewed list of
   scheduling/derivation/admission metadata is ignored.

Generated candidate IDs and derivation families do not affect these source
consumers. Actual occurrences of IDs in source strings are never normalized.
Complete source and frontend identities protect inherited fixtures, declarations
and module resolution. Unmaterializable inputs get unique identities and remain
in the order; they are not silently merged.

The reviewed consumer boundary is `oracle.prepare_requests`,
`singleton_oracle_slots`, `oracle_evidence.build_evidence`, `emitter.emit` and
`instrument._program_edits`. This is dependency-mode oracle material identity,
not a claim that all admission or emitted registration/probe logs are identical.

## Measurements

On the fixed 4,502-candidate pool, use the frozen impact policy and its full
eligible order, compute both identities for all candidates, then compare the
original first 16 with the first 16 distinct material classes. Retain the full
order; do not rerank or retune the policy. Report how many later candidates enter
and the number of ranks scanned. This is a local scheduling counterfactual,
not observed test detection or accuracy.

For each completed main campaign round 0 semantic batch, inspect its actual
singleton input requests. Separately compare exact system/prompt/settings wire
hashes and complete local assertion/analysis material (excluding only its local
candidate ID). Report the actual number of independent materials. Model replies
and decisions are outside the input reader. Completion is detected from the
existence of `semantic_result.json`, without reading its contents.

For every component, report how many weak program classes it splits, additional
classes if considered alone, and how many conservative classes would disappear
if that one component were omitted. These counts can overlap. No looser
identity is used for selection. The analysis may find no useful savings.

## Sealed result and final audit

The completed snapshot is
`results/relation_search_20260929_v3/exact_oracle_material_v1/census/`.
It started at `2026-09-29T13:38:04Z` and finished at
`2026-09-29T13:40:24Z`, with all 17 cases present. The result is negative:

| Input set | Candidates or requests | Program classes | Conservative material classes |
| --- | ---: | ---: | ---: |
| Fixed full candidate pool | 4,502 | 4,435 | 4,502 |
| Eligible pool | 2,870 | — | 2,870 |
| First 16 eligible per case | 272 | 271 | 272 |
| Main round 0 actual singleton requests | 271 | 271 | 271 |

Keeping the first representative of each conservative material class introduces
**zero later candidates** into either the pool's 272-slot comparison or the
main round's 271-slot comparison. All 271 actual requests also have distinct
exact wire, local oracle-context and combined safe keys. P5 supplied 15 actual
requests; the other 16 cases supplied 16 each. This input census does not infer
why a request was omitted or whether any model response was correct.

The 67 redundant slots under the weaker program identity disappear under the
material identity. Different edit decompositions split 59 program classes,
source controls split 22, runtime context splits 8, and imports split 2; these
counts overlap. Omitting only edits would release 37 material classes and
omitting only runtime context would release 8. Neither relaxed rule was used.
Thus, this prototype provides no evidence for reducing the current model
budget through exact input deduplication, nor for improving target coverage.

The final local audit checked all 10 recorded code hashes against both their
saved snapshots and the working tree, all declared corpus/frontend/pool/queue
input hashes, and all 271 actual request hashes. It independently recomputed
the 34 pool/request summaries from their records; all matched. The 16 focused
tests passed. The audit receipt is `census/final_audit.json`.

The census is complete and can be retained as an offline negative result. It
is not connected to production selection, does not inspect round 1 requests,
and performs no semantic-equivalence proof or new repository execution. The
manifest snapshots the 10 listed direct consumers, not the entire transitive
Python environment; reproducing it still requires the existing project
environment and the hashed source artifacts.

No new finite-template synthesis prototype is included in this result. The
existing `experimental/finite_inputs.py` and
`experimental/semantic_transport/expected_templates.py` predate this experiment
(both last changed on 2026-09-24); they provide bounded literal inputs and
source-owned expected-expression holes, respectively. They are not evidence
that a newly proposed finite oracle-template algorithm was implemented or
evaluated during this run.
