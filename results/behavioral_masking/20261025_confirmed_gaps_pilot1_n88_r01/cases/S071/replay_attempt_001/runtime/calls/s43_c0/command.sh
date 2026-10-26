cd /app && python3 - <<'PYEOF'
# Remove unused NormalizedErrorStackOptions import in error-stack.ts
path = 'src/error-stack.ts'
with open(path) as f:
    src = f.read()
old = """import {
  ErrorStackOptions,
  NormalizedErrorStackOptions,
  RedactPaths,
  StripInternalFrames,
  normalizeErrorStackOptions,
} from './error-options.js';"""
new = """import {
  ErrorStackOptions,
  RedactPaths,
  StripInternalFrames,
  normalizeErrorStackOptions,
} from './error-options.js';"""
assert old in src
src = src.replace(old, new)
with open(path, 'w') as f:
    f.write(src)

# Update transformer.ts: suppress stackFrames in string mode and stack in frames mode,
# and suppress both stack/stackFrames in default rule when errorStack options exist.
path2 = 'src/transformer.ts'
with open(path2) as f:
    src2 = f.read()

old_loop = """    } else if (prop === 'stackFrames') {
      if (
        options.mode === 'frames' &&
        typeof (error as any).stack === 'string'
      ) {
        baseError.stackFrames = processStackFrames(
          (error as any).stack,
          options
        );
      } else {
        baseError.stackFrames = (error as any).stackFrames;
      }
    } else {"""
new_loop = """    } else if (prop === 'stackFrames') {
      if (
        options.mode === 'frames' &&
        typeof (error as any).stack === 'string'
      ) {
        baseError.stackFrames = processStackFrames(
          (error as any).stack,
          options
        );
      }
    } else {"""
assert old_loop in src2
src2 = src2.replace(old_loop, new_loop)

old_default = """      superJson.allowedErrorProps.forEach(prop => {
        if (prop === 'stack' && superJson.errorStackOptions) {
          return;
        }
        baseError[prop] = (v as any)[prop];
      });"""
new_default = """      superJson.allowedErrorProps.forEach(prop => {
        if (
          superJson.errorStackOptions &&
          (prop === 'stack' || prop === 'stackFrames')
        ) {
          return;
        }
        baseError[prop] = (v as any)[prop];
      });"""
assert old_default in src2
src2 = src2.replace(old_default, new_default)

with open(path2, 'w') as f:
    f.write(src2)
print('done')
PYEOF
npx tsc --noEmit 2>&1 | head -20 && echo "TSC OK"