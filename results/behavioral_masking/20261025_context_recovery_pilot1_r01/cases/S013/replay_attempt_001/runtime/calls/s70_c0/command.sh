cd /app && cat >> src/__tests__/container.initialize.test.ts <<'EOF'

describe('container.initialize edge cases', () => {
  it('returns the same in-flight promise for concurrent calls', async () => {
    const container = createContainer()
    let resolveInit!: () => void
    const gate = new Promise<void>((r) => (resolveInit = r))
    container.register({
      svc: asFunction(() => ({})).singleton().initializer(async () => {
        await gate
      }),
    })

    const first = container.initialize()
    const second = container.initialize()
    expect(second).toBe(first)
    resolveInit()
    await first
    await second
  })

  it('can be retried after a graph-build cycle is fixed', async () => {
    const container = createContainer()
    container.register({
      a: asFunction(({ b }: any) => ({ b }))
        .singleton()
        .initializer(async () => {}),
      b: asFunction(({ a }: any) => ({ a }))
        .singleton()
        .initializer(async () => {}),
    })

    await expect(container.initialize()).rejects.toThrow(AwilixResolutionError)

    // Break the cycle.
    container.register({
      b: asFunction(() => ({})).singleton().initializer(async () => {}),
    })

    await expect(container.initialize()).resolves.toMatchObject({
      totalDuration: expect.any(Number),
    })
  })

  it('detects cycles through non-initialized registrations', async () => {
    const container = createContainer()
    container.register({
      a: asFunction(({ b }: any) => ({ b }))
        .singleton()
        .initializer(async () => {}),
      b: asFunction(() => ({})).transient(),
      c: asFunction(({ a }: any) => ({ a })).transient(),
    })
    // a -> b, c -> a: no cycle yet.
    container.register({
      b: asFunction(({ c }: any) => ({ c })).transient(),
    })
    // Now a -> b -> c -> a is a cycle.
    await expect(container.initialize()).rejects.toThrow(AwilixResolutionError)
  })
})
EOF
cd /app && npx jest src/__tests__/container.initialize.test.ts 2>&1 | tail -40