import { kea, resetContext, actions, reducers, selectors, connect } from '../../src'

describe('atomic selectors integration', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('connected logic values work and propagate', () => {
    const otherLogic = kea([
      actions({ setValue: (value) => ({ value }) }),
      reducers({ value: ['x', { setValue: (_, { value }) => value }] }),
      selectors({
        upper: [(s) => [s.value], (value) => value.toUpperCase()],
      }),
    ])

    const logic = kea([
      connect({
        values: [otherLogic, ['upper as connectedUpper']],
      }),
      selectors({
        doubled: [(s) => [s.connectedUpper], (upper) => upper + upper],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.doubled).toBe('XX')

    otherLogic.actions.setValue('y')
    expect(logic.values.doubled).toBe('YY')

    const health = logic.selectorHealth()
    expect(health.selectors.doubled.dependencies).toContain('connectedUpper')

    unmount()
  })

  test('array index reads use list.N dependencies', () => {
    let runs = 0
    const logic = kea([
      actions({ setList: (list) => ({ list }) }),
      reducers({ list: [['a', 'b'], { setList: (_, { list }) => list }] }),
      selectors({
        first: [
          (s) => [s.list],
          (list) => {
            runs += 1
            return list[0]
          },
        ],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.first).toBe('a')
    expect(logic.selectorHealth().selectors.first.dependencies).toContain('list.0')

    logic.actions.setList(['a', 'Z'])
    expect(logic.values.first).toBe('a')
    expect(runs).toBe(1)

    logic.actions.setList(['b', 'Z'])
    expect(logic.values.first).toBe('b')
    expect(runs).toBe(2)

    unmount()
  })

  test('lifecycle ordering is preserved with atomic selectors', () => {
    const order = []
    const logic = kea({
      events: () => ({
        beforeMount() { order.push('logic.beforeMount') },
        afterMount() { order.push('logic.afterMount') },
        beforeUnmount() { order.push('logic.beforeUnmount') },
        afterUnmount() { order.push('logic.afterUnmount') },
      }),
      selectors: {
        constant: [() => [], () => 42],
      },
    })

    const unmount = logic.mount()
    expect(logic.values.constant).toBe(42)
    expect(order).toEqual(['logic.beforeMount', 'logic.afterMount'])

    unmount()
    expect(order).toEqual([
      'logic.beforeMount',
      'logic.afterMount',
      'logic.beforeUnmount',
      'logic.afterUnmount',
    ])
  })

  test('props dependencies invalidate on props change', () => {
    const logic = kea([
      selectors({
        doubledProp: [(s, p) => [p.value], (value) => value * 2],
      }),
    ])

    const built = logic({ value: 2 })
    const unmount = built.mount()
    expect(built.values.doubledProp).toBe(4)
    expect(built.selectorHealth().selectors.doubledProp.dependencies).toContain('props:value')

    built.props.value = 3
    built.lastProps = { value: 3 }
    built.events.propsChanged?.({ value: 3 }, { value: 2 })
    expect(built.values.doubledProp).toBe(6)

    unmount()
  })

  test('multiple selectors depending on same state each evaluate once per action', () => {
    const runs = { a: 0, b: 0 }
    const logic = kea([
      actions({ set: (x) => ({ x }) }),
      reducers({ x: [1, { set: (_, { x }) => x }] }),
      selectors({
        selA: [(s) => [s.x], (x) => { runs.a += 1; return x * 2 }],
        selB: [(s) => [s.x], (x) => { runs.b += 1; return x * 3 }],
      }),
    ])

    const unmount = logic.mount()
    logic.values.selA
    logic.values.selB
    expect(runs).toEqual({ a: 1, b: 1 })

    logic.actions.set(2)
    logic.values.selA
    logic.values.selB
    expect(runs).toEqual({ a: 2, b: 2 })

    unmount()
  })
})
