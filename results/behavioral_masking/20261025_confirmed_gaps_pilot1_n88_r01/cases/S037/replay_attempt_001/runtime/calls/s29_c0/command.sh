cd /app && python3 - <<'PY'
p='src/kea/context.ts'
s=open(p).read()
s=s.replace("      detachStrategy: 'dispatch',\n      defaultPath: ['kea', 'logic'],", "      detachStrategy: 'dispatch',\n      defaultPath: ['kea', 'logic'],\n      atomicSelectors: false,")
open(p,'w').write(s)
print('done')
PY
grep -n "atomicSelectors" src/kea/context.ts