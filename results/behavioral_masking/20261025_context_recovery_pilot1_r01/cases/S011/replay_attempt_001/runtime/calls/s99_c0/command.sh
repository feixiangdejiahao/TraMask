cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
addition = '''
  it('supports initializer passed through resolver options', async () => {
    const container = createContainer()
    container.register({
      a: asFunction(
        (): any => ({ ready: false }),
        {
          initializer: async (instance: any) => {
            instance.ready = true
            return instance
          },
        },
      ).singleton(),
    })

    await container.initialize()
    expect(container.resolve('a').ready).toBe(true)
  })
'''
idx = s.rstrip().rfind('})')
s = s[:idx] + addition + '\n' + s[idx:]
open(p,'w').write(s)
print('added')
PYEOF
npx prettier --write src/__tests__/initialize.test.ts src/resolvers.ts >/dev/null 2>&1
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -30