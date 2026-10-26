cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
lines=open(p).read().split('\n')
for i,l in enumerate(lines):
    if l == '\t#scheduleDebouncedFetch(search: string): void {':
        lines.insert(i+1, '\t\tthis.#clearMinDurationTimer();')
        lines.insert(i+2, '\t\tthis.#clearRetryTimer();')
        break
open(p,'w').write('\n'.join(lines))
print("done")
PY
sed -n '381,390p' packages/core/src/prompts/autocomplete.ts