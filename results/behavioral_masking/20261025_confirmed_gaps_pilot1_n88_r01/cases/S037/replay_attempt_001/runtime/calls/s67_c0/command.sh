cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()
# Add maximalPaths helper after firstSegment
old = """function firstSegment(path: string): string {
  const index = path.indexOf('.')
  return index === -1 ? path : path.slice(0, index)
}
"""
new = """function firstSegment(path: string): string {
  const index = path.indexOf('.')
  return index === -1 ? path : path.slice(0, index)
}

/** Remove paths that are ancestors of other recorded paths (e.g. keep `user.name`, drop `user`). */
function maximalPaths(paths: Iterable<string>): string[] {
  const list = [...paths]
  return list.filter((path) => {
    const prefix = `${path}.`
    return !list.some((other) => other !== path && other.startsWith(prefix))
  })
}
"""
assert old in s
s=s.replace(old,new)

# Update commitDeps to refine stateDeps and pendingDeps
old = """    const dependencies = new Set<string>()
    const depKinds = new Map<string, DepKind>()
    for (const path of session.stateDeps) {
      dependencies.add(path)
      depKinds.set(path, 'state')
    }
    for (const entry of session.pendingDeps.values()) {
      if (entry.paths.size === 0) {
        dependencies.add(entry.selector)
        depKinds.set(entry.selector, 'selector')
      } else {
        for (const path of entry.paths) {
          dependencies.add(path)
          depKinds.set(path, 'state')
        }
      }
    }
"""
new = """    const dependencies = new Set<string>()
    const depKinds = new Map<string, DepKind>()
    for (const path of maximalPaths(session.stateDeps)) {
      dependencies.add(path)
      depKinds.set(path, 'state')
    }
    for (const entry of session.pendingDeps.values()) {
      if (entry.paths.size === 0) {
        dependencies.add(entry.selector)
        depKinds.set(entry.selector, 'selector')
      } else {
        for (const path of maximalPaths(entry.paths)) {
          dependencies.add(path)
          depKinds.set(path, 'state')
        }
      }
    }
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('refinement added')
PY
npx tsc --noEmit 2>&1 | head -20