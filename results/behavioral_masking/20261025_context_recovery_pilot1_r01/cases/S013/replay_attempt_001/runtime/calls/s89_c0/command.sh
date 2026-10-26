cd /app && cat >> src/__tests__/container.initialize.test.ts <<'EOF'

  it('keeps the original instance when the initializer returns undefined', async () => {
    const container = createContainer()
    container.register({
      svc: asFunction(() => ({ ready: false }))
        .singleton()
        .initializer(async (instance) => {
          instance.ready = true
        }),
    })

    await container.initialize()
    const svc = container.resolve<{ ready: boolean }>('svc')
    expect(svc.ready).toBe(true)
  })
EOF
cd /app && npx jest src/__tests__/container.initialize.test.ts 2>&1 | tail -12