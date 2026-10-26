cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
s=s.replace("import { kea, resetContext, getContext, actions, reducers, selectors, path, useValues, activatePlugin } from '../../src'", "import { kea, resetContext, getContext, actions, reducers, selectors, path, useValues, activatePlugin, connect } from '../../src'")
s=s.replace("    const { connect } = require('../../src')\n    const targetLogic = kea([\n", "    const targetLogic = kea([\n")
open(p,'w').write(s)
print('cleaned import')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -8