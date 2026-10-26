cd /app && python3 - <<'PY'
p='src/core/selectors.ts'
s=open(p).read()
old = """    const selectorInputs = typeof input === 'function' ? input(logic) : input

    // small cache so the order would not count
    const builtSelectors: Record<string, Selector> = {}
"""
new = """    const selectorInputs = typeof input === 'function' ? input(logic) : input

    if (getContext().options.atomicSelectors) {
      atomicSelectorsBuilder(logic, selectorInputs)
      return
    }

    // small cache so the order would not count
    const builtSelectors: Record<string, Selector> = {}
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('branch inserted')
PY