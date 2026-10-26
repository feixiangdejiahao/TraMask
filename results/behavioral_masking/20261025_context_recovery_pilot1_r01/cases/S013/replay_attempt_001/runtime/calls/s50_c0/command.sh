cd /app && cat > /tmp/repro2.js <<'EOF'
const { createContainer, asClass } = require('/app/lib/awilix.js')

class DatabasePool {
  constructor() { this.connected = false }
  async connect() { console.log('connect called, this.connected=', this.connected); this.connected = true; console.log('after connect, this.connected=', this.connected) }
}
let captured
const container = createContainer()
container.register({
  database: asClass(DatabasePool).singleton().initializer(async (instance) => {
    captured = instance
    console.log('initializer instance connected?', instance.connected)
    await instance.connect()
    return instance
  }),
})
async function main() {
  await container.initialize()
  const db = container.resolve('database')
  console.log('db === captured?', db === captured)
  console.log('captured.connected', captured && captured.connected)
  console.log('db.connected', db && db.connected)
  console.log('cache entries', Array.from(container.cache.entries()))
}
main().catch(e => { console.error(e); process.exit(1) })
EOF
node /tmp/repro2.js