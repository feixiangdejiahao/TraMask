cd /app && python3 - <<'PY'
p='packages/core/src/world/world.ts'
s=open(p).read()
s=s.replace("            changedMasks: new Map(),\n            worldEntity: null!,", "            changedMasks: new Map(),\n            relationTrackers: new Map(),\n            worldEntity: null!,")
s=s.replace("""            ctx.trackingSnapshots.clear();
            ctx.dirtyMasks.clear();
            ctx.changedMasks.clear();
            ctx.trackedTraits.clear();
""", """            ctx.trackingSnapshots.clear();
            ctx.dirtyMasks.clear();
            ctx.changedMasks.clear();
            ctx.relationTrackers.clear();
            ctx.trackedTraits.clear();

            // Re-initialize tracking masks for long-lived modifier factories.
            const resetCursor = getTrackingCursor();
            for (let i = 0; i < resetCursor; i++) {
                setTrackingMasks(world, i);
            }
""")
open(p,'w').write(s)
print('world updated')
PY
sed -n '55,80p' packages/core/src/world/world.ts && sed -n '165,190p' packages/core/src/world/world.ts