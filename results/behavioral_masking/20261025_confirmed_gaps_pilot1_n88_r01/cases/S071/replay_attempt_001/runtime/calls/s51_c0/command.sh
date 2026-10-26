cd /app && python3 - <<'PYEOF'
path = 'src/transformer.ts'
with open(path) as f:
    src = f.read()

old_cause = """const serializeErrorCause = (
  cause: unknown,
  options: NormalizedErrorStackOptions,
  superJson: SuperJSON,
  depth: number
): any => {
  if (!isError(cause)) {
    return undefined;
  }

  if (options.includeCauses === 'direct') {
    return serializeErrorLeaf(cause, options);
  }

  if (depth >= options.maxCauseDepth) {
    return undefined;
  }

  return serializeErrorWithOptions(cause, superJson, options, depth + 1);
};
"""
new_cause = """const serializeErrorCause = (
  cause: unknown,
  options: NormalizedErrorStackOptions,
  depth: number
): any => {
  if (!isError(cause)) {
    return undefined;
  }

  if (options.includeCauses === 'direct') {
    return serializeErrorLeaf(cause, options);
  }

  if (depth >= options.maxCauseDepth) {
    return undefined;
  }

  const result = serializeErrorLeaf(cause, options);
  if ('cause' in cause) {
    const next = serializeErrorCause(
      (cause as any).cause,
      options,
      depth + 1
    );
    if (next !== undefined) {
      result.cause = next;
    }
  }
  return result;
};
"""
assert old_cause in src
src = src.replace(old_cause, new_cause)

old_call = """    const cause = serializeErrorCause(
      error.cause,
      options,
      superJson,
      causeDepth
    );"""
new_call = """    const cause = serializeErrorCause(
      error.cause,
      options,
      causeDepth
    );"""
assert old_call in src
src = src.replace(old_call, new_call)

with open(path, 'w') as f:
    f.write(src)
print('patched')
PYEOF
npx tsc --noEmit 2>&1 | head -20 && echo "TSC OK"
npx vitest run src/error-stack.test.ts 2>&1 | tail -15