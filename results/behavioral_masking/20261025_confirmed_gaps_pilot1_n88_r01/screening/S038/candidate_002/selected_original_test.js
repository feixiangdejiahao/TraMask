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