cd /app && cat > /tmp/check_extra.mts <<'EOF'
import { createWorld, createAdded, createRemoved, createChanged, relation, Or } from '/app/packages/core/src/index.ts';
const world = createWorld(); world.init();
const Likes = relation({ store: { amount: 0 } });
const a = world.spawn(); const b = world.spawn();
const e1 = world.spawn(Likes(a)); const e2 = world.spawn(Likes(b));
const Removed = createRemoved(); const Changed = createChanged();
e1.remove(Likes(a));
e2.remove(Likes(b));
const qr = world.query(Or(Removed(Likes(a)), Removed(Likes(b))));
console.log('removed or', qr.includes(e1), qr.includes(e2));
const e3 = world.spawn(Likes(a));
e3.set(Likes(a), { amount: 5 });
const qc = world.query(Or(Changed(Likes(a)), Changed(Likes(b))));
console.log('changed or', qc.includes(e3), qc.length);
EOF
pnpm exec tsx /tmp/check_extra.mts