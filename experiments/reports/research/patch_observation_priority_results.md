> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/patch_observation_priority_results.md) · [旧路径映射](../../../results/path_map.tsv)

# Patch observation priority: fixed-pool source study

**The new v1 priority rules did not improve witnessed-program exposure.** The strict rule produced no priorities and reproduced the shape baseline. The conservative may rule exposed fewer known witness programs under the same static budget. This study made no model requests or subject executions; the established main experiment remains **16/17**.

The unique source run, session `97260`, completed successfully on 2026-09-30 before evaluator targets were opened. It used the fixed 4,502 source candidates, 17 trials and 14 previously studied tasks, with 16 candidates per trial in each arm. The generation code was committed as `7615f4e` before post-hoc evaluation. The separate v2 toy prototype was not used.

## What was measured

`Program exposure@16` asks whether the first 16 ranks include at least one previously fixed witness's original input program. It does **not** ask whether a new model supplied correct assertions or whether a new test failed on the patch. The evaluator restores original assertions by removing recorded oracle edits, applies the original input edits to the sealed corpus, and matches exact modified owner bytes, the same base test, and added import bindings. This also finds identical programs represented by different edit windows. The reconstruction reuses the frozen mechanical source modifier; it is not an independent import parser or a new semantic oracle.

Two prefixes were fixed before ranking: `raw@16` over all 4,502 candidates, and `legacy eligible@16` over the common original singleton assertion interface. The latter contains 2,870 candidates. Unknown or ineligible candidates remain in the raw denominator. Neither prefix equals the current main CLI's prefix, which scans its actual `prepare_requests` eligibility before allocating request budget.

The main evaluation bank contains all currently supported witnesses in the existing v3 checkpoint, including inherited witnesses. Exact original witness material is available for **16/17 trials and 13/14 tasks**; N08's recorded successful program is absent from this particular source pool. Missing material counts as unexposed in the full denominator, and the available-material denominator is also reported.

| Metric | Shape | Strict | Conservative may |
|---|---:|---:|---:|
| Raw program exposure, all trials | 9/17 | 9/17 | 7/17 |
| Raw exposure, available material | 9/16 | 9/16 | 7/16 |
| Legacy eligible exposure, all trials | 7/17 | 7/17 | 5/17 |
| Legacy eligible exposure, available material | 7/16 | 7/16 | 5/16 |
| Raw task exposure, any trial succeeds | 7/14 | 7/14 | 6/14 |
| Legacy eligible task exposure, any trial succeeds | 5/14 | 5/14 | 4/14 |
| Fixed five historical oracle-revision cases, raw or eligible | 3/5 | 3/5 | 3/5 |

Task figures are descriptive. P1/P2/P3 share one task and P5/P6 share another, and each trial receives its own budget of 16. Thus “any trial” is not a single budget-16 experiment on each independent task. The JSON also reports every task's constituent trials and the stricter all-trials result.

## Per-trial ranks

Each cell is the best **raw / legacy eligible** rank of available v3 witness material. Strict ranks equal shape ranks throughout. A dash means the material is absent from that projection; N08 is absent from the full source pool.

| Trial | Shape | Conservative may |
|---|---:|---:|
| N01 | 2 / — | 2 / — |
| N02 | 3 / 2 | 20 / 19 |
| N03 | 53 / 47 | 53 / 47 |
| N04 | 48 / 43 | 48 / 43 |
| N05 | 170 / 129 | 111 / 106 |
| N06 | 135 / 96 | 86 / 75 |
| N07 | 5 / 5 | 4 / 4 |
| N08 | — / — | — / — |
| N09 | 391 / — | 394 / — |
| N10 | 4 / — | 1 / — |
| P1 | 11 / 9 | 14 / 12 |
| P2 | 87 / 81 | 87 / 81 |
| P3 | 2 / 2 | 2 / 2 |
| P4 | 59 / 56 | 59 / 56 |
| P5 | 15 / 12 | 20 / 17 |
| P6 | 4 / 3 | 2 / 2 |
| P7 | 3 / 3 | 2 / 2 |

