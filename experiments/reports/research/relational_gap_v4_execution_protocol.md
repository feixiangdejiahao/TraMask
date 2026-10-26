> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_v4_execution_protocol.md) · [旧路径映射](../../../results/path_map.tsv)

# v4 execution protocol

Each admitted source-file group uses one fresh offline Docker container with the exact candidate patch. The model budget and candidate selection remain unchanged.

1. Install an unedited source snapshot containing the same original-test controls. Run only control names in a separate process and save its report, return code, timeout, elapsed time and source hashes.
2. Restore the candidate's test-file state, install the generated snapshot, and run only generated-test names in another process. Save a separate report with the same context fields.

Each phase receives 240 seconds. The container shares its compilation cache across phases; global limits remain four provider calls and two containers. A later generated compile error, panic or timeout cannot erase a completed control report. Candidates remain grouped, so a compile error or panic can still prevent observing sibling candidates. There is no per-candidate rerun or outcome-driven rescue.

Snapshots are staged under hashed `.snapshot` filenames. Keeping original test suffixes in a staging directory allowed Vitest to discover duplicate staged tests; the initial integration failure is retained under `v4_smoke_runs/N10`, and the corrected run under `v4_smoke2_runs/N10`.

Control and generated sources are separate snapshots. The evaluator records their phase contexts rather than claiming byte-identical supporting files. Historical dependency recovery and import materialization, when applied, are recorded for both phases. Whole source-control function bodies receive no input or oracle edits.

The Go materializer resolves module-local import package names from the repository's `go.mod` and actual package clauses. Unused imports retain initialization through blank imports. No task names, target labels or expected failures guide these changes.

Independent checks include actual Go compilation where both original controls pass but generated compilation fails; an enforced later timeout preserving control evidence; TypeScript execution with eight passing controls and 25 generated outcomes; and frozen phase-context verification in the evaluator. Integration results establish harness behavior, not additional experiment successes.
