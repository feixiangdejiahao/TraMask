import React, { useState } from 'react'
import { render, screen, act } from '@testing-library/react'
import { kea, resetContext, getContext, actions, reducers, selectors, path, useValues, activatePlugin, connect } from '../../src'

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
    resetContext({ createStore: true, atomicSelectors: true })
    const logic = kea({
      selectors: () => ({
        double: [(s) => [s.count], (count) => count * 2],
      }),
      reducers: () => ({ count: [1, {}] }),
    })
    resetContext({ createStore: true, atomicSelectors: true })
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

  test('dirtyCause is set immediately after an action', () => {
    const logic = kea([
      actions({ setName: (name) => ({ name }) }),
      reducers({
        user: [{ name: 'a', age: 1 }, { setName: (state, { name }) => ({ ...state, name }) }],
      }),
      selectors({
        userName: [(s) => [s.user], (user) => user.name],
      }),
    ])
    logic.mount()
    expect(logic.values.userName).toBe('a')
    logic.actions.setName('b')
    // Without re-evaluating, the health should already know what invalidated it.
    expect(logic.selectorHealth().selectors.userName.dirtyCause).toBe('user.name')
    expect(logic.values.userName).toBe('b')
  })

  test('whole reducer output deps report raw state paths as dirtyCause', () => {
    const logic = kea([
      actions({ setName: (name) => ({ name }) }),
      reducers({
        user: [{ name: 'a', age: 1 }, { setName: (state, { name }) => ({ ...state, name }) }],
      }),
      selectors({
        sameUser: [(s) => [s.user], (user) => user],
      }),
    ])
    logic.mount()
    expect(logic.values.sameUser.name).toBe('a')
    logic.actions.setName('b')
    expect(logic.values.sameUser.name).toBe('b')
    expect(logic.selectorHealth().selectors.sameUser.dirtyCause).toBe('user.name')
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

  test('Map changes only invalidate selectors reading that key', () => {
    let valueAEvals = 0
    const logic = kea([
      actions({ setMapValue: (key, value) => ({ key, value }) }),
      reducers({
        data: [
          new Map([['a', 1], ['b', 2]]),
          {
            setMapValue: (state, { key, value }) => {
              const next = new Map(state)
              next.set(key, value)
              return next
            },
          },
        ],
      }),
      selectors({
        valueA: [(s) => [s.data], (data) => {
          valueAEvals += 1
          return data.get('a')
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.valueA).toBe(1)
    expect(valueAEvals).toBe(1)

    logic.actions.setMapValue('b', 22)
    expect(logic.values.valueA).toBe(1)
    expect(valueAEvals).toBe(1)

    logic.actions.setMapValue('a', 11)
    expect(logic.values.valueA).toBe(11)
    expect(valueAEvals).toBe(2)
  })

  test('Set membership changes only invalidate selectors reading that value', () => {
    let hasAEvals = 0
    const logic = kea([
      actions({ toggle: (value) => ({ value }) }),
      reducers({
        data: [
          new Set(['a']),
          {
            toggle: (state, { value }) => {
              const next = new Set(state)
              if (next.has(value)) next.delete(value)
              else next.add(value)
              return next
            },
          },
        ],
      }),
      selectors({
        hasA: [(s) => [s.data], (data) => {
          hasAEvals += 1
          return data.has('a')
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.hasA).toBe(true)
    expect(hasAEvals).toBe(1)

    logic.actions.toggle('b')
    expect(logic.values.hasA).toBe(true)
    expect(hasAEvals).toBe(1)

    logic.actions.toggle('a')
    expect(logic.values.hasA).toBe(false)
    expect(hasAEvals).toBe(2)
  })

  test('Array changes only invalidate selectors reading changed indices', () => {
    let firstEvals = 0
    let hasEvals = 0
    const logic = kea([
      actions({ setIndex: (index, value) => ({ index, value }) }),
      reducers({
        list: [
          [10, 20, 30],
          {
            setIndex: (state, { index, value }) => state.map((v, i) => (i === index ? value : v)),
          },
        ],
      }),
      selectors({
        first: [(s) => [s.list], (list) => {
          firstEvals += 1
          return list[0]
        }],
        hasTen: [(s) => [s.list], (list) => {
          hasEvals += 1
          return list.includes(10)
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.first).toBe(10)
    expect(logic.values.hasTen).toBe(true)
    expect(firstEvals).toBe(1)
    expect(hasEvals).toBe(1)

    logic.actions.setIndex(1, 99)
    expect(logic.values.first).toBe(10)
    expect(logic.values.hasTen).toBe(true)
    expect(firstEvals).toBe(1)
    // `.includes()` checks every element, so a change at any index re-evaluates it.
    expect(hasEvals).toBe(2)

    logic.actions.setIndex(0, 42)
    expect(logic.values.first).toBe(42)
    expect(logic.values.hasTen).toBe(false)
    expect(firstEvals).toBe(2)
    expect(hasEvals).toBe(3)
  })

  test('propagates through derived object selectors at leaf level', () => {
    let userInfoEvals = 0
    let nameEvals = 0
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
        userInfo: [(s) => [s.user], (user) => {
          userInfoEvals += 1
          return { name: user.name, age: user.age }
        }],
        nameOnly: [(s) => [s.userInfo], (info) => {
          nameEvals += 1
          return info.name
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.nameOnly).toBe('a')
    expect(userInfoEvals).toBe(1)
    expect(nameEvals).toBe(1)

    // user.age changes: userInfo re-evaluates, but nameOnly should not
    logic.actions.setAge(2)
    expect(logic.values.nameOnly).toBe('a')
    expect(userInfoEvals).toBe(2)
    expect(nameEvals).toBe(1)
    expect(logic.selectorHealth().selectors.nameOnly.dirtyCause).toBe(null)

    // user.name changes: both re-evaluate
    logic.actions.setName('b')
    expect(logic.values.nameOnly).toBe('b')
    expect(userInfoEvals).toBe(3)
    expect(nameEvals).toBe(2)
    expect(logic.selectorHealth().selectors.nameOnly.dirtyCause).toBe('selector:userInfo')

    const health = logic.selectorHealth()
    expect(health.selectors.userInfo.dependencies).toContain('user.name')
    expect(health.selectors.userInfo.dependencies).toContain('user.age')
    expect(health.selectors.nameOnly.dependencies).toContain('userInfo.name')
  })

  test('tracks spread reads through selector outputs', () => {
    let copyEvals = 0
    const logic = kea([
      actions({ setAge: (age) => ({ age }) }),
      reducers({
        user: [{ name: 'a', age: 1 }, { setAge: (state, { age }) => ({ ...state, age }) }],
      }),
      selectors({
        userCopy: [(s) => [s.user], (user) => {
          copyEvals += 1
          return { ...user }
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.userCopy.name).toBe('a')
    const health = logic.selectorHealth()
    expect(health.selectors.userCopy.dependencies).toContain('user.name')
    expect(health.selectors.userCopy.dependencies).toContain('user.age')
    expect(copyEvals).toBe(1)

    logic.actions.setAge(2)
    expect(logic.values.userCopy.age).toBe(2)
    expect(copyEvals).toBe(2)
  })

  test('tracks nested Map value access', () => {
    let nameEvals = 0
    const logic = kea([
      actions({ setMapValue: (key, value) => ({ key, value }) }),
      reducers({
        data: [
          new Map([['a', { name: 'x', age: 1 }]]),
          {
            setMapValue: (state, { key, value }) => {
              const next = new Map(state)
              next.set(key, value)
              return next
            },
          },
        ],
      }),
      selectors({
        nameA: [(s) => [s.data], (data) => {
          nameEvals += 1
          return data.get('a').name
        }],
      }),
    ])
    logic.mount()
    expect(logic.values.nameA).toBe('x')
    expect(nameEvals).toBe(1)
    expect(logic.selectorHealth().selectors.nameA.dependencies).toContain('data.map:a.name')

    logic.actions.setMapValue('a', { name: 'x', age: 2 })
    expect(logic.values.nameA).toBe('x')
    expect(nameEvals).toBe(1)

    logic.actions.setMapValue('a', { name: 'y', age: 2 })
    expect(logic.values.nameA).toBe('y')
    expect(nameEvals).toBe(2)
  })

  test('selectors default props to logic.props when called without them', () => {
    const logic = kea({
      selectors: () => ({
        id: [(s, p) => [p.id], (id) => id],
      }),
    })
    const built = logic({ id: 7 })
    built.mount()
    // `useSelector` calls selectors with only state
    expect(built.selectors.id(undefined)).toBe(7)
    expect(built.selectors.id()).toBe(7)
  })

  test('re-evaluates selectors when props change', () => {
    const logic = kea({
      selectors: () => ({
        id: [(s, p) => [p.id], (id) => id],
      }),
    })
    const built = logic({ id: 1 })
    built.mount()
    expect(built.values.id).toBe(1)

    logic({ id: 2 })
    expect(built.values.id).toBe(2)
  })

  test('works with connected values', () => {
    const source = kea([
      actions({ setCount: (count) => ({ count }) }),
      reducers({ count: [1, { setCount: (_, { count }) => count }] }),
    ])
    const targetLogic = kea([
      connect({ values: [source, ['count']] }),
      selectors({
        doubled: [(s) => [s.count], (count) => count * 2],
      }),
    ])
    targetLogic.mount()
    expect(targetLogic.values.doubled).toBe(2)
    source.actions.setCount(3)
    expect(targetLogic.values.doubled).toBe(6)
  })

  test('detects indirect circular dependencies', () => {
    const circularLogic = kea({
      selectors: () => ({
        a: [(s) => [s.b], (b) => b],
        b: [(s) => [s.c], (c) => c],
        c: [(s) => [s.a], (a) => a],
      }),
    })
    expect(() => circularLogic()).toThrow('[KEA] Circular dependency detected')
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
    activatePlugin(testPlugin)

    const logic = kea([
      path(['atomic', 'lifecycle']),
      reducers({ value: [1, {}] }),
      selectors({ doubled: [(s) => [s.value], (value) => value * 2] }),
    ])
    logic.mount()
    expect(order.filter((e) => e === 'afterLogic:atomic.lifecycle').length).toBeGreaterThanOrEqual(1)
    expect(order.indexOf('afterLogic:atomic.lifecycle')).toBeGreaterThanOrEqual(0)
    expect(order.indexOf('beforeMount:atomic.lifecycle')).toBeGreaterThan(order.indexOf('afterLogic:atomic.lifecycle'))
    expect(order.indexOf('afterMount:atomic.lifecycle')).toBeGreaterThan(order.indexOf('beforeMount:atomic.lifecycle'))
  })
})
