cd /app && cat > /tmp/test_esm.mts <<'EOF'
import { createWorld, createAdded, trait } from '/app/packages/core/src/index.ts';
const world = createWorld();
world.init();
const Added = createAdded();
world.reset();
const e = world.spawn();
const T = trait();
e.add(T);
try {
  const q = world.query(Added(T));
  console.log('ok', q.length);
} catch (err) {
  console.log('ERR', err);
}
EOF
pnpm exec tsx /tmp/test_esm.mts