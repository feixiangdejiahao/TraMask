cd /app && python3 - <<'PYEOF'
path = 'src/transformer.ts'
with open(path) as f:
    src = f.read()

old_reconstruct = """    base.name = value.name ?? 'Error';
    if (value.stack !== undefined) {
      base.stack = value.stack;
    }
    if (value.cause !== undefined) {
      base.cause = reconstructError(value.cause);
    }
    Object.keys(value).forEach(key => {"""
new_reconstruct = """    base.name = value.name ?? 'Error';
    base.stack = value.stack;
    if (value.cause !== undefined) {
      base.cause = reconstructError(value.cause);
    }
    Object.keys(value).forEach(key => {"""
assert old_reconstruct in src
src = src.replace(old_reconstruct, new_reconstruct)

old_untransform = """  e.name = v.name ?? 'Error';
  if (v.stack !== undefined) {
    e.stack = v.stack;
  }
  if (v.stackFrames !== undefined) {
    e.stackFrames = v.stackFrames;
  }
  if (v.cause !== undefined) {
    e.cause = reconstructError(v.cause);
  }"""
new_untransform = """  e.name = v.name ?? 'Error';
  e.stack = v.stack;
  e.stackFrames = v.stackFrames;
  if (v.cause !== undefined) {
    e.cause = reconstructError(v.cause);
  }"""
assert old_untransform in src
src = src.replace(old_untransform, new_untransform)

with open(path, 'w') as f:
    f.write(src)
print('patched')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -20