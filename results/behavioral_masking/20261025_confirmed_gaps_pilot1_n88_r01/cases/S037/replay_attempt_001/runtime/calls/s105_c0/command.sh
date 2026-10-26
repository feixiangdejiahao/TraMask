cd /app && git add src/core/atomic-selectors.ts src/core/selectors.ts src/core/reducers.ts src/kea/build.ts src/kea/context.ts src/kea/kea.ts src/kea/store.ts src/types.ts test/jest/atomic-selectors.js && git commit -m "feat: add atomic signal selector engine

Introduce an opt-in fine-grained reactivity engine for Kea selectors,
enabled via resetContext({ atomicSelectors: true }) and disabled by default.

- Track selector dependencies at exact leaf level (e.g. user.name) so
  unrelated leaf changes do not re-evaluate selectors.
- Support collections: Map key access (data.map:a), Set membership
  (data.set:a), and Array index reads (list.0) plus .includes().
- Propagate updates through multi-level selector chains and evaluate a
  dependent selector at most once per action.
- Detect circular selector dependencies during build/mount and throw
  [KEA] Circular dependency detected.
- Expose logic.selectorHealth() with dependencies, dependents,
  evaluations, dirtyCause and topologicalOrder when enabled; keep it
  undefined when disabled.
- Preserve baseline lifecycle/plugin ordering and React re-render
  behaviour (unrelated state updates do not re-render)." && git log --oneline -3