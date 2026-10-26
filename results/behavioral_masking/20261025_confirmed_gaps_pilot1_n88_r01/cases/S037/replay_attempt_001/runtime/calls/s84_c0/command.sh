cd /app && python3 - <<'PY'
p='src/core/selectors.ts'
s=open(p).read()
s=s.replace("}\n\n\nfunction atomicSelectorsBuilder", "}\n\nfunction atomicSelectorsBuilder")
open(p,'w').write(s)
print('cleaned')
PY
npx tsc --noEmit 2>&1 | head