cd /app && python3 - <<'PY'
p='packages/prompts/src/autocomplete.ts'
s=open(p).read()
old = "\t\tplaceholder: opts.placeholder,\n\t\tfilter:"
new = """\t\tplaceholder: opts.placeholder,
\t\tdebounceMs: opts.debounceMs,
\t\tcacheResults:
\t\t\topts.cacheResults === true
\t\t\t\t? opts.maxCacheSize !== undefined
\t\t\t\t\t? { maxCacheSize: opts.maxCacheSize }
\t\t\t\t\t: true
\t\t\t\t: undefined,
\t\tminSearchLength: opts.minSearchLength,
\t\tstaleWhileRevalidate: opts.staleWhileRevalidate,
\t\tmaxRetries: opts.maxRetries,
\t\tretryDelay: opts.retryDelay,
\t\tretryBackoff: opts.retryBackoff,
\t\tfallbackOptions: opts.fallbackOptions,
\t\tloadingMinDuration: opts.loadingMinDuration,
\t\tfilter:"""
count = s.count(old)
print("count:", count)
assert count == 2
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
nl -ba packages/prompts/src/autocomplete.ts | sed -n '137,175p'