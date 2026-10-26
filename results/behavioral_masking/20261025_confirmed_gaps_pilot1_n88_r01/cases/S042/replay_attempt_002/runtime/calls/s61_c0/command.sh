cd /app && python3 - <<'PY'
p='packages/core/src/entity/types.ts'
s=open(p).read()
s=s.replace("    changed: (trait: Trait) => void;", "    changed: (trait: Trait | RelationPair) => void;")
open(p,'w').write(s)
print('entity type updated')
PY
grep -n "changed" packages/core/src/entity/types.ts