cd /app && python3 - <<'PYEOF'
path = 'src/transformer.ts'
with open(path) as f:
    src = f.read()

old_reconstruct = """  if (value && typeof value === 'object') {
    const base: any = Array.isArray(value.errors)
      ? new AggregateError(value.errors, value.message ?? '')
      : new Error(value.message ?? '');
    base.name = value.name ?? 'Error';
    if (value.stack !== undefined) {
      base.stack = value.stack;
    }
    if (value.cause !== undefined) {
      base.cause = reconstructError(value.cause);
    }
    return base;
  }"""

new_reconstruct = """  if (value && typeof value === 'object') {
    const base: any = Array.isArray(value.errors)
      ? new AggregateError(value.errors, value.message ?? '')
      : new Error(value.message ?? '');
    base.name = value.name ?? 'Error';
    if (value.stack !== undefined) {
      base.stack = value.stack;
    }
    if (value.cause !== undefined) {
      base.cause = reconstructError(value.cause);
    }
    Object.keys(value).forEach(key => {
      if (
        key === 'name' ||
        key === 'message' ||
        key === 'stack' ||
        key === 'cause' ||
        key === 'errors'
      ) {
        return;
      }
      base[key] = value[key];
    });
    return base;
  }"""

assert old_reconstruct in src
src = src.replace(old_reconstruct, new_reconstruct)

old_untransform = """  if (Array.isArray(v.errors)) {
    e.errors = v.errors;
  }

  superJson.allowedErrorProps.forEach(prop => {
    if (prop === 'stack' || prop === 'stackFrames') {
      return;
    }
    (e as any)[prop] = v[prop];
  });

  return e;
};"""

new_untransform = """  if (Array.isArray(v.errors)) {
    e.errors = v.errors;
  }

  Object.keys(v).forEach(key => {
    if (
      key === 'name' ||
      key === 'message' ||
      key === 'stack' ||
      key === 'stackFrames' ||
      key === 'cause' ||
      key === 'errors'
    ) {
      return;
    }
    e[key] = v[key];
  });

  return e;
};"""

assert old_untransform in src
src = src.replace(old_untransform, new_untransform)

with open(path, 'w') as f:
    f.write(src)
print('patched')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -30