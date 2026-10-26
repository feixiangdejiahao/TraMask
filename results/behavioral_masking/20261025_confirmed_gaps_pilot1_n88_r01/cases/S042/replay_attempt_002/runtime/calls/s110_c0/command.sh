cd /app && python3 - <<'PY'
p='packages/core/src/query/utils/check-query-tracking.ts'
s=open(p).read()
old="""            if (!eventIsPairTrait) {
                // Regular trait event: pair group unaffected.
                affected = false;
            } else {
                const pairTarget = pairCtx.target;
                if (pairTarget !== '*' && target !== pairTarget) {
                    affected = false;
                }
            }
        }
"""
new="""            if (!eventIsPairTrait) {
                // Regular trait event: pair group unaffected.
                affected = false;
            } else if (target === undefined) {
                // Trait-level structural event (first add / last remove). We
                // cross-invalidate pair additions/changes on trait removal but
                // never record a tracker here - pair-level events own trackers.
                affected = true;
            } else {
                const pairTarget = pairCtx.target;
                if (pairTarget !== '*' && target !== pairTarget) {
                    affected = false;
                }
            }
        }
"""
assert old in s
s=s.replace(old,new)
# In affected block, handle target-undefined pair groups
old2="""        if (affected) {
            // Cross-event invalidation:
            // - Remove event invalidates Added/Changed tracking
            // - Add event invalidates Removed/Changed tracking
            if (eventType === 'remove') {
                if (groupType === 'add' || groupType === 'change') return false;
            } else if (eventType === 'add') {
                if (groupType === 'remove' || groupType === 'change') return false;
            }

            // A cancelled opposite pair event must not record a new tracker bit.
            const pairCanceled = pairCanceledByTracker?.get(group.id) ?? false;
            if (pairCanceled) {
                // Fall through to satisfaction check: the group remains unsatisfied.
            } else if (groupType === eventType) {"""
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
            // Trait-level structural events (target undefined) also must not record.
            const pairCanceled = pairCanceledByTracker?.get(group.id) ?? false;
            const traitLevelPairEvent = !!group.pairs && group.pairs.length > 0 && target === undefined;
            if (pairCanceled || traitLevelPairEvent) {
                // Fall through to satisfaction check: the group remains unsatisfied.
            } else if (groupType === eventType) {"""
assert old2 in s
s=s.replace(old2,new2)
open(p,'w').write(s)
print('check-query-tracking updated')
PY
# Remove debug logs
python3 - <<'PY'
p='packages/core/src/relation/tracking.ts'
s=open(p).read()
s=s.replace("""        console.log('UPDATE', eventType, 'map', canceledByTracker ? [...canceledByTracker.entries()] : 'none', 'gids', query.trackingGroups.map(g=>g.id), 'entity', entity);
""", "")
open(p,'w').write(s)
p='packages/core/src/query/utils/check-query-tracking.ts'
s=open(p).read()
s=s.replace("""        if (affected && group.pairs && group.pairs.length > 0) {
            console.log('CQ', 'ev', eventType, 'gt', groupType, 'gid', group.id, 'canceled', pairCanceledByTracker?.get(group.id), 'target', target);
        }
""", "")
open(p,'w').write(s)
PY
rm -f packages/core/tests/zz-debug.test.ts
echo cleaned
grep -n "console.log" packages/core/src/relation/tracking.ts packages/core/src/query/utils/check-query-tracking.ts || true