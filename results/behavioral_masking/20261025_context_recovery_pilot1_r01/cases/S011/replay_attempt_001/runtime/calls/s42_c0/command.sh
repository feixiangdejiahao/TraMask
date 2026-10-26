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
        console.log('initializer got instance ctor:', instance?.constructor?.name)
        replacement.connected = true
        return replacement
      }),
  })
  await container.initialize()
  const cached = (container.cache.get('database') as any)
  console.log('cached keys:', cached && Object.keys(cached))
  console.log('cached.value keys:', cached && Object.keys(cached.value))
  console.log('cached.resolver === reg:', cached.resolver === (container.registrations as any).database)
})
EOF
npx jest src/__tests__/debug.test.ts --no-coverage 2>&1 | tail -50