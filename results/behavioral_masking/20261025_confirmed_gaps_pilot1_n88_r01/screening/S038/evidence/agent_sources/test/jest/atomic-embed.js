import { kea, resetContext, actions, reducers, selectors } from '../../src'

describe('atomic selectors embedded inputs', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('selector embedding an object input re-evaluates when it changes', () => {
    const logic = kea([
      actions({ setAge: (age) => ({ age }) }),
      reducers({
        user: [
          { name: 'x', age: 1 },
          { setAge: (state, { age }) => ({ ...state, age }) },
        ],
      }),
      selectors({
        wrapped: [(s) => [s.user], (user) => ({ user })],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.wrapped.user.name).toBe('x')
    expect(logic.selectorHealth().selectors.wrapped.dependencies).toContain('user')

    logic.actions.setAge(2)
    expect(logic.values.wrapped.user.age).toBe(2)
    expect(logic.selectorHealth().selectors.wrapped.evaluations).toBe(2)

    unmount()
  })

  test('explicit whole-object dependency survives pruning', () => {
    const logic = kea([
      actions({ setAge: (age) => ({ age }) }),
      reducers({
        user: [
          { name: 'x', age: 1 },
          { setAge: (state, { age }) => ({ ...state, age }) },
        ],
      }),
      selectors({
        wrapped: [(s) => [s.user], (user) => ({ user, name: user.name })],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.wrapped.user.name).toBe('x')
    const deps = logic.selectorHealth().selectors.wrapped.dependencies
    expect(deps).toContain('user')
    expect(deps).toContain('user.name')

    // whole user changed -> re-evaluate
    logic.actions.setAge(2)
    expect(logic.values.wrapped.user.age).toBe(2)
    expect(logic.selectorHealth().selectors.wrapped.evaluations).toBe(2)

    unmount()
  })

  test('nested embedded input works', () => {
    const logic = kea([
      actions({ setName: (name) => ({ name }) }),
      reducers({
        user: [
          { name: 'x', age: 1 },
          { setName: (state, { name }) => ({ ...state, name }) },
        ],
      }),
      selectors({
        nested: [(s) => [s.user], (user) => ({ data: { user } })],
      }),
    ])

    const unmount = logic.mount()
    expect(logic.values.nested.data.user.name).toBe('x')
    logic.actions.setName('y')
    expect(logic.values.nested.data.user.name).toBe('y')
    unmount()
  })
})
