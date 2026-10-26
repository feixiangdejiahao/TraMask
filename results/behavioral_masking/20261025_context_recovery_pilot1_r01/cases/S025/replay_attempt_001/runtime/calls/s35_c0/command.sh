cd /app && python3 - <<'PY'
import re
p='packages/prompts/src/autocomplete.ts'
s=open(p).read()

pattern = re.compile(
	r"\t\t\t\t\t\t// No matches message\n"
	r"\t\t\t\t\t\tconst noResults =\n"
	r"\t\t\t\t\t\t\tthis\.filteredOptions\.length === 0 && userInput\n"
	r"\t\t\t\t\t\t\t\t\? \[\$\{guidePrefix\}\$\{styleText\('yellow', 'No matches found'\)\}\]\n"
	r"\t\t\t\t\t\t\t\t: \[\];\n"
	r"\n"
	r"\t\t\t\t\t\tconst validationError =\n"
	r"\t\t\t\t\t\t\tthis\.state === 'error' \? \[\$\{guidePrefix\}\$\{styleText\('yellow', this\.error\)\}\] : \[\];\n"
	r"\n"
	r"\t\t\t\t\t\tif \(hasGuide\) \{\n"
	r"\t\t\t\t\t\t\theadings\.push\(\`\$\{guidePrefix\.trimEnd\(\)\}\`\);\n"
	r"\t\t\t\t\t\t\}\n"
	r"\t\t\t\t\t\theadings\.push\(\n"
	r"\t\t\t\t\t\t\t\`\$\{guidePrefix\}\$\{styleText\('dim', 'Search:')\}\$\{searchText\}\$\{matches\}\`,\n"
	r"\t\t\t\t\t\t\t\.\.\.noResults,\n"
	r"\t\t\t\t\t\t\t\.\.\.validationError\n"
	r"\t\t\t\t\t\t\);"
)

new = """\t\t\t\t\t\t// Search too short / loading / no results messages
\t\t\t\t\t\tconst tooShort =
\t\t\t\t\t\t\tthis.searchTooShort && opts.minSearchLength
\t\t\t\t\t\t\t\t? [`${guidePrefix}${styleText('yellow', `Type at least ${opts.minSearchLength} characters`)}`]
\t\t\t\t\t\t\t\t: [];
\t\t\t\t\t\tconst loading = this.loading
\t\t\t\t\t\t\t? [`${guidePrefix}${styleText('dim', opts.loadingMessage ?? 'Loading...')}`]
\t\t\t\t\t\t\t: [];
\t\t\t\t\t\tconst noResults =
\t\t\t\t\t\t\tthis.filteredOptions.length === 0 &&
\t\t\t\t\t\t\tuserInput &&
\t\t\t\t\t\t\t!this.loading &&
\t\t\t\t\t\t\t!this.searchTooShort
\t\t\t\t\t\t\t\t? [`${guidePrefix}${styleText('yellow', opts.noResultsMessage ?? 'No matches found')}`]
\t\t\t\t\t\t\t\t: [];

\t\t\t\t\t\tconst validationError =
\t\t\t\t\t\t\tthis.state === 'error' ? [`${guidePrefix}${styleText('yellow', this.error)}`] : [];

\t\t\t\t\t\tif (hasGuide) {
\t\t\t\t\t\t\theadings.push(`${guidePrefix.trimEnd()}`);
\t\t\t\t\t\t}
\t\t\t\t\t\theadings.push(
\t\t\t\t\t\t\t`${guidePrefix}${styleText('dim', 'Search:')}${searchText}${matches}`,
\t\t\t\t\t\t\t...tooShort,
\t\t\t\t\t\t\t...loading,
\t\t\t\t\t\t\t...noResults,
\t\t\t\t\t\t\t...validationError
\t\t\t\t\t\t);"""

m = pattern.search(s)
print("match:", bool(m))
if m:
	s = s[:m.start()] + new + s[m.end():]
	open(p,'w').write(s)
PY