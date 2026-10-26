cd /app && python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()
old = """    const rolledUp = rollUpRegistrations()
    const entries: Array<InitializationEntry> = Object.keys(rolledUp)
      .filter((name) => getInitializer(rolledUp[name]))
      .map((name) => ({
        name,
        resolver: rolledUp[name] as Resolver<any>,
      }))
      .filter(({ name, resolver }) => !isInitialized(name, resolver))"""
new = """    const rolledUp = rollUpRegistrations()
    const entries: Array<InitializationEntry> = Reflect.ownKeys(rolledUp)
      .filter((name) => getInitializer(rolledUp[name as any]))
      .map((name) => ({
        name,
        resolver: rolledUp[name as any] as Resolver<any>,
      }))
      .filter(({ name, resolver }) => !isInitialized(name, resolver))"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('done')
PYEOF
npx tsc -p tsconfig.json --noEmit --pretty false 2>&1 | grep -v "examples/typescript" | head