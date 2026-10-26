cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
s=s.replace("asFunction(({ b }: any) => ({ b }))", "asFunction(({ b }: any): any => ({ b }))")
s=s.replace("asFunction(({ a }: any) => ({ a }))", "asFunction(({ a }: any): any => ({ a }))")
s=s.replace("asFunction((db: any) => ({ db }))", "asFunction((db: any): any => ({ db }))")
s=s.replace("asFunction(({ db }: any) => ({ db }))", "asFunction(({ db }: any): any => ({ db }))")
open(p,'w').write(s)
print('patched')
PYEOF
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -120