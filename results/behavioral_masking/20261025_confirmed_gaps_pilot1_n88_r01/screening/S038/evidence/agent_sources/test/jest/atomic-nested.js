import { kea, resetContext, actions, reducers, selectors } from '../../src'

describe('atomic selectors nested paths', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('nested object paths are tracked at leaf level', () => {
    const logic = kea([
      actions({ setCity: (city) => ({ city }), setZip: (zip) => ({ zip }) }),
      reducers({
        user: [
          { address: { city: 'a', zip: 1 } },
          {
            setCity: (state, { city }) => ({ ...state, address: { ...state.address, city } }),
            setZip: (state, { zip }) => ({ ...state, address: { ...state.address, zip } }),
          },
        ],
      }),
      selectors({
        city: [(s) => [s.user], (user) => user.address.city],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.city).toBe('a')
    expect(logic.selectorHealth().selectors.city.dependencies).toContain('user.address.city')

    logic.actions.setZip(2)
    expect(logic.values.city).toBe('a')
    expect(logic.selectorHealth().selectors.city.evaluations).toBe(1)

    logic.actions.setCity('b')
    expect(logic.values.city).toBe('b')
    expect(logic.selectorHealth().selectors.city.evaluations).toBe(2)

    unmount()
  })

  test('Map value object leaf is tracked', () => {
    const logic = kea([
      actions({ setMap: (map) => ({ map }) }),
      reducers({
        data: [new Map([['a', { name: 'x', age: 1 }]]), { setMap: (_, { map }) => map }],
      }),
      selectors({
        name: [(s) => [s.data], (data) => data.get('a').name],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.name).toBe('x')
    const deps = logic.selectorHealth().selectors.name.dependencies
    expect(deps).toContain('data.map:a')
    expect(deps).toContain('data.map:a.name')

    // changing any part of the value at key 'a' changes data.map:a, so it re-evaluates
    logic.actions.setMap(new Map([['a', { name: 'x', age: 2 }]]))
    expect(logic.values.name).toBe('x')
    expect(logic.selectorHealth().selectors.name.evaluations).toBe(2)

    logic.actions.setMap(new Map([['a', { name: 'y', age: 2 }]]))
    expect(logic.values.name).toBe('y')
    expect(logic.selectorHealth().selectors.name.evaluations).toBe(3)

    unmount()
  })
})
