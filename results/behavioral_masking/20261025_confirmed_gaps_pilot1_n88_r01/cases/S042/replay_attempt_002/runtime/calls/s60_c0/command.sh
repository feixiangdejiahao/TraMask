cd /app && python3 - <<'PY'
p='packages/core/src/entity/entity-methods-patch.ts'
s=open(p).read()
s=s.replace("import { setChanged } from '../query/modifiers/changed';", "import { setChanged, setPairChanged } from '../query/modifiers/changed';")
open(p,'w').write(s)
print('import updated')
PY
grep -n "setPairChanged\|setChanged" packages/core/src/entity/entity-methods-patch.ts