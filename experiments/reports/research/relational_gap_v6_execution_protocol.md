> 阅读副本。本页已更新本地链接。正文保留原文。[原记录](../../../research/relational_gap_v6_execution_protocol.md) · [旧路径映射](../../../results/path_map.tsv)

# Prospective v6 execution protocol

The v5 model and execution budgets are unchanged: at most two requests per trial,
64 offered source candidates per request, every offered source-q hypothesis
retained, and at most 64 distinct model-q revisions. Execution remains bounded
by 192 hypotheses per trial and two concurrent offline Docker containers.

V6 changes source materialization only. Historical Go dependency closure uses
package names proved by source files from each trial's installed image. The
uniform offline extraction script reads imports in the prepared historical
sources, resolves them with `go list -e -find -json` with the proxy disabled, and
records an actual Go source file, its hash, and its image. No package basename
guessing or target labels are used. The extracted inventory is local experiment
data; the pipeline freezes its hash and copies it into the run ledger.

The same inventory is supplied to original controls and generated tests.
Unambiguous historical helper declarations and import aliases can be restored.
Proved implicit import names are made explicit before the existing unused-import
materializer runs; this permits blank imports to retain initialization when a
pruned historical test no longer uses the package. Import changes have separate
source-span and package-source provenance. Ambiguous bindings remain unresolved.
Control support files therefore have recorded materialization changes; byte
identity with all original support files is not claimed.

V5 artifacts, requests, raw replies, controls, and execution reports remain
unchanged. No per-case selection or rescue execution is performed. V6 launches
only after its generation and execution dependencies are frozen, then applies
the same policy to all 17 trials.
