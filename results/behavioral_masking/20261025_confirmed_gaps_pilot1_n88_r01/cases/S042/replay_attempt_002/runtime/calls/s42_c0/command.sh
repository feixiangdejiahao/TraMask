cd /app && cat > tests_tmp_esm.ts <<'EOF'
import { createWorld, createAdded, trait } from '/app/packages/core/src/index.ts';
const world = createWorld();
world.init();
const Added = createAdded();
world.reset();
const e = world.spawn();
e.add(trait());
try {
  const q = world.query(Added(trait()));
  console.log('ok', q.length);
} catch (err) {
  console.log('ERR', err);
}
EOF
pnpm exec tsx tests_tmp_esm.ts; rm -f tests_tmp_esm.ts