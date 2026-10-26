cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
old = """  it('rolls back initialized services in reverse order on failure', async () => {
    const order: string[] = []
    const container = createContainer()
    container.register({
      a: asFunction((): any => ({}))
        .singleton()
        .disposer(() => {
          order.push('a')
        })
        .initializer(async () => ({})),
      b: asFunction((): any => ({}))
        .singleton()
        .disposer(() => {
          order.push('b')
        })
        .initializer(async () => ({})),
      c: asFunction((): any => ({}))
        .singleton()
        .initializer(async () => {
          throw new Error('c failed')
        }),
    })

    await expect(container.initialize()).rejects.toBeInstanceOf(
      AwilixInitializationError,
    )
    expect(order).toEqual(['b', 'a'])
  })"""
new = """  it('rolls back initialized services in reverse order on failure', async () => {
    const order: string[] = []
    const container = createContainer()
    container.register({
      a: asFunction((): any => ({}))
        .singleton()
        .disposer(() => {
          order.push('a')
        })
        .initializer(async () => ({})),
      b: asFunction(({ a }: any): any => ({ a }))
        .singleton()
        .disposer(() => {
          order.push('b')
        })
        .initializer(async () => ({})),
      c: asFunction(({ b }: any): any => ({ b }))
        .singleton()
        .initializer(async () => {
          throw new Error('c failed')
        }),
    })

    await expect(container.initialize()).rejects.toBeInstanceOf(
      AwilixInitializationError,
    )
    expect(order).toEqual(['b', 'a'])
  })"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('updated')
PYEOF
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -20