cd /app && python3 - <<'PY'
p='packages/prompts/src/autocomplete.ts'
lines=open(p).read().split('\n')
for i,l in enumerate(lines):
    if '...`${title}${styleText(barStyle, S_BAR)}`.split' in l:
        # insert search line after this line
        search_line = "\t\t\t\t\t\t`${styleText(barStyle, S_BAR)}  ${styleText('dim', 'Search:')} ${searchText}${matches}`,"
        lines.insert(i+1, search_line)
        break
open(p,'w').write('\n'.join(lines))
PY
nl -ba packages/prompts/src/autocomplete.ts | sed -n '445,458p'
cd /app && npx tsc --noEmit --project tsconfig.json 2>&1 | grep -v 'npm warn' | head -30