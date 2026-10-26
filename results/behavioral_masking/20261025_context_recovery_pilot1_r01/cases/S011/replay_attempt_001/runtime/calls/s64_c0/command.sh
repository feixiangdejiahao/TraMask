cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
addition = '''
  it('scope initializes inherited scoped registrations independently', async () => {
    let rootRuns = 0
    let scopeRuns = 0
    const container = createContainer()
    container.register({
      db: asFunction((): any => ({}))
        .scoped()
        .initializer(async (instance: any) => {
          rootRuns++
          instance.scope = 'root'
          return instance
        }),
    })

    await container.initialize()
    expect(rootRuns).toBe(1)
    expect(container.resolve('db').scope).toBe('root')

    const scope = container.createScope()
    const result = await scope.initialize()
    expect(scopeRuns).toBe(0) // the root-owned scoped initializer only ran at root
    // Wait: this test needs a scope-local scoped registration to prove scope init works.
    // The inherited scoped registration's initializer should be run for the scope too.
  })

  it('scope initializes an inherited scoped registration for its own instance', async () => {
    const runs: string[] = []
    const container = createContainer()
    container.register({
      db: asFunction((): any => ({}))
        .scoped()
        .initializer(async (instance: any) => {
          runs.push('root')
          instance.ready = true
          return instance
        }),
    })

    await container.initialize()
    const rootDb = container.resolve('db')
    expect(runs).toEqual(['root'])

    const scope = container.createScope()
    const result = await scope.initialize()
    expect(runs).toEqual(['root', 'root']) // same initializer runs again for the scope instance
    const scopeDb = scope.resolve('db')
    expect(scopeDb).not.toBe(rootDb)
    expect(scopeDb.ready).toBe(true)
    expect(result.metrics.db.level).toBe(0)
  })

  it('scope does not reinitialize parent singletons', async () => {
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
    await container.initialize()

    const scope = container.createScope()
    const result = await scope.initialize()
    expect(runs).toBe(1)
    expect(Object.keys(result.metrics)).toEqual([])
  })

  it('resolving an inherited scoped registration from an uninitialized scope throws', async () => {
    const container = createContainer()
    container.register({
      db: asFunction((): any => ({}))
        .scoped()
        .initializer(async (instance: any) => instance),
    })
    await container.initialize()

    const scope = container.createScope()
    let error: any
    try {
      scope.resolve('db')
    } catch (err) {
      error = err
    }
    expect(error).toBeInstanceOf(AwilixNotInitializedError)
  })
'''
# insert before last two closing braces
idx = s.rstrip().rfind('})')
s = s[:idx] + addition + '\n' + s[idx:]
open(p,'w').write(s)
print('tests added')
PYEOF
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -60