cd /app && cat >> src/__tests__/container.initialize.test.ts <<'EOF'

  it('initializes a scoped container independently of its parent', async () => {
    const container = createContainer()
    let parentInitCalls = 0
    container.register({
      parentSvc: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          parentInitCalls++
        }),
    })

    const scope = container.createScope()
    let scopeInitCalls = 0
    scope.register({
      localSvc: asFunction(() => ({}))
        .scoped()
        .initializer(async () => {
          scopeInitCalls++
        }),
    })

    await scope.initialize()
    expect(parentInitCalls).toBe(0)
    expect(scopeInitCalls).toBe(1)
    expect(scope.resolve('localSvc')).toBeDefined()
  })
EOF
cd /app && npx jest src/__tests__/container.initialize.test.ts 2>&1 | tail -20