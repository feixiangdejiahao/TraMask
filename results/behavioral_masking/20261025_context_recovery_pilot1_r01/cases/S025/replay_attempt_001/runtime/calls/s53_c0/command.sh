cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
s=open(p, encoding='utf-8').read()
s=s.replace('\u258a', '\\u2588')
open(p,'w',encoding='utf-8').write(s)
PY
grep -n '258' packages/core/src/prompts/autocomplete.ts && cd packages/core && pnpm build 2>&1 | tail -3