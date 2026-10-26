import { kea, resetContext, actions, reducers, selectors, connect } from '../../src'

describe('atomic selectors extra', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('resultEqualityCheck is respected for propagation', () => {
    const runs = { derived: 0, downstream: 0 }
    const logic = kea([
      actions({ set: (list) => ({ list }) }),
      reducers({ list: [['a', 'b'], { set: (_, { list }) => list }] }),
      selectors({
        lengthOnly: [
          (s) => [s.list],
          (list) => {
            runs.derived += 1
            return list.length
          },
          { resultEqualityCheck: (a, b) => a === b },
        ],
        downstream: [
          (s) => [s.lengthOnly],
          (length) => {
            runs.downstream += 1
            return length * 2
          },
        ],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.downstream).toBe(4)
    expect(runs).toEqual({ derived: 1, downstream: 1 })

    // change list but not length -> derived should not recompute
    logic.actions.set(['a', 'c'])
    expect(logic.values.downstream).toBe(4)
    expect(runs).toEqual({ derived: 1, downstream: 1 })

    // change length -> recompute
    logic.actions.set(['a', 'b', 'c'])
    expect(logic.values.downstream).toBe(6)
    expect(runs).toEqual({ derived: 2, downstream: 2 })

    unmount()
  })

  test('logic.selector returns the logic root', () => {
    const logic = kea([
      reducers({ a: ['x', {}] }),
    ])
    const unmount = logic.mount()
    const root = logic.selector()
    expect(root.a).toBe('x')
    unmount()
  })

  test('connect with wildcard values works', () => {
    const other = kea([
      reducers({ a: ['x', {}], b: ['y', {}] }),
    ])
    const logic = kea([
      connect({ values: [other, ['* as everything']] }),
      selectors({
        joined: [(s) => [s.everything], (everything) => `${everything.a}${everything.b}`],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.joined).toBe('xy')
    unmount()
  })

  test('Map iteration tracks all keys', () => {
    const logic = kea([
      actions({ setData: (map) => ({ map }) }),
      reducers({
        data: [new Map([['a', 1], ['b', 2]]), { setData: (_, { map }) => map }],
      }),
      selectors({
        total: [
          (s) => [s.data],
          (data) => {
            let sum = 0
            data.forEach((v) => { sum += v })
            return sum
          },
        ],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.total).toBe(3)
    const health = logic.selectorHealth()
    expect(health.selectors.total.dependencies).toContain('data.map:a')
    expect(health.selectors.total.dependencies).toContain('data.map:b')

    logic.actions.setData(new Map([['a', 5], ['b', 2]]))
    expect(logic.values.total).toBe(7)
    expect(logic.selectorHealth().selectors.total.evaluations).toBe(2)

    unmount()
  })

  test('Set iteration tracks all values', () => {
    const logic = kea([
      actions({ setData: (set) => ({ set }) }),
      reducers({
        data: [new Set([1, 2, 3]), { setData: (_, { set }) => set }],
      }),
      selectors({
        sum: [
          (s) => [s.data],
          (data) => {
            let total = 0
            for (const v of data) total += v
            return total
          },
        ],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.sum).toBe(6)
    expect(logic.selectorHealth().selectors.sum.dependencies).toContain('data.set:1')
    expect(logic.selectorHealth().selectors.sum.dependencies).toContain('data.set:2')
    expect(logic.selectorHealth().selectors.sum.dependencies).toContain('data.set:3')

    logic.actions.setData(new Set([1, 2, 4]))
    expect(logic.values.sum).toBe(7)

    unmount()
  })

  test('Array map tracks all indices', () => {
    let runs = 0
    const logic = kea([
      actions({ setList: (list) => ({ list }) }),
      reducers({ list: [[1, 2, 3], { setList: (_, { list }) => list }] }),
      selectors({
        doubled: [
          (s) => [s.list],
          (list) => {
            runs += 1
            return list.map((x) => x * 2)
          },
        ],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.doubled).toEqual([2, 4, 6])
    expect(logic.selectorHealth().selectors.doubled.dependencies).toContain('list.0')
    expect(logic.selectorHealth().selectors.doubled.dependencies).toContain('list.2')

    logic.actions.setList([1, 2, 4])
    expect(logic.values.doubled).toEqual([2, 4, 8])
    expect(runs).toBe(2)

    unmount()
  })

  test('mount also throws on circular dependencies', () => {
    const logic = kea([
      selectors({
        a: [(s) => [s.b], (b) => b],
        b: [(s) => [s.a], (a) => a],
      }),
    ])
    expect(() => logic.mount()).toThrow('[KEA] Circular dependency detected')
  })

  test('health stable identity persists through wrapping', () => {
    const logic = kea([
      actions({ set: (x) => ({ x }) }),
      reducers({ x: [1, { set: (_, { x }) => x }] }),
      selectors({
        doubleX: [(s) => [s.x], (x) => x * 2],
      }),
    ])

    const unmount = logic.mount()
    logic.values.doubleX
    const health1 = logic.selectorHealth()
    expect(health1.selectors.doubleX).toBeDefined()
    expect(health1.selectors.x).toBeDefined()

    logic.actions.set(2)
    const health2 = logic.selectorHealth()
    // Same identity - health persists through selector function wrapping
    expect(health2.selectors.doubleX.evaluations).toBe(2)
    unmount()
  })
})
