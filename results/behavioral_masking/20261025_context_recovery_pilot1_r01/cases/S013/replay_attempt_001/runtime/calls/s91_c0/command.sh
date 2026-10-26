cd /app && cat >> src/__tests__/container.initialize.test.ts <<'EOF'

  it('initializes parent non-singleton registrations on a scoped container', async () => {
    const container = createContainer()
    let parentInitCalls = 0
    container.register({
      parentT: asFunction(() => ({}))
        .transient()
        .initializer(async () => {
          parentInitCalls++
        }),
    })

    const scope = container.createScope()
    let scopeInitCalls = 0
    scope.register({
      child: asFunction(({ parentT }: any) => ({ parentT }))
        .scoped()
        .initializer(async () => {
          scopeInitCalls++
        }),
    })

    await scope.initialize()
    expect(parentInitCalls).toBe(1)
    expect(scopeInitCalls).toBe(1)
    expect(scope.resolve('child')).toBeDefined()
  })
EOF
cd /app && npx jest src/__tests__/container.initialize.test.ts 2>&1 | tail -30