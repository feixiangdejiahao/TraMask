import { kea, resetContext, actions, reducers, selectors } from '../../src'

describe('atomic selectors derived nested', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('derived nested leaf tracking prunes intermediate parents', () => {
    let level2Runs = 0
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
        address: [(s) => [s.user], (user) => user.address],
        city: [
          (s) => [s.address],
          (address) => {
            level2Runs += 1
            return address.city
          },
        ],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.city).toBe('a')
    expect(level2Runs).toBe(1)
    expect(logic.selectorHealth().selectors.city.dependencies).toEqual(['address.city'])

    logic.actions.setZip(2)
    expect(logic.values.city).toBe('a')
    expect(level2Runs).toBe(1)

    logic.actions.setCity('b')
    expect(logic.values.city).toBe('b')
    expect(level2Runs).toBe(2)

    unmount()
  })
})
