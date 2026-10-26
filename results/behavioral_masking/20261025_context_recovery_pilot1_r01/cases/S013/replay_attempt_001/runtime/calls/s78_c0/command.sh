cd /app && cat > /tmp/loadmod.js <<'EOF'
const { createContainer, asFunction, RESOLVER, INITIALIZER } = require('/app/lib/awilix.js')
const fn = function (deps) { return {} }
fn[RESOLVER] = { lifetime: 'SINGLETON' }
const c = createContainer()
c.register({ s: asFunction(fn, { initializer: async (x) => ({ ...x, init: true }) }) })
const r = c.getRegistration('s')
console.log('has INITIALIZER:', typeof r[INITIALIZER])
console.log('fluid initializer is method:', typeof r.initializer)
c.initialize().then(res => {
  console.log('metrics:', Object.keys(res.metrics))
  console.log('resolved:', c.resolve('s'))
})
EOF
node /tmp/loadmod.js