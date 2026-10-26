cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
# Insert additional tests before the final lifecycle test
marker = "  test('does not disrupt plugin lifecycle ordering', () => {"
addition = '''  test('Map changes only invalidate selectors reading that key', () => {
    let valueAEvals = 0
    const logic = kea([
      actions({ setMapValue: (key, value) => ({ key, value }) }),
      reducers({
        data: [
          new Map([['a', 1], ['b', 2]]),
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
        valueA: [(s) => [s.data], (data) => {
          valueAEvals += 1
          return data.get('a')
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.valueA).toBe(1)
    expect(valueAEvals).toBe(1)

    logic.actions.setMapValue('b', 22)
    expect(logic.values.valueA).toBe(1)
    expect(valueAEvals).toBe(1)

    logic.actions.setMapValue('a', 11)
    expect(logic.values.valueA).toBe(11)
    expect(valueAEvals).toBe(2)
  })

  test('Set membership changes only invalidate selectors reading that value', () => {
    let hasAEvals = 0
    const logic = kea([
      actions({ toggle: (value) => ({ value }) }),
      reducers({
        data: [
          new Set(['a']),
          {
            toggle: (state, { value }) => {
              const next = new Set(state)
              if (next.has(value)) next.delete(value)
              else next.add(value)
              return next
            },
          },
        ],
      }),
      selectors({
        hasA: [(s) => [s.data], (data) => {
          hasAEvals += 1
          return data.has('a')
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.hasA).toBe(true)
    expect(hasAEvals).toBe(1)

    logic.actions.toggle('b')
    expect(logic.values.hasA).toBe(true)
    expect(hasAEvals).toBe(1)

    logic.actions.toggle('a')
    expect(logic.values.hasA).toBe(false)
    expect(hasAEvals).toBe(2)
  })

  test('Array changes only invalidate selectors reading changed indices', () => {
    let firstEvals = 0
    let hasEvals = 0
    const logic = kea([
      actions({ setIndex: (index, value) => ({ index, value }) }),
      reducers({
        list: [
          [10, 20, 30],
          {
            setIndex: (state, { index, value }) => state.map((v, i) => (i === index ? value : v)),
          },
        ],
      }),
      selectors({
        first: [(s) => [s.list], (list) => {
          firstEvals += 1
          return list[0]
        }],
        hasTen: [(s) => [s.list], (list) => {
          hasEvals += 1
          return list.includes(10)
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.first).toBe(10)
    expect(logic.values.hasTen).toBe(true)
    expect(firstEvals).toBe(1)
    expect(hasEvals).toBe(1)

    logic.actions.setIndex(1, 99)
    expect(logic.values.first).toBe(10)
    expect(logic.values.hasTen).toBe(true)
    expect(firstEvals).toBe(1)
    expect(hasEvals).toBe(1)

    logic.actions.setIndex(0, 42)
    expect(logic.values.first).toBe(42)
    expect(logic.values.hasTen).toBe(false)
    expect(firstEvals).toBe(2)
    expect(hasEvals).toBe(2)
  })

  test('detects indirect circular dependencies', () => {
    const circularLogic = kea({
      selectors: () => ({
        a: [(s) => [s.b], (b) => b],
        b: [(s) => [s.c], (c) => c],
        c: [(s) => [s.a], (a) => a],
      }),
    })
    expect(() => circularLogic()).toThrow('[KEA] Circular dependency detected')
  })

'''
assert marker in s
s=s.replace(marker, addition + marker)
open(p,'w').write(s)
print('added tests')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -80