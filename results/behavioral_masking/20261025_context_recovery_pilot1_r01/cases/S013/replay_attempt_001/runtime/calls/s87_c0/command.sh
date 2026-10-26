cd /app && cat > /tmp/classic.js <<'EOF'
const { createContainer, asFunction, asValue, InjectionMode } = require('/app/lib/awilix.js')
async function main() {
  const c = createContainer({ injectionMode: InjectionMode.CLASSIC })
  c.register({ x: asValue(5), s: asFunction((x) => ({ x })).singleton().initializer(async (o) => ({ ...o, init: true })) })
  await c.initialize()
  console.log(c.resolve('s'))
}
main().catch(e => { console.error(e); process.exit(1) })
EOF
node /tmp/classic.js