cd /app && for f in added removed; do python3 - <<PY
p='packages/core/src/query/modifiers/$f.ts'
s=open(p).read()
if "import { \$internal } from '../../common';" not in s:
    s="import { \$internal } from '../../common';\n"+s
open(p,'w').write(s)
PY
done
head -5 packages/core/src/query/modifiers/added.ts && head -5 packages/core/src/query/modifiers/removed.ts