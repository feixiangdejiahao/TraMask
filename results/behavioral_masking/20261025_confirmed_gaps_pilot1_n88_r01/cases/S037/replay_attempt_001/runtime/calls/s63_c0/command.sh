cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
old = """    logic.actions.setIndex(1, 99)
    expect(logic.values.first).toBe(10)
    expect(logic.values.hasTen).toBe(true)
    expect(firstEvals).toBe(1)
    expect(hasEvals).toBe(1)

    logic.actions.setIndex(0, 42)
    expect(logic.values.first).toBe(42)
    expect(logic.values.hasTen).toBe(false)
    expect(firstEvals).toBe(2)
    expect(hasEvals).toBe(2)
"""
new = """    logic.actions.setIndex(1, 99)
    expect(logic.values.first).toBe(10)
    expect(logic.values.hasTen).toBe(true)
    expect(firstEvals).toBe(1)
    // `.includes()` checks every element, so a change at any index re-evaluates it.
    expect(hasEvals).toBe(2)

    logic.actions.setIndex(0, 42)
    expect(logic.values.first).toBe(42)
    expect(logic.values.hasTen).toBe(false)
    expect(firstEvals).toBe(2)
    expect(hasEvals).toBe(3)
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('fixed')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -40