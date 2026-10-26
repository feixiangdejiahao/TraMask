cd /app && python3 - <<'PY'
# fix indentation just in case
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()
s=s.replace("\t\tthis.searchTooShort = false;\n\t\t\tthis.loadError = undefined;\n\t\t\tthis.retryCount = 0;", "\t\tthis.searchTooShort = false;\n\t\tthis.loadError = undefined;\n\t\tthis.retryCount = 0;")
open(p,'w').write(s)
print("done")
PY
sed -n '332,340p' packages/core/src/prompts/autocomplete.ts | cat -A | head -10 && npx tsc --noEmit 2>&1 | grep -v "npm warn" | head