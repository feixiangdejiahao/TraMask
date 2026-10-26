cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
# Add dirtyCause assertions to derived object test
old = """    // user.age changes: userInfo re-evaluates, but nameOnly should not
    logic.actions.setAge(2)
    expect(logic.values.nameOnly).toBe('a')
    expect(userInfoEvals).toBe(2)
    expect(nameEvals).toBe(1)

    // user.name changes: both re-evaluate
    logic.actions.setName('b')
    expect(logic.values.nameOnly).toBe('b')
    expect(userInfoEvals).toBe(3)
    expect(nameEvals).toBe(2)
"""
new = """    // user.age changes: userInfo re-evaluates, but nameOnly should not
    logic.actions.setAge(2)
    expect(logic.values.nameOnly).toBe('a')
    expect(userInfoEvals).toBe(2)
    expect(nameEvals).toBe(1)
    expect(logic.selectorHealth().selectors.nameOnly.dirtyCause).toBe(null)

    // user.name changes: both re-evaluate
    logic.actions.setName('b')
    expect(logic.values.nameOnly).toBe('b')
    expect(userInfoEvals).toBe(3)
    expect(nameEvals).toBe(2)
    expect(logic.selectorHealth().selectors.nameOnly.dirtyCause).toBe('selector:userInfo')
"""
assert old in s
s=s.replace(old,new)

# Add sameUser dirtyCause test after the dirtyCause immediate test
marker = "  test('react components only re-render for accessed changes', () => {"
addition = '''  test('whole reducer output deps report raw state paths as dirtyCause', () => {
    const logic = kea([
      actions({ setName: (name) => ({ name }) }),
      reducers({
        user: [{ name: 'a', age: 1 }, { setName: (state, { name }) => ({ ...state, name }) }],
      }),
      selectors({
        sameUser: [(s) => [s.user], (user) => user],
      }),
    ])
    logic.mount()
    expect(logic.values.sameUser.name).toBe('a')
    logic.actions.setName('b')
    expect(logic.values.sameUser.name).toBe('b')
    expect(logic.selectorHealth().selectors.sameUser.dirtyCause).toBe('user.name')
  })

'''
assert marker in s
s=s.replace(marker, addition + marker)
open(p,'w').write(s)
print('tests added')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -35