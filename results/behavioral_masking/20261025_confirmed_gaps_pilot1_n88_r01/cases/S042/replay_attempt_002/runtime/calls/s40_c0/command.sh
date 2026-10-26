cd /app && cp packages/core/src/trait/trait.ts /tmp/trait.bak && python3 - <<'PY'
p='packages/core/src/trait/trait.ts'
s=open(p).read()
s=s.replace("    ctx.entityTraits.get(entity)!.delete(trait);\n}", "    const ets = ctx.entityTraits.get(entity);\n    if (!ets) console.log('MISSING MAP at 533 entity', entity, 'id', getEntityId(entity), 'map has', ctx.entityTraits.has(entity), 'keys', [...ctx.entityTraits.keys()]);\n    ets?.delete(trait);\n}")
open(p,'w').write(s)
PY
cd packages/core && pnpm exec vitest run tests/query-modifiers.test.ts -t "Removed on a relation" 2>&1 | tail -40; cd /app && cp /tmp/trait.bak packages/core/src/trait/trait.ts