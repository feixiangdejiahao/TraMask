> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_v5_execution_protocol.md) · [旧路径映射](../../../results/path_map.tsv)

# v5: retain source observations as executable hypotheses

This revision changes the model from a gate into an optional oracle reviser. For each case, the two frozen requests still offer at most 64 program-produced candidates each, under the existing 80 KB request limit. Every exact offered candidate is emitted in the `source_q` lane with its existing source observation. A model response cannot remove it. Provider and decoder failures are preserved and do not prevent this lane from running.

Model-validated expected-value edits produce separate `llm_q` hypotheses. An identical edit set shares the source execution; a different edit set gets a deterministic separate ID and an explicit `static_parent_id`. Both lanes retain `oracle.applicability=unknown_hypothesis_requires_independent_evaluation`. Model judgments are stored separately and never count as independent oracle proof.

The model budget remains at most 2 calls and 128 offered candidates per case. The **execution budget increases** to at most 128 source hypotheses plus 64 model revisions, or 192 in total. Results cannot be described as an improvement under equal overall cost. No case-specific selection or outcome-based retry occurs.

Groups are separated by `(execution_lane, source_file)` and source groups execute first. Invalid revised expected values therefore cannot prevent a source group from compiling. Within each group, v4's original-control process runs before the generated-test process in a fresh offline container. Compilation errors, missing reports, failed controls and timeouts remain non-detections. An invalid source candidate can still prevent its same-file peers from executing; this protocol does not claim candidate-level isolation.

Generation and model inputs do not include the independent census, probes, target labels, reference implementation or evaluation outcomes. Evaluation reports source-parent retrieval, target scenario, oracle correctness, whole-control pass and matching target failure separately, as well as execution lane. Unknown failures are hypotheses requiring review.

Entry point:

```bash
.venv/bin/python scripts/run_relational_gap_batch_v5.py \
  --batch-root results/relational_gap_20260928/batch5 \
  --prefix results/relational_gap_20260928/batch5 \
  --workers 4 --preparation-timeout 1200
```

The new files preserve v4's code and result directories. Driver hashes and source snapshots are frozen before dispatch; maximum concurrency remains four provider calls and two Docker containers.
