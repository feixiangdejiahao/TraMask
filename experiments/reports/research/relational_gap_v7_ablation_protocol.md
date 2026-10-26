> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_v7_ablation_protocol.md) · [旧路径映射](../../../results/path_map.tsv)

# Whole-source-observation ablation

This offline ablation starts from every source_q candidate actually offered in batch6. It makes no provider request, reads no evaluator label, and does not choose candidates from their outcomes. It restores only atomic-neutralized source observations, replays any input edit absorbed by their neutralization, and retains input/action/exception/normal-result guards. Unsupported restoration remains an explicit unknown. Byte-identical restored candidates share one new wholeq ID with every original ID recorded.

Each trial has a new preparation snapshot with new candidate IDs, source-parent provenance, copied immutable corpus/selection, and SHA manifests for the original preparation/accepted list. Consequently the existing evaluator can still enforce exact equality between each new static source candidate and its executed edits. Restoring an assertion does not establish that its expectation remains valid; all semantic and runtime verdicts require independent review.

The fixed budget is all offered source hypotheses, at most128 per trial, without the model-request byte cap. Model-revised candidates are excluded as a lane, without outcome inspection. Preparation uses four local workers. Execution uses two offline Docker slots, separate complete-source controls, and the unchanged240-second timeout per phase. The execution gate opens only when the complete batch6 evaluation artifact exists. There are no retries or target-specific rescues.

```bash
.venv/bin/python scripts/run_relational_gap_ablation_batch.py \
  --source-batch-root results/relational_gap_20260928/batch6 \
  --source-emitted-root results/relational_gap_20260928/batch6_emitted \
  --source-freeze results/relational_gap_20260928/batch6_pipeline/frozen_driver.json \
  --prefix results/relational_gap_20260928/batch7 \
  --execution-gate results/relational_gap_20260928/batch6_evaluation.json
```

This is an additional experiment with additional execution cost, not an equal-cost improvement over batch6. The frozen batch6 inputs, driver and results remain unchanged.

The initial gate-only scheduler was subsequently stopped after all17 preparations/emissions and **zero subject executions**. The interruption manifest records its PID, signal and zero-execution check. A separately frozen `resume_relational_gap_ablation.py` uses the already emitted files: one worker starts immediately in the free Docker slot while batch6 finishes its last case; the second joins the same fixed registry queue only after `batch6_pipeline/runs.json` exists. Thus both experiments together still use at most two containers. This is solely a resource-scheduling change: no preparation, emission or test is repeated, and no execution code, candidate or timeout changes. Final execution provenance and run index are under `batch7_resumed_pipeline/`.
