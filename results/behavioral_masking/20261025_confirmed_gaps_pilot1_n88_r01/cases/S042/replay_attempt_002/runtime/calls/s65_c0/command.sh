cd /app && python3 - <<'PY'
p='packages/core/src/query/query.ts'
s=open(p).read()
s=s.replace("""import { hasRelationPair } from '../relation/relation';
import type { Relation } from '../relation/types';
import { isRelationPair } from '../relation/utils/is-relation';""", """import { hasRelationPair } from '../relation/relation';
import { hasPairEvent } from '../relation/tracking';
import type { Relation, RelationPair } from '../relation/types';
import { isRelationPair } from '../relation/utils/is-relation';""")
open(p,'w').write(s)
print('imports updated')
PY
sed -n '1,20p' packages/core/src/query/query.ts