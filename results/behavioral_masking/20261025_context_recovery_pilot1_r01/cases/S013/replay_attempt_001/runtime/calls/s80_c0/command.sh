cd /app && cat > /tmp/edge4.js <<'EOF'
const { createContainer, asFunction, asValue } = require('/app/lib/awilix.js')
async function main() {
  const c = createContainer()
  const order = []
  c.register({
    b: asFunction(() => ({})).singleton().initializer(async () => { order.push('b') }),
    x: asFunction(({ b }) => ({ b })).transient(),
    a: asFunction(({ x }) => ({ x })).singleton().initializer(async () => { order.push('a') }),
  })
  const r = await c.initialize()
  console.log('order:', order)
  console.log('levels:', r.metrics.b.level, r.metrics.a.level)
}
main().catch(e => { console.error(e); process.exit(1) })
EOF
node /tmp/edge4.js