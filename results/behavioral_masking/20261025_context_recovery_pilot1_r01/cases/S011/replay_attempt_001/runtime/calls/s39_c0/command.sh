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
  console.log('metrics:', r.metrics)
  const resolved = container.resolve('database')
  console.log('resolved constructor:', resolved?.constructor?.name)
  console.log('is replacement:', resolved === replacement)
})
EOF
npx jest src/__tests__/debug.test.ts --no-coverage 2>&1 | tail -40