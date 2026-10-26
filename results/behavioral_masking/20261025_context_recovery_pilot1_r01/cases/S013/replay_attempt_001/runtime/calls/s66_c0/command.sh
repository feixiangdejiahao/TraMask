cd /app && npm run build 2>&1 | tail -3 && cat > /tmp/edge.js <<'EOF'
const { createContainer, asFunction, asValue } = require('/app/lib/awilix.js')

async function main() {
  // transient with initializer
  const c = createContainer()
  let calls = 0
  c.register({ t: asFunction(() => ({ n: ++calls })).initializer(async (x) => ({ ...x, init: true })) })
  await c.initialize()
  const v1 = c.resolve('t')
  console.log('transient resolved value:', v1) // should be {n:1, init:true}

  // parent init then scope resolves parent singleton
  const p = createContainer()
  p.register({ ps: asFunction(() => ({ ok: true })).singleton().initializer(async () => ({ ok: true, init: true })) })
  await p.initialize()
  const scope = p.createScope()
  console.log('scope resolves parent singleton:', scope.resolve('ps'))

  // scope local depends on parent singleton
  const s2 = p.createScope()
  s2.register({ local: asFunction(({ ps }) => ({ ps })).scoped().initializer(async (x) => ({ ...x, localInit: true })) })
  const r = await s2.initialize()
  console.log('scope init metrics:', Object.keys(r.metrics))
  console.log('scope local:', s2.resolve('local'))

  // indirect dependency through non-initializer
  const c2 = createContainer()
  const order = []
  c2.register({
    dep: asValue(1),
    mid: asFunction(({ dep }) => ({ dep })).transient(),
    top: asFunction(({ mid }) => ({ mid })).singleton().initializer(async () => { order.push('top') }),
    root: asFunction(({ dep }) => ({ dep })).singleton().initializer(async () => { order.push('root') }),
  })
  c2.register({ midInit: asFunction(({ mid }) => ({ mid })).singleton().initializer(async () => { order.push('midInit') }) })
  await c2.initialize()
  console.log('indirect order:', order)
}

main().catch(e => { console.error('FAIL', e); process.exit(1) })
EOF
node /tmp/edge.js