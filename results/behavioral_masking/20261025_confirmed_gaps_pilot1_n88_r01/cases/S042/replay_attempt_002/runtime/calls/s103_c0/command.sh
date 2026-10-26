cd /app && python3 - <<'PY'
# Clean tracking.ts logs
p='packages/core/src/relation/tracking.ts'
s=open(p).read()
s=s.replace("""        console.log('UPDATE', eventType, 'map', canceledByTracker ? [...canceledByTracker.entries()] : 'none', 'query gids', query.trackingGroups.map(g=>g.id));
""", "")
open(p,'w').write(s)

# Clean check-query-tracking.ts debug log
p='packages/core/src/query/utils/check-query-tracking.ts'
s=open(p).read()
s=s.replace("""        if (affected && group.pairs && group.pairs.length > 0) {
            const pc = pairCanceledByTracker?.get(group.id) ?? false;
            console.log('CQ pair', 'ev', eventType, 'groupType', groupType, 'groupLogic', groupLogic, 'gid', group.id, 'canceled', pc, 'target', target);
        }
""", "")
open(p,'w').write(s)
print('cleaned')
PY
grep -n "console.log" packages/core/src/relation/tracking.ts packages/core/src/query/utils/check-query-tracking.ts