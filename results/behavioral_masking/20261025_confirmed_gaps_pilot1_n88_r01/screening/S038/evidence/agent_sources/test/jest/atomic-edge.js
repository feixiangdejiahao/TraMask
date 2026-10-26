import { kea, resetContext, actions, reducers, selectors, activatePlugin } from '../../src'

describe('atomic selectors edge cases', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('dependencies list only leaf paths, not parent nodes', () => {
    const logic = kea([
      reducers({ user: [{ name: 'x', age: 1 }, {}] }),
      selectors({
        userName: [(s) => [s.user], (user) => user.name],
      }),
    ])

    const unmount = logic.mount()
    logic.values.userName
    const deps = logic.selectorHealth().selectors.userName.dependencies
    expect(deps).toContain('user.name')
    expect(deps).not.toContain('user')
    unmount()
  })

  test('direct selector calls return values through proxies', () => {
    const logic = kea([
      reducers({ user: [{ name: 'x', age: 1 }, {}] }),
      selectors({
        userName: [(s) => [s.user], (user) => user.name],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.selectors.user()).toEqual({ name: 'x', age: 1 })
    expect(logic.selectors.userName()).toBe('x')
    unmount()
  })

  test('includes with no match tracks all indices', () => {
    const logic = kea([
      actions({ setList: (list) => ({ list }) }),
      reducers({ list: [['a', 'b'], { setList: (_, { list }) => list }] }),
      selectors({
        hasZ: [(s) => [s.list], (list) => list.includes('z')],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.hasZ).toBe(false)
    const deps = logic.selectorHealth().selectors.hasZ.dependencies
    expect(deps).toContain('list.0')
    expect(deps).toContain('list.1')

    logic.actions.setList(['a', 'Z'])
    expect(logic.values.hasZ).toBe(false)
    expect(logic.selectorHealth().selectors.hasZ.evaluations).toBe(2)

    unmount()
  })

  test('plugin afterMount ordering preserved with atomic engine', () => {
    const order = []
    activatePlugin({
      name: 'ordering-test',
      events: {
        afterMount(logic) { order.push('plugin.afterMount') },
        beforeMount(logic) { order.push('plugin.beforeMount') },
        afterUnmount(logic) { order.push('plugin.afterUnmount') },
        beforeUnmount(logic) { order.push('plugin.beforeUnmount') },
      },
    })

    const logic = kea({
      events: {
        beforeMount() { order.push('logic.beforeMount') },
        afterMount() { order.push('logic.afterMount') },
        beforeUnmount() { order.push('logic.beforeUnmount') },
        afterUnmount() { order.push('logic.afterUnmount') },
      },
    })

    const unmount = logic.mount()
    expect(order).toEqual(['plugin.beforeMount', 'logic.beforeMount', 'plugin.afterMount', 'logic.afterMount'])
    unmount()
    expect(order).toEqual([
      'plugin.beforeMount',
      'logic.beforeMount',
      'plugin.afterMount',
      'logic.afterMount',
      'plugin.beforeUnmount',
      'logic.beforeUnmount',
      'plugin.afterUnmount',
      'logic.afterUnmount',
    ])
  })

  test('dirtyCause persists after recompute', () => {
    const logic = kea([
      actions({ setName: (name) => ({ name }) }),
      reducers({ name: ['x', { setName: (_, { name }) => name }] }),
      selectors({
        upper: [(s) => [s.name], (name) => name.toUpperCase()],
      }),
    ])

    const unmount = logic.mount()
    logic.values.upper
    logic.actions.setName('y')
    expect(logic.selectorHealth().selectors.upper.dirtyCause).toBe('name')
    logic.values.upper
    expect(logic.selectorHealth().selectors.upper.dirtyCause).toBe('name')
    unmount()
  })
})
