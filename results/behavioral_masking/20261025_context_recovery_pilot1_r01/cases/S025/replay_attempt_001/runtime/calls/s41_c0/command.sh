cd /app && python3 - <<'PY'
p='packages/prompts/src/autocomplete.ts'
lines=open(p).read().split('\n')
# locate noResults block in multiselect (after line with '// No results message' and containing S_BAR)
start=None
for i,l in enumerate(lines):
    if l.strip() == '// No results message' and i>300:
        start=i
        break
print("start", start)
assert start is not None
new_block = [
"\t\t\t\t\t// Search too short / loading / no results messages",
"\t\t\t\t\tconst tooShort =",
"\t\t\t\t\t\tthis.searchTooShort && opts.minSearchLength",
"\t\t\t\t\t\t\t? [`${styleText(barStyle, S_BAR)}  ${styleText('yellow', `Type at least ${opts.minSearchLength} characters`)}`]",
"\t\t\t\t\t\t\t: [];",
"\t\t\t\t\tconst loading = this.loading",
"\t\t\t\t\t\t? [`${styleText(barStyle, S_BAR)}  ${styleText('dim', opts.loadingMessage ?? 'Loading...')}`]",
"\t\t\t\t\t\t: [];",
"\t\t\t\t\tconst noResults =",
"\t\t\t\t\t\tthis.filteredOptions.length === 0 &&",
"\t\t\t\t\t\tuserInput &&",
"\t\t\t\t\t\t!this.loading &&",
"\t\t\t\t\t\t!this.searchTooShort",
"\t\t\t\t\t\t\t? [`${styleText(barStyle, S_BAR)}  ${styleText('yellow', opts.noResultsMessage ?? 'No matches found')}`]",
"\t\t\t\t\t\t\t: [];",
]
# Replace from start to start+5 (the noResults block, lines start..start+4 with blank at start+5)
lines[start:start+5] = new_block
# Now update headerLines to include tooShort/loading
for i,l in enumerate(lines):
    if l.strip() == "...noResults," and i>300:
        lines[i-1:i+1] = [
            "\t\t\t\t\t\t...tooShort,",
            "\t\t\t\t\t\t...loading,",
            "\t\t\t\t\t\t...noResults,",
        ]
        break
open(p,'w').write('\n'.join(lines))
print("done")
PY
nl -ba packages/prompts/src/autocomplete.ts | sed -n '420,448p'