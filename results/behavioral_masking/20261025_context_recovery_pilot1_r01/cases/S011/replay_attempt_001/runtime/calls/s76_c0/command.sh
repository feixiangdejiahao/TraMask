cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
addition = '''
  it('supports symbol registration names', async () => {
    const db = Symbol('db')
    const container = createContainer()
    container.register({
      [db]: asFunction((): any => ({ ready: false }))
        .singleton()
        .initializer(async (instance: any) => {
          instance.ready = true
          return instance
        }),
    })

    const result = await container.initialize()
    expect(container.resolve(db).ready).toBe(true)
    expect(result.metrics[db.toString()].level).toBe(0)
  })
'''
idx = s.rstrip().rfind('})')
s = s[:idx] + addition + '\n' + s[idx:]
open(p,'w').write(s)
print('added')
PYEOF
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -20