cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()

# Add markDirtyForChanges method after propagate
old = """  private propagate(meta: AtomicSelectorMeta, oldVal: any, newVal: any): void {
    if (Object.is(oldVal, newVal)) {
      return
    }
    const changes = diffPaths(oldVal, newVal, meta.name)
    for (const change of changes) {
      this.bumpPath(change)
    }
  }
"""
new = """  private propagate(meta: AtomicSelectorMeta, oldVal: any, newVal: any): void {
    if (Object.is(oldVal, newVal)) {
      return
    }
    const changes = diffPaths(oldVal, newVal, meta.name)
    for (const change of changes) {
      this.bumpPath(change)
    }
    this.markDirtyForChanges(changes, meta.name)
  }

  private markDirtyForChanges(changes: string[], sourceSelector?: string): void {
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
assert old in s
s=s.replace(old,new)

# In notify, after bumping changes, mark dirty causes
old = """    const changes = diffPaths(previousRoot, nextRoot, '')
    for (const change of changes) {
      this.bumpPath(change)
    }
  }
"""
new = """    const changes = diffPaths(previousRoot, nextRoot, '')
    for (const change of changes) {
      this.bumpPath(change)
    }
    this.markDirtyForChanges(changes)
  }
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('eager dirtyCause added')
PY
npx tsc --noEmit 2>&1 | head -20