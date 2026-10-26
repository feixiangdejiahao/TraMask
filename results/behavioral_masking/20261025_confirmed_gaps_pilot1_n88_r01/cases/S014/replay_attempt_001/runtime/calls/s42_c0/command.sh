cd /app && python3 - <<'PY'
p='packages/prompts/src/autocomplete.ts'
s=open(p).read()

old = '''\t\t\t\t\t// No matches message
\t\t\t\t\tconst noResults =
\t\t\t\t\t\tthis.filteredOptions.length === 0 && userInput
\t\t\t\t\t\t\t? [`${guidePrefix}${styleText('yellow', 'No matches found')}`]
\t\t\t\t\t\t\t: [];

\t\t\t\t\tconst validationError =
\t\t\t\t\t\tthis.state === 'error' ? [`${guidePrefix}${styleText('yellow', this.error)}`] : [];

\t\t\t\t\tif (hasGuide) {
\t\t\t\t\t\theadings.push(`${guidePrefix.trimEnd()}`);
\t\t\t\t\t}
\t\t\t\t\theadings.push(
\t\t\t\t\t\t`${guidePrefix}${styleText('dim', 'Search:')}${searchText}${matches}`,
\t\t\t\t\t\t...noResults,
\t\t\t\t\t\t...validationError
\t\t\t\t\t);'''
new = '''\t\t\t\t\t// Async status messages
\t\t\t\t\tconst minSearchLength = opts.minSearchLength ?? 1;
\t\t\t\t\tconst loading = this.loading
\t\t\t\t\t\t? [`${guidePrefix}${styleText('dim', opts.loadingMessage ?? 'Loading...')}`]
\t\t\t\t\t\t: [];
\t\t\t\t\tconst tooShort = this.searchTooShort
\t\t\t\t\t\t? [`${guidePrefix}${styleText('yellow', `Type at least ${minSearchLength} characters`)}`]
\t\t\t\t\t\t: [];
\t\t\t\t\tconst fetchError = this.loadError
\t\t\t\t\t\t? [`${guidePrefix}${styleText('red', this.loadError)}`]
\t\t\t\t\t\t: [];

\t\t\t\t\t// No matches message
\t\t\t\t\tconst noResults =
\t\t\t\t\t\tthis.filteredOptions.length === 0 &&
\t\t\t\t\t\tuserInput &&
\t\t\t\t\t\t!this.loading &&
\t\t\t\t\t\t!this.searchTooShort &&
\t\t\t\t\t\t!this.loadError
\t\t\t\t\t\t\t? [`${guidePrefix}${styleText('yellow', opts.noResultsMessage ?? 'No matches found')}`]
\t\t\t\t\t\t\t: [];

\t\t\t\t\tconst validationError =
\t\t\t\t\t\tthis.state === 'error' ? [`${guidePrefix}${styleText('yellow', this.error)}`] : [];

\t\t\t\t\tif (hasGuide) {
\t\t\t\t\t\theadings.push(`${guidePrefix.trimEnd()}`);
\t\t\t\t\t}
\t\t\t\t\theadings.push(
\t\t\t\t\t\t`${guidePrefix}${styleText('dim', 'Search:')}${searchText}${matches}`,
\t\t\t\t\t\t...loading,
\t\t\t\t\t\t...tooShort,
\t\t\t\t\t\t...noResults,
\t\t\t\t\t\t...fetchError,
\t\t\t\t\t\t...validationError
\t\t\t\t\t);'''
assert old in s, "noResults block not found"
s=s.replace(old,new)

old = '''\t\t\t\t\t// Render options with selection
\t\t\t\t\tconst displayOptions =
\t\t\t\t\t\tthis.filteredOptions.length === 0
\t\t\t\t\t\t\t? []
\t\t\t\t\t\t\t: limitOptions({'''
new = '''\t\t\t\t\t// Render options with selection
\t\t\t\t\tconst displayOptions =
\t\t\t\t\t\tthis.loading || this.filteredOptions.length === 0
\t\t\t\t\t\t\t? []
\t\t\t\t\t\t\t: limitOptions({'''
assert old in s, "displayOptions block not found"
s=s.replace(old,new)

open(p,'w').write(s)
print("single autocomplete render done")
PY