import { describe, expect, it } from 'vitest';
import SuperJSON from './index.js';
import {
  normalizeStackNewlines,
  processStackFrames,
  processStackString,
} from './error-stack.js';
import { normalizeErrorStackOptions } from './error-options.js';
import { sanitizeMessage } from './error-sanitizer.js';
import { ErrorClassRegistry } from './error-class-registry.js';

const stack = `Error: test
    at fn1 (/home/user/project/src/a.ts:1:2)
    at fn2 (/home/user/project/src/b.ts:3:4)
    at node:internal/modules/cjs/loader:5:6
    at superjson (/app/src/transformer.ts:7:8)`;

describe('error-stack exports', () => {
  it('normalizeStackNewlines converts CRLF and CR to LF', () => {
    expect(normalizeStackNewlines('a\r\nb\rc')).toBe('a\nb\nc');
  });

  it('processStackString trims leading whitespace by default', () => {
    const options = normalizeErrorStackOptions({ mode: 'string' })!;
    expect(processStackString(stack, options)).toBe(`Error: test
at fn1 (/home/user/project/src/a.ts:1:2)
at fn2 (/home/user/project/src/b.ts:3:4)
at node:internal/modules/cjs/loader:5:6
at superjson (/app/src/transformer.ts:7:8)`);
  });

  it('processStackString preserves leading whitespace when disabled', () => {
    const options = normalizeErrorStackOptions({
      mode: 'string',
      trimLeadingWhitespace: false,
    })!;
    expect(processStackString(stack, options)).toContain('\n    at fn1');
  });

  it('processStackString honors maxStackLines (header counts as a line)', () => {
    const options = normalizeErrorStackOptions({
      mode: 'string',
      maxStackLines: 2,
    })!;
    expect(processStackString(stack, options).split('\n')).toHaveLength(2);
    expect(processStackString(stack, options).startsWith('Error: test')).toBe(
      true
    );
  });

  it('processStackString strips internal frames after limiting', () => {
    const options = normalizeErrorStackOptions({
      mode: 'string',
      maxStackLines: 3,
      stripInternalFrames: 'node',
    })!;
    expect(processStackString(stack, options)).toBe(`Error: test
at fn1 (/home/user/project/src/a.ts:1:2)
at fn2 (/home/user/project/src/b.ts:3:4)`);
  });

  it('processStackString redacts paths to basename', () => {
    const options = normalizeErrorStackOptions({
      mode: 'string',
      redactPaths: 'basename',
    })!;
    const result = processStackString(stack, options);
    expect(result).toContain('at fn1 (a.ts:1:2)');
    expect(result).toContain('at fn2 (b.ts:3:4)');
  });

  it('processStackString strips cwd prefix', () => {
    const cwdStack = `Error: test
    at fn1 (${process.cwd()}/src/a.ts:1:2)
    at fn2 (/other/path/b.ts:3:4)`;
    const options = normalizeErrorStackOptions({
      mode: 'string',
      redactPaths: 'strip_cwd',
    })!;
    const result = processStackString(cwdStack, options);
    expect(result).toContain('at fn1 (src/a.ts:1:2)');
    expect(result).toContain('at fn2 (/other/path/b.ts:3:4)');
  });

  it('processStackFrames uses header as first raw frame', () => {
    const options = normalizeErrorStackOptions({ mode: 'frames' })!;
    const result = processStackFrames(stack, options);
    expect(result[0]).toEqual({ raw: 'Error: test' });
    expect(result[1]).toEqual({
      raw: 'at fn1 (/home/user/project/src/a.ts:1:2)',
    });
  });

  it('processStackFrames strips before limiting', () => {
    const options = normalizeErrorStackOptions({
      mode: 'frames',
      maxStackLines: 3,
      stripInternalFrames: 'node',
    })!;
    const result = processStackFrames(stack, options);
    expect(result).toEqual([
      { raw: 'Error: test' },
      { raw: 'at fn1 (/home/user/project/src/a.ts:1:2)' },
      { raw: 'at fn2 (/home/user/project/src/b.ts:3:4)' },
    ]);
  });
});

describe('error-options exports', () => {
  it('returns undefined for non-objects', () => {
    expect(normalizeErrorStackOptions(undefined)).toBeUndefined();
    expect(normalizeErrorStackOptions(null)).toBeUndefined();
    expect(normalizeErrorStackOptions('string')).toBeUndefined();
  });

  it('treats missing or invalid mode as off', () => {
    expect(normalizeErrorStackOptions({})?.mode).toBe('off');
    expect(normalizeErrorStackOptions({ mode: 'bogus' } as any)?.mode).toBe(
      'off'
    );
    expect(
      normalizeErrorStackOptions({ mode: 'string' } as any)?.mode
    ).toBe('string');
  });

  it('treats invalid maxStackLines as off', () => {
    expect(
      normalizeErrorStackOptions({ mode: 'string', maxStackLines: 0 })?.mode
    ).toBe('off');
    expect(
      normalizeErrorStackOptions({ mode: 'string', maxStackLines: -1 })?.mode
    ).toBe('off');
    expect(
      normalizeErrorStackOptions({ mode: 'string', maxStackLines: 1.5 })?.mode
    ).toBe('off');
  });

  it('falls back to includeCauses none for non-integer maxCauseDepth', () => {
    expect(
      normalizeErrorStackOptions({
        includeCauses: 'deep',
        maxCauseDepth: 1.5,
      })?.includeCauses
    ).toBe('none');
  });

  it('defaults maxCauseDepth to 16', () => {
    expect(
      normalizeErrorStackOptions({ includeCauses: 'deep' })?.maxCauseDepth
    ).toBe(16);
  });
});

describe('error-sanitizer exports', () => {
  it('redacts URLs, emails, and IPv4 addresses', () => {
    expect(
      sanitizeMessage(
        'see https://example.com/path, write foo@bar.com or connect to 1.2.3.4'
      )
    ).toBe('see [redacted], write [redacted] or connect to [redacted]');
  });
});

describe('error-class-registry exports', () => {
  it('implements register, has and getProcessor', () => {
    const registry = new ErrorClassRegistry();
    const processor = () => ({});
    expect(registry.has('MyError')).toBe(false);
    registry.register('MyError', processor);
    expect(registry.has('MyError')).toBe(true);
    expect(registry.getProcessor('MyError')).toBe(processor);
    expect(registry.getProcessor('Other')).toBeUndefined();
  });
});

describe('SuperJSON errorStack option', () => {
  it('off mode never serializes stack even when allowed', () => {
    const superJson = new SuperJSON({ errorStack: { mode: 'off' } });
    superJson.allowErrorProps('stack');
    const parsed: any = superJson.parse(superJson.stringify(new Error('boom')));
    expect(parsed.stack).toBeUndefined();
  });

  it('string mode processes stack when allowed', () => {
    const superJson = new SuperJSON({
      errorStack: { mode: 'string', maxStackLines: 2 },
    });
    superJson.allowErrorProps('stack');
    const parsed: any = superJson.parse(
      superJson.stringify(new Error('boom'))
    );
    expect(parsed.stack).toBeDefined();
    expect(parsed.stack.split('\n')).toHaveLength(2);
    expect(parsed.stack).toMatch(/^Error: boom$/m);
  });

  it('uses Error/stack annotation in string mode', () => {
    const superJson = new SuperJSON({ errorStack: { mode: 'string' } });
    superJson.allowErrorProps('stack');
    expect(superJson.serialize(new Error('boom')).meta?.values).toEqual([
      'Error/stack',
    ]);
  });

  it('frames mode serializes stackFrames when allowed', () => {
    const superJson = new SuperJSON({ errorStack: { mode: 'frames' } });
    superJson.allowErrorProps('stackFrames');
    const parsed: any = superJson.parse(
      superJson.stringify(new Error('boom'))
    );
    expect(parsed.stackFrames).toBeInstanceOf(Array);
    expect(parsed.stackFrames[0]).toEqual({ raw: 'Error: boom' });
    expect(parsed.stackFrames[0].raw).toBeTypeOf('string');
  });

  it('uses Error/frames annotation in frames mode', () => {
    const superJson = new SuperJSON({ errorStack: { mode: 'frames' } });
    superJson.allowErrorProps('stackFrames');
    expect(superJson.serialize(new Error('boom')).meta?.values).toEqual([
      'Error/frames',
    ]);
  });

  it('classFilter restricts stack processing', () => {
    class CustomError extends Error {
      constructor(message: string) {
        super(message);
        this.name = 'CustomError';
      }
    }
    const superJson = new SuperJSON({
      errorStack: { mode: 'string', classFilter: ['CustomError'] },
    });
    superJson.allowErrorProps('stack');
    expect(superJson.serialize(new CustomError('x')).meta?.values).toEqual([
      'Error/stack',
    ]);
    expect(superJson.serialize(new Error('x')).meta?.values).toEqual([
      'Error',
    ]);
  });

  it('includeCauses none drops causes', () => {
    const superJson = new SuperJSON({ errorStack: { mode: 'off' } });
    const error: any = new Error('outer', { cause: new Error('inner') });
    const parsed: any = superJson.parse(superJson.stringify(error));
    expect(parsed.cause).toBeUndefined();
  });

  it('includeCauses direct keeps only the immediate cause', () => {
    const superJson = new SuperJSON({ errorStack: { includeCauses: 'direct' } });
    const inner = new Error('inner', { cause: new Error('deep') });
    const error: any = new Error('outer', { cause: inner });
    const parsed: any = superJson.parse(superJson.stringify(error));
    expect(parsed.cause).toBeInstanceOf(Error);
    expect(parsed.cause.message).toBe('inner');
    expect(parsed.cause.cause).toBeUndefined();
  });

  it('includeCauses deep respects maxCauseDepth', () => {
    const superJson = new SuperJSON({
      errorStack: { includeCauses: 'deep', maxCauseDepth: 2 },
    });
    let cause: any = new Error('level3');
    cause = new Error('level2', { cause });
    cause = new Error('level1', { cause });
    const error: any = new Error('level0', { cause });
    const parsed: any = superJson.parse(superJson.stringify(error));
    expect(parsed.cause.message).toBe('level1');
    expect(parsed.cause.cause.message).toBe('level2');
    expect(parsed.cause.cause.cause).toBeUndefined();
  });

  it('drops non-Error causes', () => {
    const superJson = new SuperJSON({ errorStack: { includeCauses: 'direct' } });
    const error: any = new Error('outer', { cause: 'oops' } as any);
    const parsed: any = superJson.parse(superJson.stringify(error));
    expect(parsed.cause).toBeUndefined();
  });

  it('sanitizeMessage applies to messages and causes', () => {
    const superJson = new SuperJSON({
      errorStack: { includeCauses: 'deep', sanitizeMessage: true },
    });
    const error: any = new Error('outer https://example.com', {
      cause: new Error('inner foo@bar.com'),
    });
    const parsed: any = superJson.parse(superJson.stringify(error));
    expect(parsed.message).toBe('outer [redacted]');
    expect(parsed.cause.message).toBe('inner [redacted]');
  });

  it('serializes AggregateError errors', () => {
    const superJson = new SuperJSON({ errorStack: { mode: 'off' } });
    const aggregate: any = new AggregateError(
      [new Error('a'), new Error('b')],
      'aggregate'
    );
    const parsed: any = superJson.parse(superJson.stringify(aggregate));
    expect(parsed.errors).toHaveLength(2);
    expect(parsed.errors[0]).toBeInstanceOf(Error);
    expect(parsed.errors[0].message).toBe('a');
  });

  it('registerErrorStackProcessor runs after serialization steps', () => {
    const superJson = new SuperJSON({
      errorStack: { mode: 'string', maxStackLines: 1 },
    });
    superJson.allowErrorProps('stack');
    superJson.registerErrorStackProcessor('Error', (serialized: any) => {
      expect(serialized.name).toBe('Error');
      expect(serialized.message).toBeDefined();
      expect(serialized.stack).toBeDefined();
      return { ...serialized, extra: 'added' };
    });
    const error = new Error('boom');
    const serialized = superJson.serialize(error);
    expect((serialized.json as any).extra).toBe('added');
    const parsed: any = superJson.parse(superJson.stringify(error));
    expect(parsed.extra).toBe('added');
  });

  it('stops cleanly on circular cause chains', () => {
    const superJson = new SuperJSON({ errorStack: { includeCauses: 'deep' } });
    const a: any = new Error('a');
    const b: any = new Error('b');
    a.cause = b;
    b.cause = a;
    expect(() => superJson.stringify(a)).not.toThrow();
    const parsed: any = superJson.parse(superJson.stringify(a));
    expect(parsed.message).toBe('a');
  });
});
