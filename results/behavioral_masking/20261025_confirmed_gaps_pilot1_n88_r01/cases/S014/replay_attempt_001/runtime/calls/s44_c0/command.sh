cd /app && python3 - <<'PY'
p='packages/prompts/src/autocomplete.ts'
s=open(p).read()

old = '''\t\t\t\t\t// No results message
\t\t\t\t\tconst noResults =
\t\t\t\t\t\tthis.filteredOptions.length === 0 && userInput
\t\t\t\t\t\t\t? [`${styleText(barStyle, S_BAR)}  ${styleText('yellow', 'No matches found')}`]
\t\t\t\t\t\t\t: [];

\t\t\t\t\tconst errorMessage =
\t\t\t\t\t\tthis.state === 'error'
\t\t\t\t\t\t\t? [`${styleText(barStyle, S_BAR)}  ${styleText('yellow', this.error)}`]
\t\t\t\t\t\t\t: [];

\t\t\t\t\t// Calculate header and footer line counts for rowPadding
\t\t\t\t\tconst headerLines = [
\t\t\t\t\t\t...`${title}${styleText(barStyle, S_BAR)}`.split('\\n'),
\t\t\t\t\t\t`${styleText(barStyle, S_BAR)}  ${styleText('dim', 'Search:')} ${searchText}${matches}`,
\t\t\t\t\t\t...noResults,
\t\t\t\t\t\t...errorMessage,
\t\t\t\t\t];'''
new = '''\t\t\t\t\t// Async status messages
\t\t\t\t\tconst minSearchLength = opts.minSearchLength ?? 1;
\t\t\t\t\tconst loading = this.loading
\t\t\t\t\t\t? [`${styleText(barStyle, S_BAR)}  ${styleText('dim', opts.loadingMessage ?? 'Loading...')}`]
\t\t\t\t\t\t: [];
\t\t\t\t\tconst tooShort = this.searchTooShort
\t\t\t\t\t\t? [
\t\t\t\t\t\t\t\t`${styleText(barStyle, S_BAR)}  ${styleText('yellow', `Type at least ${minSearchLength} characters`)}`,
\t\t\t\t\t\t\t]
\t\t\t\t\t\t: [];
\t\t\t\t\tconst fetchError = this.loadError
\t\t\t\t\t\t? [`${styleText(barStyle, S_BAR)}  ${styleText('red', this.loadError)}`]
\t\t\t\t\t\t: [];

\t\t\t\t\t// No results message
\t\t\t\t\tconst noResults =
\t\t\t\t\t\tthis.filteredOptions.length === 0 &&
\t\t\t\t\t\tuserInput &&
\t\t\t\t\t\t!this.loading &&
\t\t\t\t\t\t!this.searchTooShort &&
\t\t\t\t\t\t!this.loadError
\t\t\t\t\t\t\t? [
\t\t\t\t\t\t\t\t\t`${styleText(barStyle, S_BAR)}  ${styleText('yellow', opts.noResultsMessage ?? 'No matches found')}`,
\t\t\t\t\t\t\t\t]
\t\t\t\t\t\t\t: [];

\t\t\t\t\tconst errorMessage =
\t\t\t\t\t\tthis.state === 'error'
\t\t\t\t\t\t\t? [`${styleText(barStyle, S_BAR)}  ${styleText('yellow', this.error)}`]
\t\t\t\t\t\t\t: [];

\t\t\t\t\t// Calculate header and footer line counts for rowPadding
\t\t\t\t\tconst headerLines = [
\t\t\t\t\t\t...`${title}${styleText(barStyle, S_BAR)}`.split('\\n'),
\t\t\t\t\t\t`${styleText(barStyle, S_BAR)}  ${styleText('dim', 'Search:')} ${searchText}${matches}`,
\t\t\t\t\t\t...loading,
\t\t\t\t\t\t...tooShort,
\t\t\t\t\t\t...noResults,
\t\t\t\t\t\t...fetchError,
\t\t\t\t\t\t...errorMessage,
\t\t\t\t\t];'''
assert old in s, "multiselect noResults block not found"
s=s.replace(old,new)

old = '''\t\t\t\t\t// Get limited options for display
\t\t\t\t\tconst displayOptions = limitOptions({'''
new = '''\t\t\t\t\t// Get limited options for display
\t\t\t\t\tconst displayOptions = this.loading
\t\t\t\t\t\t? []
\t\t\t\t\t\t: limitOptions({'''
assert old in s, "multiselect displayOptions not found"
s=s.replace(old,new)

open(p,'w').write(s)
print("multiselect render done")
PY