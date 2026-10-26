cd /app && python3 - <<'PY'
p='packages/core/src/prompts/autocomplete.ts'
lines=open(p).read().split('\n')
for i,l in enumerate(lines):
    if l.strip() == "this.searchTooShort = false;":
        # insert after it if not already followed by loadError reset
        if i+1 < len(lines) and 'this.loadError = undefined;' in lines[i+1]:
            print("already present")
            break
        lines.insert(i+1, "\t\t\tthis.loadError = undefined;")
        lines.insert(i+2, "\t\t\tthis.retryCount = 0;")
        print("inserted at line", i+1)
        break
open(p,'w').write('\n'.join(lines))
PY
sed -n '330,342p' packages/core/src/prompts/autocomplete.ts