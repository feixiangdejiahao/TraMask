cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.ts'
with open(path) as f:
    src = f.read()

old_import = """import {
  NormalizedErrorStackOptions,
  RedactPaths,
  StripInternalFrames,
} from './error-options.js';"""
new_import = """import {
  ErrorStackOptions,
  NormalizedErrorStackOptions,
  RedactPaths,
  StripInternalFrames,
  normalizeErrorStackOptions,
} from './error-options.js';"""
assert old_import in src
src = src.replace(old_import, new_import)

# Add defaultOptions after normalizeStackNewlines
old_norm = """export function normalizeStackNewlines(stack: string): string {
  return stack.replace(/\\r\\n/g, '\\n').replace(/\\r/g, '\\n');
}
"""
new_norm = """export function normalizeStackNewlines(stack: string): string {
  return stack.replace(/\\r\\n/g, '\\n').replace(/\\r/g, '\\n');
}

const defaultOptions = normalizeErrorStackOptions({})!;
"""
assert old_norm in src
src = src.replace(old_norm, new_norm)

# processStackString signature + normalize
old_fn = """export function processStackString(
  stack: string,
  options: NormalizedErrorStackOptions
): string {
  const lines = splitStack(stack, options.normalizeNewlines);"""
new_fn = """export function processStackString(
  stack: string,
  options: ErrorStackOptions
): string {
  const normalizedOptions =
    normalizeErrorStackOptions(options) ?? defaultOptions;
  const lines = splitStack(stack, normalizedOptions.normalizeNewlines);"""
assert old_fn in src
src = src.replace(old_fn, new_fn)

# processStackFrames signature + normalize
old_fn2 = """export function processStackFrames(
  stack: string,
  options: NormalizedErrorStackOptions
): { raw: string }[] {
  const lines = splitStack(stack, options.normalizeNewlines);"""
new_fn2 = """export function processStackFrames(
  stack: string,
  options: ErrorStackOptions
): { raw: string }[] {
  const normalizedOptions =
    normalizeErrorStackOptions(options) ?? defaultOptions;
  const lines = splitStack(stack, normalizedOptions.normalizeNewlines);"""
assert old_fn2 in src
src = src.replace(old_fn2, new_fn2)

# Replace all remaining references to `options.` inside the two functions with `normalizedOptions.`
# We'll do targeted replacements within the function bodies.
for token in [
    'options.trimLeadingWhitespace',
    'options.redactPaths',
    'options.maxStackLines',
    'options.stripInternalFrames',
]:
    # Only replace occurrences after processStackString definition (function bodies)
    src = src.replace(token, 'normalizedOptions.' + token[len('options.'):])
# Fix the accidental double replacement in the first line we already changed (normalizedOptions.normalizeNewlines stays fine)

with open(path, 'w') as f:
    f.write(src)
print('patched error-stack.ts')
PYEOF
nl -ba src/error-stack.ts | sed -n '1,160p'