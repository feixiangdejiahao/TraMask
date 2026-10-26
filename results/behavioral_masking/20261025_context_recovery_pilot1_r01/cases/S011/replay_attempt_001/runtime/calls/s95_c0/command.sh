cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
addition = '''
  it('multiple scopes each initialize their own inherited scoped instances', async () => {
    const container = createContainer()
    container.register({
      db: asFunction((): any => ({}))
        .scoped()
        .initializer(async (instance: any) => {
          instance.ready = true
          return instance
        }),
    })

    const scopeA = container.createScope()
    const scopeB = container.createScope()
    await scopeA.initialize()
    expect(scopeA.resolve('db').ready).toBe(true)

    let error: any
    try {
      scopeB.resolve('db')
    } catch (err) {
      error = err
    }
    expect(error).toBeInstanceOf(AwilixNotInitializedError)

    await scopeB.initialize()
    expect(scopeB.resolve('db').ready).toBe(true)
    expect(scopeA.resolve('db')).not.toBe(scopeB.resolve('db'))
  })
'''
idx = s.rstrip().rfind('})')
s = s[:idx] + addition + '\n' + s[idx:]
open(p,'w').write(s)
print('added')
PYEOF
npx prettier --write src/__tests__/initialize.test.ts >/dev/null 2>&1
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -25