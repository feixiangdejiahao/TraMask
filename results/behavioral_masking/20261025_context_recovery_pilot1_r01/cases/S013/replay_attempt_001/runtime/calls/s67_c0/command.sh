cd /app && cat > /tmp/edge2.js <<'EOF'
const { createContainer, asFunction } = require('/app/lib/awilix.js')
async function main() {
  const c = createContainer()
  const replacement = { replaced: true }
  c.register({
    a: asFunction(() => ({ orig: true })).singleton().initializer(async () => replacement),
    b: asFunction(({ a }) => ({ a })).singleton().initializer(async (x) => ({ ...x, ok: true })),
  })
  const r = await c.initialize()
  console.log('levels:', r.metrics.a.level, r.metrics.b.level)
  const b = c.resolve('b')
  console.log('b.a === replacement?', b.a === replacement, b.ok)
}
main().catch(e => { console.error(e); process.exit(1) })
EOF
node /tmp/edge2.js