cd /app && cat >> src/__tests__/container.initialize.test.ts <<'EOF'

  it('allows scoped services to depend on parent-initialized singletons', async () => {
    const container = createContainer()
    const parentValue = { ready: true }
    container.register({
      parentSvc: asFunction(() => ({}))
        .singleton()
        .initializer(async () => parentValue),
    })
    await container.initialize()

    const scope = container.createScope()
    scope.register({
      child: asFunction(({ parentSvc }: any) => ({ parentSvc }))
        .scoped()
        .initializer(async (instance) => ({ ...instance, ok: true })),
    })

    await scope.initialize()
    const child = scope.resolve<{ parentSvc: any; ok: boolean }>('child')
    expect(child.parentSvc).toBe(parentValue)
    expect(child.ok).toBe(true)
  })
EOF
cd /app && npx jest src/__tests__/container.initialize.test.ts 2>&1 | tail -8