cd /app && cat > /tmp/repro3.js <<'EOF'
const { asClass } = require('/app/lib/awilix.js')
class DatabasePool {
  async connect() { this.connected = true }
}
const r = asClass(DatabasePool).singleton().initializer(async (instance) => {
  console.log('INIT RUNNING')
  await instance.connect()
  return instance
})
console.log('has initializer prop:', typeof r.initializer)
console.log('keys:', Object.keys(r))
console.log('initializer fn source:', String(r.initializer))
console.log('resolve.dependencies:', r.resolve && r.resolve.dependencies)
EOF
node /tmp/repro3.js