There are no new exposed trials under may priority; N02 and P5 leave both prefixes. N05's canonical program improves its rank but still misses 16 by a large margin. N06 similarly improves without becoming exposed.

A separately retained, older historical bank gives raw **9/17 → 6/17** and legacy eligible **7/17 → 4/17**. It additionally loses N07 because that bank contains only the earlier witness material; the later supported v3 bank includes another valid N07 program that remains exposed. Both banks are saved separately, rather than choosing the more favorable one. Their fixed five oracle-revision cases remain **3/5** in all arms.

## Source coverage and cost

Strict finds **0/4,502** complete supported returned-parameter paths. May prioritizes **925/4,502** candidates. These are source facts, not correct expectations, execution coverage or discovered defects. The may rule raises the number of raw selected candidates with legacy editable assertions from 220 to 236 out of 272, while reducing known witness exposure; more editable material alone is insufficient.

| Arm | Sum of measured ranking analysis time |
|---|---:|
| Shape | 48.768 s |
| Strict | 4,548.164 s (75.80 min) |
| Conservative may | 4,543.901 s (75.73 min) |

These timings cover complete source-pool ranking, not analysis of only 16 selected candidates. They exclude the shared eligibility census and input/output hashing. The implementation computes both kinds of evidence separately in each mode, so strict timing is not a measurement of an optimized strict-only implementation. The Go tails dominate: P5 costs 1,990.317 / 1,988.149 seconds and P6 costs 1,985.493 / 1,982.504 seconds for strict / may. Known repeated AST scans are an implementation limitation; separate toy caching results cannot be substituted for these measured real-case costs.

The evidence supports two limited conclusions: the strict supported fragment is too narrow on this development pool, and Boolean changed-callee may reachability is too coarse to improve this selection budget. It does not establish an end-to-end regression: nonsemantic witnesses need not depend on oracle-request selection, and no model or native execution was repeated. In particular, neither the old main 16/17 result nor false-alarm/missed-defect rates are updated by these static counts.

## Reproduction and frozen evidence

[Source protocol](../../../results/program_relation_search/patch_observation_priority_20260930/census_v1/protocol.json), [summary](../../../results/program_relation_search/patch_observation_priority_20260930/census_v1/summary.json), [post-hoc review](../../../results/program_relation_search/patch_observation_priority_20260930/evaluation/posthoc_v1/review.json), [evaluation record](../../../results/program_relation_search/patch_observation_priority_20260930/evaluation/posthoc_v1/evaluation_record.json), and [independent rank audit](../../../results/program_relation_search/patch_observation_priority_20260930/evaluation/source_seal_audit_v2.json) retain all denominators, matching records, gains/losses, snapshots and hashes. The audit verifies 162 sealed files, 87 inputs and 40 generation code files, candidate identities, both rank prefixes, stable partitions, and exact cross-mode evidence identity for all 17 cases. All 17 patch strings also round-trip to their original UTF-8 bytes exactly.

Generation seal SHA256: `96b1528bd7ff73f5eb645f9e384b43030099a24c45a05c866fcf6dbae5860682`. Evaluation review SHA256: `e6ff5d7eb776bd1df47bae3fa35df9a2098cb60aa7a2533b438549825f3220d5`. The independent evaluator has nine synthetic qualification tests. Targets were read only after the generation seal, and no target IDs or ranks were sent back to the generation designer.

```bash
.venv/bin/python scripts/evaluate_patch_observation_priority.py \
  --input results/patch_observation_priority_20260930/census_v1 \
  --historical-matching results/relation_search_20260929_v3/evaluation/impact_rank_review_v1.json \
  --checkpoint results/relation_search_20260929_v3/evaluation/uniform_fresh_impact_v3/checkpoint_14.json \
  --output /tmp/patch-priority-posthoc-reproduction
```
