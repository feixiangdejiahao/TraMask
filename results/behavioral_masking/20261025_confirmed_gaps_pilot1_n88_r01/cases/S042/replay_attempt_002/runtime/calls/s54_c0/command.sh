cd /app && python3 - <<'PY'
p='packages/core/src/world/types.ts'
s=open(p).read()
s=s.replace("import type { Relation, RelationPair } from '../relation/types';", "import type { Relation, RelationPair } from '../relation/types';\nimport type { RelationTracker } from '../relation/tracking';")
s=s.replace("    changedMasks: Map<number, number[][]>;", "    changedMasks: Map<number, number[][]>;\n    /** Per-modifier pair-level tracking state */\n    relationTrackers: Map<number, RelationTracker>;")
open(p,'w').write(s)
print('world types updated')
PY
grep -n "relationTrackers" packages/core/src/world/types.ts