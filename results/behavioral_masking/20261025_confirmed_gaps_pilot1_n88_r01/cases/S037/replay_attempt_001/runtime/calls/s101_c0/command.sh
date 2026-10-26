cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
marker = "  test('tracks nested Map value access', () => {"
addition = '''  test('tracks spread reads through selector outputs', () => {
    let copyEvals = 0
    const logic = kea([
      actions({ setAge: (age) => ({ age }) }),
      reducers({
        user: [{ name: 'a', age: 1 }, { setAge: (state, { age }) => ({ ...state, age }) }],
      }),
      selectors({
        userCopy: [(s) => [s.user], (user) => {
          copyEvals += 1
          return { ...user }
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.userCopy.name).toBe('a')
    const health = logic.selectorHealth()
    expect(health.selectors.userCopy.dependencies).toContain('user.name')
    expect(health.selectors.userCopy.dependencies).toContain('user.age')
    expect(copyEvals).toBe(1)

    logic.actions.setAge(2)
    expect(logic.values.userCopy.age).toBe(2)
    expect(copyEvals).toBe(2)
  })

'''
assert marker in s
s=s.replace(marker, addition + marker)
open(p,'w').write(s)
print('test added')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js -t "spread" 2>&1 | tail -20