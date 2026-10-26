cd /app && python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
s=s.replace("    logic.mount()\n    expect(logic.values.first).toBe(10)\n    expect(logic.values.hasTen).toBe(true)\n    expect(firstEvals).toBe(1)\n    expect(hasEvals).toBe(1)", "    logic.mount()\n    expect(logic.values.first).toBe(10)\n    console.log('DBG after first', firstEvals, hasEvals)\n    expect(logic.values.hasTen).toBe(true)\n    console.log('DBG after hasTen', firstEvals, hasEvals)\n    expect(firstEvals).toBe(1)\n    expect(hasEvals).toBe(1)")
open(p,'w').write(s)
PY
NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js -t "Array changes" 2>&1 | grep -E "DBG|Expected|Received"
# revert debug prints
python3 - <<'PY'
p='test/jest/atomic-selectors.js'
s=open(p).read()
s=s.replace("    console.log('DBG after first', firstEvals, hasEvals)\n", "")
s=s.replace("    console.log('DBG after hasTen', firstEvals, hasEvals)\n", "")
open(p,'w').write(s)
PY