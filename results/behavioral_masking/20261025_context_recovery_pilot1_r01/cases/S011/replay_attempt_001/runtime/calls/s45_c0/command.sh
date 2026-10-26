cd /app && python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()
s=s.replace("""        case Lifetime.SINGLETON:
          // Singleton lifetime means cache at all times, regardless of scope.
          cached = rootContainer.cache.get(name)
          if (!cached) {
            // if we are running in strict mode, perform singleton resolution using the root
            // container only.
            resolved = resolver.resolve(
              options.strict ? rootContainer : container,
            )
            rootContainer.cache.set(name, { resolver, value: resolved })""",
"""        case Lifetime.SINGLETON:
          // Singleton lifetime means cache at all times, regardless of scope.
          cached = rootContainer.cache.get(name)
          if (!cached) {
            // if we are running in strict mode, perform singleton resolution using the root
            // container only.
            resolved = resolver.resolve(
              options.strict ? rootContainer : container,
            )
            if (resolved === resolver) {
              console.log('DEBUG resolve returned resolver for', name)
            }
            rootContainer.cache.set(name, { resolver, value: resolved })""")
open(p,'w').write(s)
print('done')
PYEOF
cat > src/__tests__/debug.test.ts <<'EOF'
import { createContainer, asClass } from '../awilix'

class DatabasePool { connected = false }

it('debug', async () => {
  const container = createContainer()
  const replacement = new DatabasePool()
  container.register({
    database: asClass(DatabasePool)
      .singleton()
      .initializer(async (instance) => {
        replacement.connected = true
        return replacement
      }),
  })
  await container.initialize()
  const resolved = container.resolve('database')
  console.log('resolved is replacement:', resolved === replacement)
})
EOF
npx jest src/__tests__/debug.test.ts --no-coverage 2>&1 | tail -30