cd /app && cat > /tmp/repro.js <<'EOF'
const { createContainer, asClass, asFunction } = require('./lib/awilix.js')

class DatabasePool {
  constructor() { this.connected = false }
  async connect() { this.connected = true }
  async disconnect() { this.connected = false }
}

async function main() {
  const container = createContainer()
  container.register({
    database: asClass(DatabasePool)
      .singleton()
      .initializer(async (instance) => {
        await instance.connect()
        return instance
      }),
  })
  // should throw NotInitialized
  try {
    container.resolve('database')
    console.log('ERROR: should have thrown NotInitialized')
  } catch (e) {
    console.log('resolve before init threw:', e.name, e.message)
  }
  const result = await container.initialize({ concurrency: 5 })
  console.log('totalDuration', result.totalDuration)
  console.log('metrics', result.metrics.database)
  const db = container.resolve('database')
  console.log('connected', db.connected)
  const result2 = await container.initialize()
  console.log('idempotent same metrics?', result2 === result)
}

main().catch((e) => { console.error('FAIL', e); process.exit(1) })
EOF
node /tmp/repro.js