cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()

# Change markDirtyForChanges signature and logic
old = """  private markDirtyForChanges(changes: string[], sourceSelector?: string): void {
    for (const meta of this.selectors.values()) {
      if (sourceSelector && meta.name === sourceSelector) {
        continue
      }
      for (const dep of meta.dependencies) {
        const matching = changes.find((change) => dep === change || change.startsWith(`${dep}.`))
        if (matching) {
          const kind = meta.depKinds.get(dep)
          meta.dirtyCause = kind === 'selector' ? `selector:${dep}` : matching
          break
        }
      }
    }
  }
"""
new = """  private markDirtyForChanges(changes: string[], sourceMeta?: AtomicSelectorMeta): void {
    for (const meta of this.selectors.values()) {
      if (sourceMeta && meta.name === sourceMeta.name) {
        continue
      }
      for (const dep of meta.dependencies) {
        const matching = changes.find((change) => dep === change || change.startsWith(`${dep}.`))
        if (matching) {
          if (sourceMeta) {
            // A derived selector invalidates its dependents as `selector:<name>`.
            // Reducer selectors just mirror state, so keep the raw leaf path.
            meta.dirtyCause = sourceMeta.isReducer ? matching : `selector:${sourceMeta.name}`
          } else {
            meta.dirtyCause = matching
          }
          break
        }
      }
    }
  }
"""
assert old in s
s=s.replace(old,new)

# Update propagate call
s=s.replace("    this.markDirtyForChanges(changes, meta.name)\n  }\n", "    this.markDirtyForChanges(changes, meta)\n  }\n")

# Update runSelector and runReducerSelector to keep eager dirtyCause if present
old = """      meta.cached = rawResult
      meta.hasCached = true
      meta.evaluations += 1
      meta.dirtyCause = finalCause
      meta.lastArgResults = argResults.map(unwrap)
"""
new = """      meta.cached = rawResult
      meta.hasCached = true
      meta.evaluations += 1
      meta.dirtyCause = meta.dirtyCause !== null ? meta.dirtyCause : finalCause
      meta.lastArgResults = argResults.map(unwrap)
"""
assert old in s
s=s.replace(old,new)

old = """      meta.cached = rawResult
      meta.hasCached = true
      meta.evaluations += 1
      meta.dirtyCause = cause
      meta.lastPropsVersion = this.propsVersion
"""
new = """      meta.cached = rawResult
      meta.hasCached = true
      meta.evaluations += 1
      meta.dirtyCause = meta.dirtyCause !== null ? meta.dirtyCause : cause
      meta.lastPropsVersion = this.propsVersion
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('dirtyCause refined')
PY
npx tsc --noEmit 2>&1 | head -20