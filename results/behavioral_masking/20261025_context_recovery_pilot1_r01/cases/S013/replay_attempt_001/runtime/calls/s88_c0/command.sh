cd /app && cat > /tmp/symbol.js <<'EOF'
const { createContainer, asFunction } = require('/app/lib/awilix.js')
const S = Symbol('svc')
async function main() {
  const c = createContainer()
  c.register({ [S]: asFunction(() => ({})).singleton().initializer(async () => ({ ok: true })) })
  const r = await c.initialize()
  console.log('metrics keys:', Object.getOwnPropertySymbols(r.metrics).length)
  console.log('resolved:', c.resolve(S))
}
main().catch(e => { console.error(e); process.exit(1) })
EOF
node /tmp/symbol.js