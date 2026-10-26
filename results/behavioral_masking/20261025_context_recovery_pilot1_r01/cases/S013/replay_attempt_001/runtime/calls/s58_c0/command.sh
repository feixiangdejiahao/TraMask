cd /app && python3 - <<'PY'
p='src/__tests__/container.initialize.test.ts'
s=open(p).read()

old = """    container.register({
      a: asFunction(() => ({})).singleton().initializer(async () => {}),
      b: asFunction(({ a }: any) => ({ a }))
        .singleton()
        .initializer(async () => {}),
      c: asFunction(({ b }: any) => ({ b }))
        .singleton()
        .initializer(async () => {
          throw fail
        }),
    })
    container.register({
      aDisposer: asFunction(() => ({})).singleton(),
      bDisposer: asFunction(() => ({})).singleton(),
    })

    ;(container.getRegistration('a') as any).dispose = () => {
      disposed.push('a')
    }
    ;(container.getRegistration('b') as any).dispose = () => {
      disposed.push('b')
    }

    await expect(container.initialize()).rejects.toThrow(
      AwilixInitializationError,
    )
    expect(disposed).toEqual(['b', 'a'])"""
new = """    container.register({
      a: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {})
        .disposer(() => {
          disposed.push('a')
        }),
      b: asFunction(({ a }: any) => ({ a }))
        .singleton()
        .initializer(async () => {})
        .disposer(() => {
          disposed.push('b')
        }),
      c: asFunction(({ b }: any) => ({ b }))
        .singleton()
        .initializer(async () => {
          throw fail
        }),
    })

    await expect(container.initialize()).rejects.toThrow(
      AwilixInitializationError,
    )
    expect(disposed).toEqual(['b', 'a'])"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("cleaned")
PY
cd /app && npx jest src/__tests__/container.initialize.test.ts 2>&1 | tail -60