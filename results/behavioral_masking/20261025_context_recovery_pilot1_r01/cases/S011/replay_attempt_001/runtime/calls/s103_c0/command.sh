cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
addition = '''
  it('can initialize again after dispose', async () => {
    let runs = 0
    const container = createContainer()
    container.register({
      a: asFunction((): any => ({}))
        .singleton()
        .initializer(async (instance: any) => {
          runs++
          return instance
        }),
    })

    await container.initialize()
    expect(runs).toBe(1)
    await container.dispose()

    // Resolving after dispose throws again because initialization state was reset.
    let error: any
    try {
      container.resolve('a')
    } catch (err) {
      error = err
    }
    expect(error).toBeInstanceOf(AwilixNotInitializedError)

    await container.initialize()
    expect(runs).toBe(2)
  })
'''
idx = s.rstrip().rfind('})')
s = s[:idx] + addition + '\n' + s[idx:]
open(p,'w').write(s)
print('added')
PYEOF
npx prettier --write src/__tests__/initialize.test.ts >/dev/null 2>&1
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -30