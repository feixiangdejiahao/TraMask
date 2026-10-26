cd /app && python3 - <<'PY'
p='src/kea/context.ts'
s=open(p).read()
# add atomicEngines to context object
s=s.replace("    wrapperContexts: new WeakMap(),\n    buildHeap: [],", "    wrapperContexts: new WeakMap(),\n    buildHeap: [],\n    atomicEngines: new Map(),")
# add atomicSelectors default option
s=s.replace("      disableAsyncActions: false,\n      defaultPath:", "      disableAsyncActions: false,\n      atomicSelectors: false,\n      defaultPath:")
open(p,'w').write(s)
print('done')
PY
grep -n "atomic" src/kea/context.ts