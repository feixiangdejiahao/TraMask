cd /app && cat > src/__tests__/debug.test.ts <<'EOF'
import { createContainer, asFunction } from '../awilix'

it('debug', async () => {
  const container = createContainer()
  container.register({
    a: asFunction((): any => ({ x: 1 }))
      .singleton()
      .initializer(async (instance: any) => {
        instance.ready = true
        return instance
      }),
  })
  console.log('resolve fn type:', typeof container.resolve)
  console.log('registrations:', Object.keys(container.registrations))
  console.log('has initializer:', !!(container.registrations as any).a?.initializer)
  console.log('resolved:', container.resolve('a'))
  const r = await container.initialize()
  console.log('metrics:', r.metrics)
  console.log('resolved2:', container.resolve('a'))
})
EOF
npx jest src/__tests__/debug.test.ts --no-coverage 2>&1 | tail -50