cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.ts'
with open(path) as f:
    src = f.read()

old = """export function processStackString(
  stack: string,
  options: NormalizedErrorStackOptions
): string {
  const lines = normalizeStackNewlines(stack).split('\\n');"""
new = """export function processStackString(
  stack: string,
  options: NormalizedErrorStackOptions
): string {
  const normalized = options.normalizeNewlines
    ? normalizeStackNewlines(stack)
    : stack;
  const lines = normalized.split('\\n');"""
assert old in src
src = src.replace(old, new)

old2 = """export function processStackFrames(
  stack: string,
  options: NormalizedErrorStackOptions
): { raw: string }[] {
  const lines = normalizeStackNewlines(stack).split('\\n');"""
new2 = """export function processStackFrames(
  stack: string,
  options: NormalizedErrorStackOptions
): { raw: string }[] {
  const normalized = options.normalizeNewlines
    ? normalizeStackNewlines(stack)
    : stack;
  const lines = normalized.split('\\n');"""
assert old2 in src
src = src.replace(old2, new2)

with open(path, 'w') as f:
    f.write(src)
print('patched')
PYEOF
nl -ba src/error-stack.ts | sed -n '60,120p'