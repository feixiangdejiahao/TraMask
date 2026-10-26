cd /app && python3 - <<'PYEOF'
import re

path = 'src/transformer.ts'
with open(path) as f:
    src = f.read()

# 1. Replace import block
old_import = """import {
  isBigint,
  isDate,
  isInfinite,
  isMap,
  isNaNValue,
  isRegExp,
  isSet,
  isUndefined,
  isSymbol,
  isArray,
  isError,
  isTypedArray,
  TypedArrayConstructor,
  isURL,
} from './is.js';
import { findArr } from './util.js';
import SuperJSON from './index.js';"""

new_import = """import {
  isBigint,
  isDate,
  isInfinite,
  isMap,
  isNaNValue,
  isRegExp,
  isSet,
  isUndefined,
  isSymbol,
  isArray,
  isError,
  isTypedArray,
  TypedArrayConstructor,
  isURL,
} from './is.js';
import { findArr } from './util.js';
import SuperJSON from './index.js';
import { processStackFrames, processStackString } from './error-stack.js';
import { NormalizedErrorStackOptions } from './error-options.js';
import { sanitizeMessage } from './error-sanitizer.js';"""

assert old_import in src
src = src.replace(old_import, new_import)

# 2. Replace SimpleTypeAnnotation
old_type = "type SimpleTypeAnnotation = LeafTypeAnnotation | 'map' | 'set' | 'Error';"
new_type = """type SimpleTypeAnnotation =
  | LeafTypeAnnotation
  | 'map'
  | 'set'
  | 'Error'
  | 'Error/stack'
  | 'Error/frames';"""
assert old_type in src
src = src.replace(old_type, new_type)

# 3. Insert helpers before "const simpleRules = ["
helpers = r'''const matchesClassFilter = (
  error: Error,
  options: NormalizedErrorStackOptions | undefined
): boolean => {
  if (!options || options.classFilter.length === 0) {
    return true;
  }
  return options.classFilter.includes(error.name);
};

const isErrorStackString = (
  v: any,
  superJson: SuperJSON
): v is Error =>
  isError(v) &&
  superJson.errorStackOptions?.mode === 'string' &&
  matchesClassFilter(v, superJson.errorStackOptions);

const isErrorStackFrames = (
  v: any,
  superJson: SuperJSON
): v is Error =>
  isError(v) &&
  superJson.errorStackOptions?.mode === 'frames' &&
  matchesClassFilter(v, superJson.errorStackOptions);

const isDefaultError = (
  v: any,
  superJson: SuperJSON
): v is Error =>
  isError(v) &&
  !isErrorStackString(v, superJson) &&
  !isErrorStackFrames(v, superJson);

const isAggregateError = (error: any): error is any =>
  typeof AggregateError !== 'undefined' && error instanceof AggregateError;

const serializeErrorLeaf = (
  error: Error,
  options: NormalizedErrorStackOptions
): any => {
  const result: any = {
    name: error.name,
    message: error.message,
  };

  if (options.sanitizeMessage) {
    result.message = sanitizeMessage(result.message);
  }

  if (isAggregateError(error) && 'errors' in error) {
    result.errors = (error as any).errors;
  }

  return result;
};

const serializeErrorWithOptions = (
  error: Error,
  superJson: SuperJSON,
  options: NormalizedErrorStackOptions,
  causeDepth = 0
): any => {
  const baseError: any = {
    name: error.name,
    message: error.message,
  };

  if (options.includeCauses !== 'none' && 'cause' in error) {
    const cause = serializeErrorCause(
      error.cause,
      options,
      superJson,
      causeDepth
    );
    if (cause !== undefined) {
      baseError.cause = cause;
    }
  }

  if (isAggregateError(error) && 'errors' in error) {
    baseError.errors = (error as any).errors;
  }

  superJson.allowedErrorProps.forEach(prop => {
    if (prop === 'stack') {
      if (
        options.mode === 'string' &&
        typeof (error as any).stack === 'string'
      ) {
        baseError.stack = processStackString((error as any).stack, options);
      }
    } else if (prop === 'stackFrames') {
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
    } else {
      baseError[prop] = (error as any)[prop];
    }
  });

  if (options.sanitizeMessage) {
    baseError.message = sanitizeMessage(baseError.message);
  }

  const processor = superJson.errorClassRegistry.getProcessor(error.name);
  if (processor) {
    return processor(baseError);
  }

  return baseError;
};

const serializeErrorCause = (
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

const reconstructError = (value: any): Error => {
  if (value instanceof Error) {
    return value;
  }

  if (value && typeof value === 'object') {
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
  }

  return new Error(String(value));
};

const errorStackUntransform = (v: any, superJson: SuperJSON) => {
  const e: any = Array.isArray(v.errors)
    ? new AggregateError(v.errors, v.message ?? '')
    : new Error(v.message ?? '');
  e.name = v.name ?? 'Error';
  if (v.stack !== undefined) {
    e.stack = v.stack;
  }
  if (v.stackFrames !== undefined) {
    e.stackFrames = v.stackFrames;
  }
  if (v.cause !== undefined) {
    e.cause = reconstructError(v.cause);
  }
  if (Array.isArray(v.errors)) {
    e.errors = v.errors;
  }

  superJson.allowedErrorProps.forEach(prop => {
    if (prop === 'stack' || prop === 'stackFrames') {
      return;
    }
    (e as any)[prop] = v[prop];
  });

  return e;
};

const simpleRules = ['''

assert "const simpleRules = [" in src
src = src.replace("const simpleRules = [", helpers, 1)

# 4. Replace the old error rule block with three rules
old_error_rule = r'''  simpleTransformation(
    isError,
    'Error',
    (v, superJson) => {
      const baseError: any = {
        name: v.name,
        message: v.message,
      };

      if ('cause' in v) {
        baseError.cause = v.cause;
      }

      superJson.allowedErrorProps.forEach(prop => {
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
  ),'''

new_error_rules = r'''  simpleTransformation(
    isErrorStackString,
    'Error/stack',
    (v, superJson) =>
      serializeErrorWithOptions(v, superJson, superJson.errorStackOptions!),
    errorStackUntransform
  ),

  simpleTransformation(
    isErrorStackFrames,
    'Error/frames',
    (v, superJson) =>
      serializeErrorWithOptions(v, superJson, superJson.errorStackOptions!),
    errorStackUntransform
  ),

  simpleTransformation(
    isDefaultError,
    'Error',
    (v, superJson) => {
      const baseError: any = {
        name: v.name,
        message: v.message,
      };

      if ('cause' in v) {
        baseError.cause = v.cause;
      }

      superJson.allowedErrorProps.forEach(prop => {
        if (prop === 'stack' && superJson.errorStackOptions) {
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
  ),'''

assert old_error_rule in src, "old error rule not found"
src = src.replace(old_error_rule, new_error_rules)

with open(path, 'w') as f:
    f.write(src)

print("patched transformer.ts")
PYEOF