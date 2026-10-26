cd /app && python3 - <<'PYEOF'
path = 'src/transformer.ts'
with open(path) as f:
    src = f.read()

old_transform = """      if ('cause' in v) {
        baseError.cause = v.cause;
      }

      superJson.allowedErrorProps.forEach(prop => {
        if (
          superJson.errorStackOptions &&
          (prop === 'stack' || prop === 'stackFrames')
        ) {
          return;
        }
        baseError[prop] = (v as any)[prop];
      });

      return baseError;
    },
    (v, superJson) => {
      const e = new Error(v.message, { cause: v.cause });
      e.name = v.name;
      e.stack = v.stack;

      superJson.allowedErrorProps.forEach(prop => {
        (e as any)[prop] = v[prop];
      });

      return e;
    }
  ),"""

new_transform = """      if ('cause' in v) {
        baseError.cause = v.cause;
      }

      if (
        superJson.errorStackOptions &&
        isAggregateError(v) &&
        'errors' in v
      ) {
        baseError.errors = (v as any).errors;
      }

      superJson.allowedErrorProps.forEach(prop => {
        if (
          superJson.errorStackOptions &&
          (prop === 'stack' || prop === 'stackFrames')
        ) {
          return;
        }
        baseError[prop] = (v as any)[prop];
      });

      return baseError;
    },
    (v, superJson) => {
      const e: any = new Error(v.message, { cause: v.cause });
      e.name = v.name;
      e.stack = v.stack;

      if (Array.isArray(v.errors)) {
        e.errors = v.errors;
      }

      superJson.allowedErrorProps.forEach(prop => {
        (e as any)[prop] = v[prop];
      });

      return e;
    }
  ),"""

assert old_transform in src
src = src.replace(old_transform, new_transform)

with open(path, 'w') as f:
    f.write(src)
print('patched')
PYEOF
npx tsc --noEmit 2>&1 | head && echo TSC_OK
npx vitest run 2>&1 | tail -15