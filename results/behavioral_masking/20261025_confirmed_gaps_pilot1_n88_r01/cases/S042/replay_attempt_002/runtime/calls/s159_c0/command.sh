cd /app && cat > /tmp/check_module_scope.mts <<'EOF'
import { createAdded, createWorld, relation } from '/app/packages/core/src/index.ts';
const Added = createAdded(); // before world
const world = createWorld();
world.init();
const Likes = relation();
const p = world.spawn();
const e = world.spawn();
e.add(Likes(p));
const q = world.query(Added(Likes(p)));
console.log('module scope ok', q.includes(e));
EOF
pnpm exec tsx /tmp/check_module_scope.mts