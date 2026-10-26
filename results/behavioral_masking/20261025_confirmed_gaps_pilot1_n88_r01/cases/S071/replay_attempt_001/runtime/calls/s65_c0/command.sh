cd /app && git commit -m "feat: add errorStack constructor option

Adds configurable Error stack serialization with modes off, string, and
frames, including stack processing (newline normalization, whitespace
trimming, path redaction, max line limits, internal frame stripping),
cause inclusion, message sanitization, class filtering, and
post-serialization hooks via registerErrorStackProcessor.

New modules:
- error-options.ts (normalizeErrorStackOptions)
- error-stack.ts (processStackString, processStackFrames, normalizeStackNewlines)
- error-sanitizer.ts (sanitizeMessage)
- error-class-registry.ts (ErrorClassRegistry)

Existing Error serialization behavior is unchanged when errorStack is
omitted." && git log --oneline -3