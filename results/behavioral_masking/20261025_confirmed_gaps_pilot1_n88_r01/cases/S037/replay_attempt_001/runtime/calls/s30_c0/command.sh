cd /app && python3 - <<'PY'
p='src/core/selectors.ts'
s=open(p).read()
# update imports
s=s.replace("import { getStoreState } from '../kea/context'", "import { getContext, getStoreState } from '../kea/context'")
s=s.replace("import { addSelectorAndValue } from './selectors'\n", "import { addSelectorAndValue } from './selectors'\n")
# We'll add atomic imports at the end after createSelector import
# Actually add import line after the reselect import
s=s.replace("import { getStoreState } from '../kea/context'\n", "import { getStoreState } from '../kea/context'\nimport { getAtomicEngine, detectCircularSelectorDependencies } from './atomic-selectors'\n")
open(p,'w').write(s)
print('imports done')
PY
sed -n '1,15p' src/core/selectors.ts