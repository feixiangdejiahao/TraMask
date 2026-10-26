cd /app && python3 - <<'PY'
p='packages/core/src/query/utils/check-query-tracking.ts'
s=open(p).read()
old="""export function checkQueryTracking(
    world: World,
    query: QueryInstance,
    entity: Entity,
    eventType: EventType,
    eventGenerationId: number,
    eventBitflag: number,
    target?: Entity
): boolean {"""
new="""export function checkQueryTracking(
    world: World,
    query: QueryInstance,
    entity: Entity,
    eventType: EventType,
    eventGenerationId: number,
    eventBitflag: number,
    target?: Entity,
    pairCanceled = false
): boolean {"""
assert old in s
s=s.replace(old,new)
old2="""        if (affected) {
            // Cross-event invalidation:
            // - Remove event invalidates Added/Changed tracking
            // - Add event invalidates Removed/Changed tracking
            if (eventType === 'remove') {
                if (groupType === 'add' || groupType === 'change') return false;
            } else if (eventType === 'add') {
                if (groupType === 'remove' || groupType === 'change') return false;
            }

            // Update tracker if event type matches group type
            if (groupType === eventType) {"""
new2="""        if (affected) {
            // Cross-event invalidation:
            // - Remove event invalidates Added/Changed tracking
            // - Add event invalidates Removed/Changed tracking
            if (eventType === 'remove') {
                if (groupType === 'add' || groupType === 'change') return false;
            } else if (eventType === 'add') {
                if (groupType === 'remove' || groupType === 'change') return false;
            }

            // A cancelled opposite pair event must not record a new tracker bit.
            if (pairCanceled) {
                // Fall through to satisfaction check: the group remains unsatisfied.
            } else if (groupType === eventType) {"""
assert old2 in s
s=s.replace(old2,new2)
open(p,'w').write(s)
print('check-query-tracking updated')
PY
sed -n '60,140p' packages/core/src/query/utils/check-query-tracking.ts