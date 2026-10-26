cd /app && python3 - <<'PY'
p='packages/core/src/relation/tracking.ts'
s=open(p).read()
# remove the $internal import added for logging
s=s.replace("import { $internal } from '../common';\n", "")
# remove console logs
s=s.replace("""        console.log('PAIR-UPDATE', eventType, 'canceled', canceled, 'query hash', query.hash, 'groups', query.trackingGroups.map(g=>({type:g.type, logic:g.logic, pairs:g.pairs?.map(p=>p[$internal].target)})));
""", "")
s=s.replace("""        console.log('  match', match, 'entity', entity);
""", "")
open(p,'w').write(s)
print('logs removed')
PY
grep -n "console.log\|\$internal" packages/core/src/relation/tracking.ts | head