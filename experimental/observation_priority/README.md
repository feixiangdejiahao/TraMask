# Optional observation-based ordering

This module only reorders an existing neighbor list. It does not reject candidates, change the 2,000-triple/128-output budgets, or replace semantic admission.

`rank_neighbors(A, neighbors, capsules=by_test_id, phase="target" | "edit", cache=per_generation_cache)` uses records already built by the analogy driver. It preserves the existing order for ties and returns every supplied record exactly once.

- For A→C, compare the first calls reached backwards from **actual** expressions through value edges, retaining field projections. Resolved equal identities rank before spelling-only matches; unknown or different observations remain available. A shared remote factory is insufficient if the nearest observations or fields differ.
- For A→B, compare call occurrences after erasing argument literal values, and compare actual-observation occurrences. Added/deleted/changed calls are ranked by their connection to the corresponding source observation: value edge path, may-effect path, then a shared locally bound receiver/argument with unknown effects. Unrelated changes remain last. Expected constants never form observation keys.

The existing graph is approximate. Missing receiver resolution remains spelling-only; aliasing, effects and embedded string-program semantics are not inferred here. Call-shape multiset differencing can confuse repeated indistinguishable occurrences. These are ordering heuristics, not semantic or independence proofs.

`experimental.observation_priority.generate.generate(corpus, Budget())` is an independent wrapper around the v5 unified views. It supplies one per-run feature cache and changes only the two neighbor orders. Its gate policy is exactly the v5 policy; ordering evidence is not treated as additional semantic authorization.

The shared driver supplies this optional callback:

```python
# `neighbors` already has the existing deterministic skeleton-distance order.
target_order = order_neighbors(A, neighbors, capsules=capsules, phase="target")
edit_order = order_neighbors(A, neighbors, capsules=capsules, phase="edit")
edit_neighbors = _diverse_neighbors(edit_order)[:budget.edit_neighbors]
for C in target_order[:budget.target_neighbors]:
    for B in edit_neighbors:
        # Existing triple deduplication, focus round-robin and budgets.
        ...
```

The callback returns all neighbors; the original C truncation and B shape-diversity/truncation still follow it. Thus unknown relationships remain eligible, but a finite neighbor or attempt budget can still prevent their execution. Original focus round-robin scheduling and the 2,000-triple/128-output budgets are unchanged. The default driver path without this callback preserves the baseline order.

Synthetic end-to-end checks cover first-focus priority, retention of unknown/unrelated queues when the budget allows them, row instantiation, deterministic repeated generation, JSON and emitter compatibility. They use no pilot or execution results.
