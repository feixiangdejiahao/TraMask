cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
addition = '''
  it('disposer errors during rollback do not override the original error', async () => {
    const boom = new Error('init boom')
    const container = createContainer()
    container.register({
      a: asFunction((): any => ({}))
        .singleton()
        .disposer(() => {
          throw new Error('dispose boom')
        })
        .initializer(async () => ({})),
      b: asFunction((): any => ({}))
        .singleton()
        .initializer(async () => {
          throw boom
        }),
    })

    let error: any
    try {
      await container.initialize()
    } catch (err) {
      error = err
    }
    expect(error.message).toContain('init boom')
    expect(error.cause).toBe(boom)
  })

  it('scope initializing a parent singleton marks it initialized for the root too', async () => {
    let runs = 0
    const container = createContainer()
    container.register({
      db: asFunction((): any => ({}))
        .singleton()
        .initializer(async (instance: any) => {
          runs++
          return instance
        }),
    })

    const scope = container.createScope()
    await scope.initialize()
    expect(runs).toBe(1)
    expect(container.resolve('db')).toBeDefined()

    // Root initialize should not reinitialize the already-initialized singleton.
    const result = await container.initialize()
    expect(runs).toBe(1)
    expect(Object.keys(result.metrics)).toEqual([])
  })
'''
idx = s.rstrip().rfind('})')
s = s[:idx] + addition + '\n' + s[idx:]
open(p,'w').write(s)
print('added')
PYEOF
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -45