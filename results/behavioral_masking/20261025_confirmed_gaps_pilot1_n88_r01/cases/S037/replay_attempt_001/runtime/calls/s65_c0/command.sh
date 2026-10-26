cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()
old = """      for (const dep of meta.dependencies) {
        const root = firstSegment(dep)
        if (this.selectors.has(root)) {
          if (!dependents.has(root)) {
            dependents.set(root, new Set())
          }
          dependents.get(root)!.add(meta.name)
        }
      }
"""
new = """      for (const dep of meta.dependencies) {
        const root = firstSegment(dep)
        if (root !== meta.name && this.selectors.has(root)) {
          if (!dependents.has(root)) {
            dependents.set(root, new Set())
          }
          dependents.get(root)!.add(meta.name)
        }
      }
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('fixed')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -30