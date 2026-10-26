cd /app && cat > /tmp/edge3.js <<'EOF'
const { createContainer, asFunction } = require('/app/lib/awilix.js')
async function main() {
  const c = createContainer()
  let init = 0
  c.register({ s: asFunction(() => ({})).singleton().initializer(async () => { init++ }).disposer(() => { console.log('disposed') }) })
  await c.initialize()
  console.log('init count', init)
  await c.dispose()
  try { c.resolve('s'); console.log('ERROR no throw') } catch (e) { console.log('after dispose:', e.name, e.message.includes('not initialized')) }
  await c.initialize()
  console.log('init count after re-init', init)
  console.log('resolved after re-init:', c.resolve('s'))
}
main().catch(e => { console.error(e); process.exit(1) })
EOF
node /tmp/edge3.js