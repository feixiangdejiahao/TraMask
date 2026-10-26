> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_go_materialization_audit.md) · [旧路径映射](../../../results/path_map.tsv)

# Go materialization: independent execution audit

Batch2 Go failures came from several separate causes. They are not evidence of the target combination gaps.

| Evidence | Cause | Generic action | Validation |
|---|---|---|---|
| P5 group000, compiler_test.go | Replacing len(input) by 0 removes the only read of a previously evaluated local | Add a blank read after an unread local declaration in a generated function | Both original controls now compile and pass |
| N06 group000/001 | Replacing base with ours or target with base removes a local use; model also replaces nil by 0 | Preserve unread bindings; leave wrong typed expected expressions for independent rejection | Seven blank reads inserted in group000; no oracle or input repair performed |
| P6 group004 | An unrelated test in an injected historical donor file uses a removed Bytecode API and an absent bytes import | Retain selected test entries and transitive referenced test entries; remove other historical test entries, preserving helper declarations | Package now compiles: 6 original controls pass, 3 historical controls fail unchanged |
| N07 all groups | Namespace recovery rewrites blank identifier; some historical files duplicate test declarations | Fixed by parent in source recovery, not by evaluator | Batch2 remains invalid; no retrospective target credit |
| P6 group000; P5 group002 | A generated panic or infinite loop prevents later Go tests/controls from running | Separate future execution-isolation decision | Current runtime policy unchanged; missing controls remain unverified |

The v3 materializer uses Go parser binding objects, not identifier spelling, to recognize variable reads. It handles ordinary statement-list short declarations and var declarations, nested scopes, captured reads, multi-bindings, and struct field keys. It inserts `_ = local` without repeating the initializer, changing the value, or modifying source control bodies. Unsupported initializer and range scopes are recorded rather than rewritten at an invalid scope.

Historical test-entry pruning computes function-reference closure across injected files within the same package. Selected originals, control functions, generated tests, normal helper declarations, and referenced test entries remain. Import package names are explicit aliases or obtained from locally available Go package declarations; unavailable package names are not guessed. Newly unused known imports become blank imports, preserving package initialization.

A separate audit confirmed exact control-function text identity for 2 P5 controls, 11 N06 controls, and 9 P6 controls. The P6 failures after the compile repair are genuine original-control failures: two int64/int expectations and one invalid embedded map literal. They are not repaired, omitted from the recorded outcome, or counted as target detections.

Artifacts: `results/relational_gap_20260928/v3_go_materialization_audit/`; the old batch2 files are unchanged. v3 emission writes `materialization.json` with edits and before/after source hashes, then hashes the actual final mounted files. The independent evaluator freezes this materialization record as evidence.

Implementation: `scripts/go_materialization.py`, `scripts/go_source_materializer/main.go`; integrated only in `scripts/execute_relational_gap_v3.py`. Tests in `tests/test_go_materialization.py` compile and run independent toy packages, including preserved initialization, shadowing, cross-file dependency closure, and import initialization.
