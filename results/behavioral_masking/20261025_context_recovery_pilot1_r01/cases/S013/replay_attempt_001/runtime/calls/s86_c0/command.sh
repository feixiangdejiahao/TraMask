cd /app && cat > /tmp/classdep.js <<'EOF'
const { createContainer, asClass, asValue } = require('/app/lib/awilix.js')
class Dep {}
class Svc { constructor(dep) { this.dep = dep } }
async function main() {
  const c = createContainer()
  c.register({ dep: asClass(Dep).singleton(), svc: asClass(Svc).singleton().initializer(async (x) => ({ ...x, ok: true })) })
  const r = await c.initialize()
  console.log('levels:', r.metrics.dep !== undefined ? 'dep-in-metrics' : 'dep-not-in-metrics', r.metrics.svc.level)
  console.log('svc.dep instanceof Dep:', c.resolve('svc').dep instanceof Dep, 'ok:', c.resolve('svc').ok)
}
main().catch(e => { console.error(e); process.exit(1) })
EOF
node /tmp/classdep.js