cd /app && cat > /tmp/order.js <<'EOF'
const { createContainer, asFunction, INITIALIZER } = require('/app/lib/awilix.js')
async function main() {
  const c = createContainer()
  const disposed = []
  c.register({
    s: asFunction(() => ({})).singleton().disposer(() => disposed.push('x')).initializer(async (x) => ({ ...x, init: true })),
    t: asFunction(() => ({})).singleton().initializer(async (x) => ({ ...x, init: true })).disposer(() => disposed.push('y')),
  })
  await c.initialize()
  console.log('s resolved:', c.resolve('s'))
  console.log('t resolved:', c.resolve('t'))
  await c.dispose()
  console.log('disposed:', disposed.sort())
}
main().catch(e => { console.error(e); process.exit(1) })
EOF
node /tmp/order.js