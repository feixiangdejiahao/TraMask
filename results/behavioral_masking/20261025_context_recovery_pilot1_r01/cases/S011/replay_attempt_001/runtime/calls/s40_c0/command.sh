cd /app && cat > src/__tests__/debug.test.ts <<'EOF'
import { createContainer, asClass } from '../awilix'

class DatabasePool {
  connected = false
  async connect() { this.connected = true }
}

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
  const r = await container.initialize()
  console.log('cache keys:', Array.from(container.cache.keys()))
  console.log('cache value ctor:', (container.cache.get('database') as any)?.value?.constructor?.name)
  console.log('registrations database ctor:', (container.registrations as any).database?.constructor?.name)
  const resolved = container.resolve('database')
  console.log('resolved === cache value:', resolved === (container.cache.get('database') as any)?.value)
  console.log('resolved === replacement:', resolved === replacement)
  console.log('resolved === resolver:', resolved === (container.registrations as any).database)
})
EOF
npx jest src/__tests__/debug.test.ts --no-coverage 2>&1 | tail -40