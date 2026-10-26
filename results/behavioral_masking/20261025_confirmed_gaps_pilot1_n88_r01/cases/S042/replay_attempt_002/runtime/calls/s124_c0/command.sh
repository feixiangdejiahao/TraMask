cd /app && rm -f packages/core/tests/zz-or.test.ts && python3 - <<'PY'
p='packages/core/tests/pair-tracking-modifiers.test.ts'
s=open(p).read()
s=s.replace("const seen = new Map<number, number>();", "const seen = new Map<number, number | undefined>();")
open(p,'w').write(s)
print('test fixed')
PY
cd packages/core && pnpm exec tsc --noEmit -p tsconfig.json 2>&1 | head -40