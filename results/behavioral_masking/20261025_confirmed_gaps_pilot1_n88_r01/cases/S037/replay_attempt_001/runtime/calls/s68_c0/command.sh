cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
old = """    const target = kea([
      connect,
    ])
    // Use a manual connect since the builder is imported below
    const { connect } = require('../../src')
    const targetLogic = kea([
"""
new = """    const { connect } = require('../../src')
    const targetLogic = kea([
"""
assert old in s
s=s.replace(old,new)
# Also the source logic variable `target` was unused; remove it
s=s.replace("    const targetLogic = kea([", "    const targetLogic = kea([")
open(p,'w').write(s)
print('test fixed')
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -45