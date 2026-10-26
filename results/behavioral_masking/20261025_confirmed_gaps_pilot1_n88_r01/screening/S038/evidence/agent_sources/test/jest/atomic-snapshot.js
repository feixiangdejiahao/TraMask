import { kea, resetContext, actions, reducers, selectors, getContext } from '../../src'

describe('atomic selectors snapshot stability (React integration contract)', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('snapshots are stable unless the accessed selector changes', () => {
    const logic = kea([
      actions({ setUserName: (name) => ({ name }), setUserAge: (age) => ({ age }) }),
      reducers({
        user: [
          { name: 'chirpy', age: 30 },
          {
            setUserName: (state, { name }) => ({ ...state, name }),
            setUserAge: (state, { age }) => ({ ...state, age }),
          },
        ],
      }),
      selectors({
        userName: [(s) => [s.user], (user) => user.name],
      }),
    ])

    const unmount = logic.mount()
    const store = getContext().store
    const snapshot = () => logic.selectors.userName(store.getState())

    const first = snapshot()
    expect(first).toBe('chirpy')

    // unrelated change -> same value (primitive string, so same by value)
    logic.actions.setUserAge(31)
    expect(snapshot()).toBe('chirpy')

    // related change -> new value
    logic.actions.setUserName('pollo')
    expect(snapshot()).toBe('pollo')

    // object selector: proxy reference should be stable across unrelated changes
    const userSnap1 = logic.selectors.user(store.getState())
    logic.actions.setUserAge(32)
    const userSnap2 = logic.selectors.user(store.getState())
    expect(userSnap2).not.toBe(userSnap1) // whole user object changed, so re-render
    expect(userSnap2.name).toBe('pollo')
    expect(userSnap2.age).toBe(32)

    unmount()
  })
})
