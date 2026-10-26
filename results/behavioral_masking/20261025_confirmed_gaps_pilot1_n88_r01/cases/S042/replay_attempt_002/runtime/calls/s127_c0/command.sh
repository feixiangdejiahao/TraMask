cd /app && python3 - <<'PY'
p='packages/core/src/query/utils/tracking-cursor.ts'
s=open(p).read()
old="""    // Initialize pair-level tracking state.
    const tracker = createRelationTracker();
    populateRelationTrackerSnapshot(world, tracker);
    ctx.relationTrackers.set(id, tracker);"""
new="""    // Initialize pair-level tracking state for actual tracking modifiers.
    // IDs 0-2 are reserved for internal masks and never used by pair queries.
    if (id >= 3) {
        const tracker = createRelationTracker();
        populateRelationTrackerSnapshot(world, tracker);
        ctx.relationTrackers.set(id, tracker);
    }"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('tracking-cursor updated')
PY
cd packages/core && pnpm exec vitest run tests/pair-tracking-modifiers.test.ts 2>&1 | tail -30