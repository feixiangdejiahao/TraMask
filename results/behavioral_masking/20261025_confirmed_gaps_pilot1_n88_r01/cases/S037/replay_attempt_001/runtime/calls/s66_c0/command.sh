cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
marker = "  test('detects indirect circular dependencies', () => {"
addition = '''  test('propagates through derived object selectors at leaf level', () => {
    let userInfoEvals = 0
    let nameEvals = 0
    const logic = kea([
      actions({ setName: (name) => ({ name }), setAge: (age) => ({ age }) }),
      reducers({
        user: [
          { name: 'a', age: 1 },
          {
            setName: (state, { name }) => ({ ...state, name }),
            setAge: (state, { age }) => ({ ...state, age }),
          },
        ],
      }),
      selectors({
        userInfo: [(s) => [s.user], (user) => {
          userInfoEvals += 1
          return { name: user.name, age: user.age }
        }],
        nameOnly: [(s) => [s.userInfo], (info) => {
          nameEvals += 1
          return info.name
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.nameOnly).toBe('a')
    expect(userInfoEvals).toBe(1)
    expect(nameEvals).toBe(1)

    // user.age changes: userInfo re-evaluates, but nameOnly should not
    logic.actions.setAge(2)
    expect(logic.values.nameOnly).toBe('a')
    expect(userInfoEvals).toBe(2)
    expect(nameEvals).toBe(1)

    // user.name changes: both re-evaluate
    logic.actions.setName('b')
    expect(logic.values.nameOnly).toBe('b')
    expect(userInfoEvals).toBe(3)
    expect(nameEvals).toBe(2)

    const health = logic.selectorHealth()
    expect(health.selectors.userInfo.dependencies).toContain('user.name')
    expect(health.selectors.userInfo.dependencies).toContain('user.age')
    expect(health.selectors.nameOnly.dependencies).toContain('userInfo.name')
  })

  test('tracks nested Map value access', () => {
    let nameEvals = 0
    const logic = kea([
      actions({ setMapValue: (key, value) => ({ key, value }) }),
      reducers({
        data: [
          new Map([['a', { name: 'x', age: 1 }]]),
          {
            setMapValue: (state, { key, value }) => {
              const next = new Map(state)
              next.set(key, value)
              return next
            },
          },
        ],
      }),
      selectors({
        nameA: [(s) => [s.data], (data) => {
          nameEvals += 1
          return data.get('a').name
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.nameA).toBe('x')
    expect(nameEvals).toBe(1)
    expect(logic.selectorHealth().selectors.nameA.dependencies).toContain('data.map:a.name')

    logic.actions.setMapValue('a', { name: 'x', age: 2 })
    expect(logic.values.nameA).toBe('x')
    expect(nameEvals).toBe(1)

    logic.actions.setMapValue('a', { name: 'y', age: 2 })
    expect(logic.values.nameA).toBe('y')
    expect(nameEvals).toBe(2)
  })

  test('re-evaluates selectors when props change', () => {
    const logic = kea({
      selectors: () => ({
        id: [(s, p) => [p.id], (id) => id],
      }),
    })
    const built = logic({ id: 1 })
    built.mount()
    expect(built.values.id).toBe(1)

    logic({ id: 2 })
    expect(built.values.id).toBe(2)
  })

  test('works with connected values', () => {
    const source = kea([
      actions({ setCount: (count) => ({ count }) }),
      reducers({ count: [1, { setCount: (_, { count }) => count }] }),
    ])
    const target = kea([
      connect,
    ])
    // Use a manual connect since the builder is imported below
    const { connect } = require('../../src')
    const targetLogic = kea([
      connect({ values: [source, ['count']] }),
      selectors({
        doubled: [(s) => [s.count], (count) => count * 2],
      }),
    ])
    targetLogic.mount()
    expect(targetLogic.values.doubled).toBe(2)
    source.actions.setCount(3)
    expect(targetLogic.values.doubled).toBe(6)
  })

'''
assert marker in s
s=s.replace(marker, addition + marker)
open(p,'w').write(s)
print('added edge tests')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -60