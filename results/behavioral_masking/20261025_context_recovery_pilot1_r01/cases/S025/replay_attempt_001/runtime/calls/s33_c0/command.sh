cd /app && python3 - <<'PY'
p='packages/prompts/src/autocomplete.ts'
s=open(p).read()

old = """\t\t\t\t\t\t// No matches message
\t\t\t\t\t\tconst noResults =
\t\t\t\t\t\t\tthis.filteredOptions.length === 0 && userInput
\t\t\t\t\t\t\t\t? [`${guidePrefix}${styleText('yellow', 'No matches found')}`]
\t\t\t\t\t\t\t\t: [];

\t\t\t\t\t\tconst validationError =
\t\t\t\t\t\t\tthis.state === 'error' ? [`${guidePrefix}${styleText('yellow', this.error)}`] : [];

\t\t\t\t\t\tif (hasGuide) {
\t\t\t\t\t\t\theadings.push(`${guidePrefix.trimEnd()}`);
\t\t\t\t\t\t}
\t\t\t\t\t\theadings.push(
\t\t\t\t\t\t\t`${guidePrefix}${styleText('dim', 'Search:')}${searchText}${matches}`,
\t\t\t\t\t\t\t...noResults,
\t\t\t\t\t\t\t...validationError
\t\t\t\t\t\t);"""
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
assert old in s, "single pattern not found"
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY