  test('selectorHealth is available on logics without selectors', () => {
    const logic = kea({})
    const unmount = logic.mount()
    expect(typeof logic.selectorHealth).toBe('function')
    expect(logic.selectorHealth()).toEqual({ selectors: {}, topologicalOrder: [] })
    unmount()
  })
