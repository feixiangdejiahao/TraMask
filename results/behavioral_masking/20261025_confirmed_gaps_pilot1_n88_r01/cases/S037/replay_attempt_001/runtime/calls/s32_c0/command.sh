cd /app && python3 - <<'PY'
p='src/core/selectors.ts'
s=open(p).read()
s=s.replace("import { getContext, getStoreState } from '../kea/context'\n", "import { getContext, getStoreState } from '../kea/context'\nimport { getAtomicEngine, detectCircularSelectorDependencies } from './atomic-selectors'\n")
open(p,'w').write(s)
print('done')
PY
sed -n '1,6p' src/core/selectors.ts