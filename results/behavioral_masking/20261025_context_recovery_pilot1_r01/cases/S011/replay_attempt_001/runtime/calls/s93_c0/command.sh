cd /app && npm run build >/dev/null 2>&1 && cat > /tmp/spec_check.js <<'EOF'
const {
  createContainer,
  asClass,
  asFunction,
  AwilixInitializationError,
  AwilixNotInitializedError,
  AwilixResolutionError,
} = require('./lib/awilix')

class DatabasePool {
  async connect() { this.connected = true }
}

async function main() {
  // Basic API
  const container = createContainer()
  container.register({
    database: asClass(DatabasePool)
      .singleton()
      .initializer(async (instance) => {
        await instance.connect()
        return instance
      }),
  })
  const result = await container.initialize({ concurrency: 5 })
  console.log('totalDuration:', typeof result.totalDuration)
  console.log('metrics.database:', result.metrics.database)
  console.log('connected:', container.resolve('database').connected)

  // Uninitialized resolve
  const c2 = createContainer()
  c2.register({ a: asFunction(() => ({})).singleton().initializer(async () => ({})) })
  try { c2.resolve('a') } catch (e) {
    console.log('not-init:', e instanceof AwilixNotInitializedError, /not initialized/.test(e.message))
  }

  // Failure
  const c3 = createContainer()
  const boom = new Error('boom')
  c3.register({ a: asFunction(() => ({})).singleton().initializer(async () => { throw boom }) })
  try { await c3.initialize() } catch (e) {
    console.log('init-fail:', e instanceof AwilixInitializationError, /a/.test(e.message), /boom/.test(e.message), e.cause === boom)
  }
  try { await c3.initialize() } catch (e) {
    console.log('re-init:', /previously failed|Cannot re-initialize/.test(e.message))
  }

  // Circular
  const c4 = createContainer()
  c4.register({
    a: asFunction(({ b }) => ({ b })).singleton().initializer(async () => ({})),
    b: asFunction(({ a }) => ({ a })).singleton().initializer(async () => ({})),
  })
  try { await c4.initialize() } catch (e) {
    console.log('circular:', e instanceof AwilixResolutionError)
  }
  c4.register({ b: asFunction(() => ({})).singleton().initializer(async () => ({})) })
  await c4.initialize()
  console.log('retry after circular: ok')
}

main().catch((e) => { console.error('FAIL', e); process.exit(1) })
EOF
node /tmp/spec_check.js