import { kea, resetContext, actions, reducers, selectors } from '../../src'

describe('atomic selectors', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('tracks leaf dependencies and skips unrelated changes', () => {
    let userNameRuns = 0
    const logic = kea([
      actions({
        setUserName: (name) => ({ name }),
        setUserAge: (age) => ({ age }),
      }),
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
        userName: [
          (s) => [s.user],
          (user) => {
            userNameRuns += 1
            return user.name
          },
        ],
      }),
    ])

    const unmount = logic.mount()

    expect(logic.values.userName).toBe('chirpy')
    expect(userNameRuns).toBe(1)

    logic.actions.setUserAge(31)

    expect(logic.values.userName).toBe('chirpy')
    expect(userNameRuns).toBe(1)

    logic.actions.setUserName('pollo')

    expect(logic.values.userName).toBe('pollo')
    expect(userNameRuns).toBe(2)

    unmount()
  })

  test('selectorHealth exposes dependencies, dependents and dirtyCause', () => {
    const logic = kea([
      actions({
        setUserName: (name) => ({ name }),
        setUserAge: (age) => ({ age }),
      }),
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
    logic.values.userName

    const health = logic.selectorHealth()
    expect(health.selectors.userName.dependencies).toContain('user.name')
    expect(health.selectors.user.dependents).toContain('userName')
    expect(health.topologicalOrder).toEqual(['user', 'userName'])

    // unrelated change should not invalidate userName
    logic.actions.setUserAge(31)
    expect(logic.selectorHealth().selectors.userName.dirtyCause).toBeNull()
    expect(logic.selectorHealth().selectors.user.dirtyCause).toBe('user')

    // related change invalidates userName
    logic.actions.setUserName('pollo')
    expect(logic.selectorHealth().selectors.userName.dirtyCause).toBe('user.name')

    logic.values.userName
    expect(logic.selectorHealth().selectors.userName.evaluations).toBe(2)

    unmount()
  })

  test('selectorHealth is available on logics without selectors', () => {
    const logic = kea({})
    const unmount = logic.mount()
    expect(typeof logic.selectorHealth).toBe('function')
    expect(logic.selectorHealth()).toEqual({ selectors: {}, topologicalOrder: [] })
    unmount()
  })

  test('reducer selectors appear in selectorHealth', () => {
    const logic = kea({
      reducers: { value: ['x', {}] },
    })
    const unmount = logic.mount()
    logic.values.value
    const health = logic.selectorHealth()
    expect(health.selectors.value).toBeDefined()
    expect(health.topologicalOrder).toEqual(['value'])
    unmount()
  })

  test('selectorHealth is undefined when disabled', () => {
    resetContext({ createStore: true })
    const logic = kea({
      reducers: { value: ['x', {}] },
    })
    logic.mount()
    expect(logic.selectorHealth).toBeUndefined()
    logic.unmount()
  })
})
