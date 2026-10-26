cd /app && cat > test/jest/atomic-selectors.js <<'EOF'
import React, { useState } from 'react'
import { render, screen, act } from '@testing-library/react'
import { kea, resetContext, getContext, actions, reducers, selectors, path, useValues } from '../../src'

describe('atomic selectors', () => {
  beforeEach(() => {
    resetContext({ atomicSelectors: true, createStore: true })
  })

  test('selectorHealth is undefined when atomicSelectors disabled', () => {
    resetContext({ createStore: true })
    const logic = kea({
      selectors: () => ({
        double: [(s) => [s.count], (count) => count * 2],
      }),
      reducers: () => ({ count: [1, {}] }),
    })
    logic.mount()
    expect(logic.selectorHealth).toBe(undefined)
    expect(logic().selectorHealth).toBe(undefined)
  })

  test('selectorHealth is a function when enabled', () => {
    const logic = kea({
      selectors: () => ({
        double: [(s) => [s.count], (count) => count * 2],
      }),
      reducers: () => ({ count: [1, {}] }),
    })
    logic.mount()
    expect(typeof logic.selectorHealth).toBe('function')
    const health = logic.selectorHealth()
    expect(health.selectors.count).toBeDefined()
    expect(health.selectors.double).toBeDefined()
    expect(health.topologicalOrder).toEqual(['count', 'double'])
  })

  test('tracks dependencies at leaf level (user.name vs user.age)', () => {
    const logic = kea([
      actions({ setName: (name) => ({ name }), setAge: (age) => ({ age }) }),
      reducers({
        user: [
          { name: 'a', age: 1 },
          {
            setName: (state, { name }) => ({ ...state, name }),
            setAge: (state, { age }) => ({ ...state, age }),
          },
        ],
      }),
      selectors({
        userName: [(s) => [s.user], (user) => user.name],
      }),
    ])

    let nameEvals = 0
    const evalLogic = kea([
      actions({ setName: (name) => ({ name }), setAge: (age) => ({ age }) }),
      reducers({
        user: [
          { name: 'a', age: 1 },
          {
            setName: (state, { name }) => ({ ...state, name }),
            setAge: (state, { age }) => ({ ...state, age }),
          },
        ],
      }),
      selectors({
        userName: [
          (s) => [s.user],
          (user) => {
            nameEvals += 1
            return user.name
          },
        ],
      }),
    ])

    const unmount = evalLogic.mount()
    expect(evalLogic.values.userName).toBe('a')
    const before = evalLogic.selectorHealth()
    expect(before.selectors.userName.dependencies).toContain('user.name')
    expect(before.selectors.userName.dependencies).not.toContain('user')
    expect(before.selectors.userName.dependencies).not.toContain('user.age')

    const evalBefore = evalLogic.selectorHealth().selectors.userName.evaluations
    evalLogic.actions.setAge(2)
    // user.age changed, user.name did not -> no re-evaluation
    expect(evalLogic.values.userName).toBe('a')
    expect(evalLogic.selectorHealth().selectors.userName.evaluations).toBe(evalBefore)

    evalLogic.actions.setName('b')
    expect(evalLogic.values.userName).toBe('b')
    expect(evalLogic.selectorHealth().selectors.userName.evaluations).toBe(evalBefore + 1)

    unmount()
    // second logic not mounted, just ensure it builds
    expect(logic.pathString).toBeTruthy()
  })

  test('supports Map key access dependencies', () => {
    const logic = kea([
      actions({ setMap: (map) => ({ map }) }),
      reducers({
        data: [new Map([['a', 1], ['b', 2]]), {
          setMap: (state, { map }) => map,
        }],
      }),
      selectors({
        valueA: [(s) => [s.data], (data) => data.get('a')],
      }),
    ])
    logic.mount()
    expect(logic.values.valueA).toBe(1)
    const health = logic.selectorHealth()
    expect(health.selectors.valueA.dependencies).toContain('data.map:a')
    expect(health.selectors.valueA.dependencies).not.toContain('data.map:b')
  })

  test('supports Set membership dependencies', () => {
    const logic = kea([
      actions({ setSet: (set) => ({ set }) }),
      reducers({
        data: [new Set(['a', 'b']), {
          setSet: (state, { set }) => set,
        }],
      }),
      selectors({
        hasA: [(s) => [s.data], (data) => data.has('a')],
      }),
    ])
    logic.mount()
    expect(logic.values.hasA).toBe(true)
    const health = logic.selectorHealth()
    expect(health.selectors.hasA.dependencies).toContain('data.set:a')
    expect(health.selectors.hasA.dependencies).not.toContain('data.set:b')
  })

  test('supports Array index and includes dependencies', () => {
    const logic = kea([
      actions({ setList: (list) => ({ list }) }),
      reducers({
        list: [[10, 20, 30], {
          setList: (state, { list }) => list,
        }],
      }),
      selectors({
        first: [(s) => [s.list], (list) => list[0]],
        hasTen: [(s) => [s.list], (list) => list.includes(10)],
      }),
    ])
    logic.mount()
    expect(logic.values.first).toBe(10)
    expect(logic.values.hasTen).toBe(true)
    const health = logic.selectorHealth()
    expect(health.selectors.first.dependencies).toContain('list.0')
    expect(health.selectors.hasTen.dependencies).toEqual(expect.arrayContaining(['list.0', 'list.1', 'list.2']))
  })

  test('propagates through multi-level chains only to affected selectors', () => {
    let lowerEvals = 0
    let middleEvals = 0
    let upperEvals = 0

    const logic = kea([
      actions({ setLower: (v) => ({ v }) }),
      reducers({
        lower: ['a', { setLower: (_, { v }) => v }],
      }),
      selectors({
        middle: [(s) => [s.lower], (lower) => {
          middleEvals += 1
          return lower.toUpperCase()
        }],
        upper: [(s) => [s.middle], (middle) => {
          upperEvals += 1
          return middle + '!'
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.upper).toBe('A!')
    expect(middleEvals).toBe(1)
    expect(upperEvals).toBe(1)

    logic.actions.setLower('b')
    expect(logic.values.upper).toBe('B!')
    expect(middleEvals).toBe(2)
    expect(upperEvals).toBe(2)

    // No changes -> no re-evaluations
    logic.actions.setLower('b')
    expect(logic.values.upper).toBe('B!')
    expect(middleEvals).toBe(2)
    expect(upperEvals).toBe(2)

    const health = logic.selectorHealth()
    expect(health.selectors.middle.dependencies).toContain('lower')
    expect(health.selectors.upper.dependencies).toContain('middle')
    expect(health.selectors.lower.dependents).toContain('middle')
    expect(health.selectors.middle.dependents).toContain('upper')
    expect(health.topologicalOrder).toEqual(['lower', 'middle', 'upper'])
  })

  test('atomic updates trigger exactly one re-evaluation', () => {
    let evals = 0
    const logic = kea([
      actions({ setBoth: (name, age) => ({ name, age }) }),
      reducers({
        user: [
          { name: 'a', age: 1 },
          {
            setBoth: (state, { name, age }) => ({ ...state, name, age }),
          },
        ],
      }),
      selectors({
        userInfo: [(s) => [s.user], (user) => {
          evals += 1
          return `${user.name}:${user.age}`
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.userInfo).toBe('a:1')
    expect(evals).toBe(1)
    logic.actions.setBoth('b', 2)
    expect(logic.values.userInfo).toBe('b:2')
    expect(evals).toBe(2)
    // Calling values again should not re-evaluate
    expect(logic.values.userInfo).toBe('b:2')
    expect(evals).toBe(2)
  })

  test('detects circular dependencies during build', () => {
    const circularLogic = kea({
      selectors: () => ({
        a: [(s) => [s.b], (b) => b],
        b: [(s) => [s.a], (a) => a],
      }),
    })
    expect(() => circularLogic()).toThrow('[KEA] Circular dependency detected')
  })

  test('exposes dirtyCause', () => {
    const logic = kea([
      actions({ setName: (name) => ({ name }), setAge: (age) => ({ age }) }),
      reducers({
        user: [
          { name: 'a', age: 1 },
          {
            setName: (state, { name }) => ({ ...state, name }),
            setAge: (state, { age }) => ({ ...state, age }),
          },
        ],
      }),
      selectors({
        userName: [(s) => [s.user], (user) => user.name],
        greeting: [(s) => [s.userName], (userName) => `hi ${userName}`],
      }),
    ])
    logic.mount()
    expect(logic.values.greeting).toBe('hi a')
    logic.actions.setName('b')
    expect(logic.values.greeting).toBe('hi b')
    const health = logic.selectorHealth()
    expect(health.selectors.userName.dirtyCause).toBe('user.name')
    expect(health.selectors.greeting.dirtyCause).toBe('selector:userName')
  })

  test('react components only re-render for accessed changes', () => {
    const logic = kea([
      actions({ setName: (name) => ({ name }), setAge: (age) => ({ age }) }),
      reducers({
        user: [
          { name: 'a', age: 1 },
          {
            setName: (state, { name }) => ({ ...state, name }),
            setAge: (state, { age }) => ({ ...state, age }),
          },
        ],
      }),
      selectors({
        userName: [(s) => [s.user], (user) => user.name],
      }),
    ])

    let renders = 0
    function NameComponent() {
      renders += 1
      const { userName } = useValues(logic)
      return <div data-testid="name">{userName}</div>
    }

    render(<NameComponent />)
    expect(screen.getByTestId('name')).toHaveTextContent('a')
    const rendersAfterMount = renders

    act(() => logic.actions.setAge(2))
    expect(screen.getByTestId('name')).toHaveTextContent('a')
    expect(renders).toBe(rendersAfterMount)

    act(() => logic.actions.setName('b'))
    expect(screen.getByTestId('name')).toHaveTextContent('b')
    expect(renders).toBe(rendersAfterMount + 1)
  })

  test('does not disrupt plugin lifecycle ordering', () => {
    const order = []
    const testPlugin = {
      name: 'atomic-test-plugin',
      events: {
        afterLogic(logic) { order.push(`afterLogic:${logic.pathString}`) },
        beforeMount(logic) { order.push(`beforeMount:${logic.pathString}`) },
        afterMount(logic) { order.push(`afterMount:${logic.pathString}`) },
      },
    }
    getContext().plugins.activated.push(testPlugin)
    getContext().plugins.events.afterLogic.push(testPlugin.events.afterLogic)
    getContext().plugins.events.beforeMount.push(testPlugin.events.beforeMount)
    getContext().plugins.events.afterMount.push(testPlugin.events.afterMount)

    const logic = kea([
      path(['atomic', 'lifecycle']),
      reducers({ value: [1, {}] }),
      selectors({ doubled: [(s) => [s.value], (value) => value * 2] }),
    ])
    logic.mount()
    expect(order).toEqual([
      'afterLogic:atomic.lifecycle',
      'beforeMount:atomic.lifecycle',
      'afterMount:atomic.lifecycle',
    ])
  })
})
EOF
echo "test written"