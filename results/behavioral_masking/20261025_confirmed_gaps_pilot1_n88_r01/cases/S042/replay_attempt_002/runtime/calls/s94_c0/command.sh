cd /app && python3 - <<'PY'
# query/types.ts
p='packages/core/src/query/types.ts'
s=open(p).read()
s=s.replace("        target?: Entity,\n        pairCanceled?: boolean\n    ) => boolean;", "        target?: Entity,\n        pairCanceledByTracker?: Map<number, boolean>\n    ) => boolean;")
open(p,'w').write(s)

# query.ts
p='packages/core/src/query/query.ts'
s=open(p).read()
s=s.replace("""            target?: Entity,
            pairCanceled = false
        ) => checkQueryTracking(world, query, entity, eventType, generationId, bitflag, target, pairCanceled),""", """            target?: Entity,
            pairCanceledByTracker?: Map<number, boolean>
        ) => checkQueryTracking(world, query, entity, eventType, generationId, bitflag, target, pairCanceledByTracker),""")
open(p,'w').write(s)

# check-query-tracking.ts
p='packages/core/src/query/utils/check-query-tracking.ts'
s=open(p).read()
s=s.replace("    eventBitflag: number,\n    target?: Entity,\n    pairCanceled = false\n): boolean {", "    eventBitflag: number,\n    target?: Entity,\n    pairCanceledByTracker?: Map<number, boolean>\n): boolean {")
s=s.replace("""            // A cancelled opposite pair event must not record a new tracker bit.
            if (pairCanceled) {""", """            // A cancelled opposite pair event must not record a new tracker bit.
            const pairCanceled = pairCanceledByTracker?.get(group.id) ?? false;
            if (pairCanceled) {""")
open(p,'w').write(s)

# check-query-tracking-with-relations.ts
p='packages/core/src/query/utils/check-query-tracking-with-relations.ts'
s=open(p).read()
s=s.replace("    eventBitflag: number,\n    target?: Entity,\n    pairCanceled = false\n): boolean {", "    eventBitflag: number,\n    target?: Entity,\n    pairCanceledByTracker?: Map<number, boolean>\n): boolean {")
s=s.replace("checkQueryTracking(world, query, entity, eventType, eventGenerationId, eventBitflag, target, pairCanceled)", "checkQueryTracking(world, query, entity, eventType, eventGenerationId, eventBitflag, target, pairCanceledByTracker)")
open(p,'w').write(s)
print('all updated')
PY
grep -n "pairCanceled" packages/core/src/query/query.ts packages/core/src/query/utils/check-query-tracking.ts packages/core/src/query/types.ts