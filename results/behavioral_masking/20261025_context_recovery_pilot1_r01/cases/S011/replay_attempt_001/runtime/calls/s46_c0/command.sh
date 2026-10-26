cd /app && python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()
s=s.replace("""      value = resolve(name)
      if (resolver.initializer) {
        value = await resolver.initializer(value)
      }""",
"""      value = resolve(name)
      console.log('DEBUG initializeService', name.toString(), 'resolved ctor:', value?.constructor?.name)
      if (resolver.initializer) {
        value = await resolver.initializer(value)
        console.log('DEBUG initializeService after initializer ctor:', value?.constructor?.name)
      }""")
open(p,'w').write(s)
print('done')
PYEOF
npx jest src/__tests__/debug.test.ts --no-coverage 2>&1 | tail -40