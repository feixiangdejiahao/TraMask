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
