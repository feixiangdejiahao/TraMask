import { kea, resetContext, actions, reducers, selectors } from '../../src'

describe('atomic selectors advanced', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('multi-level chains propagate only to affected selectors', () => {
    const runs = { level1: 0, level2: 0, level3: 0 }
    const logic = kea([
      actions({
        setA: (a) => ({ a }),
        setB: (b) => ({ b }),
      }),
      reducers({
        a: ['a1', { setA: (_, { a }) => a }],
        b: ['b1', { setB: (_, { b }) => b }],
      }),
      selectors({
        level1: [
          (s) => [s.a, s.b],
          (a, b) => {
            runs.level1 += 1
            return { a, b }
          },
        ],
        level2: [
          (s) => [s.level1],
          (level1) => {
            runs.level2 += 1
            return level1.a
          },
        ],
        level3: [
          (s) => [s.level2],
          (level2) => {
            runs.level3 += 1
            return level2.toUpperCase()
          },
        ],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.level3).toBe('A1')
    expect(runs).toEqual({ level1: 1, level2: 1, level3: 1 })

    // changing b should not re-evaluate level2/level3
    logic.actions.setB('b2')
    expect(logic.values.level3).toBe('A1')
    expect(runs).toEqual({ level1: 2, level2: 1, level3: 1 })

    // changing a propagates through all levels
    logic.actions.setA('a2')
    expect(logic.values.level3).toBe('A2')
    expect(runs).toEqual({ level1: 3, level2: 2, level3: 2 })

    unmount()
  })

  test('atomic updates: one re-evaluation per action even with multiple dependency changes', () => {
    const runs = { sum: 0, product: 0 }
    const logic = kea([
      actions({ setBoth: (x, y) => ({ x, y }) }),
      reducers({
        x: [2, { setBoth: (_, { x }) => x }],
        y: [3, { setBoth: (_, { y }) => y }],
      }),
      selectors({
        sum: [
          (s) => [s.x, s.y],
          (x, y) => {
            runs.sum += 1
            return x + y
          },
        ],
        product: [
          (s) => [s.x, s.y],
          (x, y) => {
            runs.product += 1
            return x * y
          },
        ],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.sum).toBe(5)
    expect(logic.values.product).toBe(6)

    logic.actions.setBoth(4, 5)
    expect(logic.values.sum).toBe(9)
    expect(logic.values.product).toBe(20)
    expect(runs.sum).toBe(2)
    expect(runs.product).toBe(2)

    unmount()
  })

  test('dirtyCause uses selector:name when caused by another selector', () => {
    const logic = kea([
      actions({ setA: (a) => ({ a }) }),
      reducers({ a: ['x', { setA: (_, { a }) => a }] }),
      selectors({
        upper: [(s) => [s.a], (a) => a.toUpperCase()],
        doubled: [(s) => [s.upper], (upper) => upper + upper],
      }),
    ])

    const unmount = logic.mount()
    logic.values.doubled

    logic.actions.setA('y')
    expect(logic.selectorHealth().selectors.upper.dirtyCause).toBe('a')
    expect(logic.selectorHealth().selectors.doubled.dirtyCause).toBe('selector:upper')

    unmount()
  })

  test('Map key access uses map:key dependency', () => {
    const logic = kea([
      actions({ setMap: (map) => ({ map }) }),
      reducers({
        data: [new Map([['a', 1], ['b', 2]]), { setMap: (_, { map }) => map }],
      }),
      selectors({
        getA: [(s) => [s.data], (data) => data.get('a')],
        hasB: [(s) => [s.data], (data) => data.has('b')],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.getA).toBe(1)
    expect(logic.values.hasB).toBe(true)

    const health = logic.selectorHealth()
    expect(health.selectors.getA.dependencies).toContain('data.map:a')
    expect(health.selectors.hasB.dependencies).toContain('data.map:b')

    // change only b
    logic.actions.setMap(new Map([['a', 1], ['b', 99]]))
    expect(logic.values.getA).toBe(1)
    expect(logic.values.hasB).toBe(true)
    expect(logic.selectorHealth().selectors.getA.evaluations).toBe(1)

    // change a
    logic.actions.setMap(new Map([['a', 10], ['b', 99]]))
    expect(logic.values.getA).toBe(10)
    expect(logic.selectorHealth().selectors.getA.evaluations).toBe(2)

    unmount()
  })

  test('Set membership uses set:value dependency', () => {
    const logic = kea([
      actions({ setData: (set) => ({ set }) }),
      reducers({
        data: [new Set(['a', 'b']), { setData: (_, { set }) => set }],
      }),
      selectors({
        hasA: [(s) => [s.data], (data) => data.has('a')],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.hasA).toBe(true)

    const health = logic.selectorHealth()
    expect(health.selectors.hasA.dependencies).toContain('data.set:a')

    logic.actions.setData(new Set(['b', 'c']))
    expect(logic.values.hasA).toBe(false)
    expect(logic.selectorHealth().selectors.hasA.evaluations).toBe(2)

    unmount()
  })

  test('Array includes tracks indices checked', () => {
    const logic = kea([
      actions({ setList: (list) => ({ list }) }),
      reducers({
        list: [['a', 'b', 'c'], { setList: (_, { list }) => list }],
      }),
      selectors({
        includesB: [(s) => [s.list], (list) => list.includes('b')],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.includesB).toBe(true)

    const health = logic.selectorHealth()
    expect(health.selectors.includesB.dependencies).toContain('list.0')
    expect(health.selectors.includesB.dependencies).toContain('list.1')

    // change an element after the matched one -> no re-eval
    logic.actions.setList(['a', 'b', 'Z'])
    expect(logic.values.includesB).toBe(true)
    expect(logic.selectorHealth().selectors.includesB.evaluations).toBe(1)

    // change the matched element -> re-eval
    logic.actions.setList(['a', 'X', 'Z'])
    expect(logic.values.includesB).toBe(false)
    expect(logic.selectorHealth().selectors.includesB.evaluations).toBe(2)

    unmount()
  })

  test('circular dependencies throw during build', () => {
    const logic = kea([
      selectors({
        a: [(s) => [s.b], (b) => b + 1],
        b: [(s) => [s.a], (a) => a + 1],
      }),
    ])
    expect(() => logic.build()).toThrow('[KEA] Circular dependency detected')
  })

  test('works with multi-level chain where derived selector caches intermediate', () => {
    const runs = { info: 0, name: 0 }
    const logic = kea([
      actions({ setAge: (age) => ({ age }), setName: (name) => ({ name }) }),
      reducers({
        user: [
          { name: 'x', age: 1 },
          {
            setAge: (state, { age }) => ({ ...state, age }),
            setName: (state, { name }) => ({ ...state, name }),
          },
        ],
      }),
      selectors({
        userInfo: [
          (s) => [s.user],
          (user) => {
            runs.info += 1
            return { name: user.name }
          },
        ],
        userName: [
          (s) => [s.userInfo],
          (userInfo) => {
            runs.name += 1
            return userInfo.name
          },
        ],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.userName).toBe('x')
    expect(runs).toEqual({ info: 1, name: 1 })

    logic.actions.setAge(2)
    expect(logic.values.userName).toBe('x')
    expect(runs).toEqual({ info: 1, name: 1 })

    logic.actions.setName('y')
    expect(logic.values.userName).toBe('y')
    expect(runs).toEqual({ info: 2, name: 2 })

    unmount()
  })
})
