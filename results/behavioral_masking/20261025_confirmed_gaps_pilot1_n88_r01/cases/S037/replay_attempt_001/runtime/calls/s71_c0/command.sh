cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
# Add a test for dirtyCause before re-evaluation after the existing dirtyCause test
marker = "  test('react components only re-render for accessed changes', () => {"
addition = '''  test('dirtyCause is set immediately after an action', () => {
    const logic = kea([
      actions({ setName: (name) => ({ name }) }),
      reducers({
        user: [{ name: 'a', age: 1 }, { setName: (state, { name }) => ({ ...state, name }) }],
      }),
      selectors({
        userName: [(s) => [s.user], (user) => user.name],
      }),
    ])
    logic.mount()
    expect(logic.values.userName).toBe('a')
    logic.actions.setName('b')
    // Without re-evaluating, the health should already know what invalidated it.
    expect(logic.selectorHealth().selectors.userName.dirtyCause).toBe('user.name')
    expect(logic.values.userName).toBe('b')
  })

'''
assert marker in s
s=s.replace(marker, addition + marker)
open(p,'w').write(s)
print('test added')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -45