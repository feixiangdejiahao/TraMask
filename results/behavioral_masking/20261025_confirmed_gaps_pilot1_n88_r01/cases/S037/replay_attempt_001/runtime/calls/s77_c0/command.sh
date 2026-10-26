cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
old = """    built.mount()
    // `useSelector` calls selectors with only state
    expect(built.selectors.id(built.selector(getContext().store.getState()))).toBe(7)
    expect(built.selectors.id()).toBe(7)
"""
new = """    built.mount()
    // `useSelector` calls selectors with only state
    expect(built.selectors.id(undefined)).toBe(7)
    expect(built.selectors.id()).toBe(7)
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('fixed test')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js -t "default props" 2>&1 | tail -20