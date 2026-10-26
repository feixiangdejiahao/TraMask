cd /app && cat > src/__tests__/debug.test.ts <<'EOF'
import { createContainer, asClass } from '../awilix'

class DatabasePool {
  connected = false
  async connect() { this.connected = true }
}

it('debug', async () => {
  const container = createContainer()
  container.register({
    database: asClass(DatabasePool).singleton(),
  })
  const resolver = (container.registrations as any).database
  const result = resolver.resolve(container)
  console.log('direct resolve ctor:', result?.constructor?.name)
  console.log('is instance:', result instanceof DatabasePool)
})
EOF
npx jest src/__tests__/debug.test.ts --no-coverage 2>&1 | tail -30