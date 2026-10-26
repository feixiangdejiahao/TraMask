import { describe, expect, it, test } from 'vitest';
import SuperJSON from './index.js';
import {
  normalizeStackNewlines,
  processStackFrames,
  processStackString,
} from './error-stack.js';
import { normalizeErrorStackOptions } from './error-options.js';
import { sanitizeMessage } from './error-sanitizer.js';
import { ErrorClassRegistry } from './error-class-registry.js';

describe('normalizeErrorStackOptions', () => {
  it('returns undefined for non-object input', () => {
    expect(normalizeErrorStackOptions(undefined)).toBeUndefined();
    expect(normalizeErrorStackOptions(null)).toBeUndefined();
    expect(normalizeErrorStackOptions('hello' as any)).toBeUndefined();
  });

  it('treats missing/invalid mode as off', () => {
    expect(normalizeErrorStackOptions({})?.mode).toBe('off');
    expect(normalizeErrorStackOptions({ mode: 'bogus' as any })?.mode).toBe(
      'off'
    );
  });

  it('applies defaults', () => {
    const opts = normalizeErrorStackOptions({ mode: 'string' })!;
    expect(opts.mode).toBe('string');
    expect(opts.normalizeNewlines).toBe(false);
    expect(opts.trimLeadingWhitespace).toBe(true);
    expect(opts.stripInternalFrames).toBe('none');
    expect(opts.redactPaths).toBe('none');
    expect(opts.includeCauses).toBe('none');
    expect(opts.sanitizeMessage).toBe(false);
    expect(opts.maxStackLines).toBeUndefined();
  });

  it('normalizes enums and falls back unknown values to none', () => {
    const opts = normalizeErrorStackOptions({
      mode: 'frames',
      stripInternalFrames: 'node' as any,
      redactPaths: 'basename' as any,
      includeCauses: 'deep',
      maxCauseDepth: 3,
    })!;
    expect(opts.stripInternalFrames).toBe('node');
    expect(opts.redactPaths).toBe('basename');
    expect(opts.includeCauses).toBe('deep');
    expect(opts.maxCauseDepth).toBe(3);

    const invalid = normalizeErrorStackOptions({
      stripInternalFrames: 'bogus' as any,
      redactPaths: 'bogus' as any,
    })!;
    expect(invalid.stripInternalFrames).toBe('none');
    expect(invalid.redactPaths).toBe('none');
  });

  it('defaults maxCauseDepth to 16 for deep', () => {
    expect(normalizeErrorStackOptions({ includeCauses: 'deep' })!.maxCauseDepth).toBe(16);
    expect(normalizeErrorStackOptions({ includeCauses: 'deep', maxCauseDepth: 5 })!.maxCauseDepth).toBe(5);
  });

  it('falls back to includeCauses none when maxCauseDepth is invalid', () => {
    const opts = normalizeErrorStackOptions({
      includeCauses: 'deep',
      maxCauseDepth: 1.5,
    })!;
    expect(opts.includeCauses).toBe('none');
  });
});

describe('ErrorClassRegistry', () => {
  it('implements register/has/getProcessor', () => {
    const reg = new ErrorClassRegistry();
    const fn = (x: any) => x;
    expect(reg.has('Foo')).toBe(false);
    reg.register('Foo', fn);
    expect(reg.has('Foo')).toBe(true);
    expect(reg.getProcessor('Foo')).toBe(fn);
    expect(reg.getProcessor('Bar')).toBeUndefined();
  });
});

describe('sanitizeMessage', () => {
  it('redacts urls, emails and ipv4', () => {
    expect(sanitizeMessage('see https://example.com/a?b=1 now')).toBe(
      'see [redacted] now'
    );
    expect(sanitizeMessage('mail me foo.bar@example.com please')).toBe(
      'mail me [redacted] please'
    );
    expect(sanitizeMessage('ip 192.168.0.1 here')).toBe('ip [redacted] here');
  });
});

describe('processStackString', () => {
  const stack = [
    'Error: boom',
    '    at one (/app/src/a.ts:1:2)',
    '    at two (node:internal/foo:3:4)',
    '    at three (/app/src/b.ts:5:6)',
  ].join('\n');

  it('keeps header and applies trimLeadingWhitespace by default', () => {
    const opts = normalizeErrorStackOptions({ mode: 'string' })!;
    const result = processStackString(stack, opts)!;
    expect(result.split('\n')[0]).toBe('Error: boom');
    expect(result.split('\n')[1]).toBe('at one (/app/src/a.ts:1:2)');
  });

  it('preserves leading whitespace when trimLeadingWhitespace is false', () => {
    const opts = normalizeErrorStackOptions({
      mode: 'string',
      trimLeadingWhitespace: false,
    })!;
    const result = processStackString(stack, opts)!;
    expect(result.split('\n')[1]).toBe('    at one (/app/src/a.ts:1:2)');
  });

  it('normalizes newlines', () => {
    const opts = normalizeErrorStackOptions({
      mode: 'string',
      normalizeNewlines: true,
    })!;
    const crlf = stack.replace(/\n/g, '\r\n');
    expect(processStackString(crlf, opts)!.split('\n').length).toBe(
      stack.split('\n').length
    );
    expect(normalizeStackNewlines('a\r\nb\rc')).toBe('a\nb\nc');
  });

  it('applies maxStackLines counting header', () => {
    const opts = normalizeErrorStackOptions({
      mode: 'string',
      maxStackLines: 2,
    })!;
    const result = processStackString(stack, opts)!;
    expect(result.split('\n')).toHaveLength(2);
    expect(result.split('\n')[0]).toBe('Error: boom');
  });

  it('returns undefined for invalid maxStackLines', () => {
    for (const bad of [0, -1, 1.5, NaN]) {
      const opts = normalizeErrorStackOptions({
        mode: 'string',
        maxStackLines: bad,
      })!;
      expect(processStackString(stack, opts)).toBeUndefined();
    }
  });

  it('strips node:internal frames', () => {
    const opts = normalizeErrorStackOptions({
      mode: 'string',
      stripInternalFrames: 'node',
    })!;
    const result = processStackString(stack, opts)!;
    expect(result).not.toContain('node:internal');
    expect(result.split('\n')[0]).toBe('Error: boom');
  });

  it('redacts paths with basename', () => {
    const opts = normalizeErrorStackOptions({
      mode: 'string',
      redactPaths: 'basename',
    })!;
    const result = processStackString(stack, opts)!;
    expect(result).toContain('a.ts:1:2');
    expect(result).not.toContain('/app/src/a.ts');
  });

  it('respects classFilter', () => {
    const opts = normalizeErrorStackOptions({
      mode: 'string',
      classFilter: ['TypeError'],
    })!;
    expect(processStackString(stack, opts)).toBeUndefined();
    const typeStack = stack.replace(/^Error/, 'TypeError');
    expect(processStackString(typeStack, opts)).toBeDefined();
  });
});

describe('processStackFrames', () => {
  const stack = [
    'Error: boom',
    '    at one (/app/src/a.ts:1:2)',
    '    at two (node:internal/foo:3:4)',
    '    at three (/app/src/b.ts:5:6)',
  ].join('\n');

  it('produces array of { raw } with header first', () => {
    const opts = normalizeErrorStackOptions({ mode: 'frames' })!;
    const frames = processStackFrames(stack, opts)!;
    expect(frames[0]).toEqual({ raw: 'Error: boom' });
    expect(frames[1].raw).toBe('at one (/app/src/a.ts:1:2)');
  });

  it('applies frames ordering (strip before max)', () => {
    const opts = normalizeErrorStackOptions({
      mode: 'frames',
      stripInternalFrames: 'node',
      maxStackLines: 2,
    })!;
    const frames = processStackFrames(stack, opts)!;
    // header + first non-internal frame
    expect(frames).toHaveLength(2);
    expect(frames[0].raw).toBe('Error: boom');
    expect(frames[1].raw).toContain('a.ts');
  });
});

describe('SuperJSON errorStack string mode', () => {
  it('does not serialize stack unless allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'string' } });
    const input = new Error('boom');
    const { stack } = sj.parse(sj.stringify(input)) as any;
    expect(stack).toBeUndefined();

    sj.allowErrorProps('stack');
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.message).toBe('boom');
    expect(out.stack.split('\n')[0]).toBe('Error: boom');
  });

  it('off mode never serializes stack even when allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    sj.allowErrorProps('stack');
    const input = new Error('boom');
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.stack).toBeUndefined();
  });

  it('round-trips causes with includeCauses direct', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'direct' },
    });
    sj.allowErrorProps('stack');
    const input = new Error('outer', { cause: new Error('inner') });
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.cause).toBeInstanceOf(Error);
    expect(out.cause.message).toBe('inner');
  });

  it('includeCauses deep respects maxCauseDepth and drops non-Error causes', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'deep', maxCauseDepth: 2 },
    });
    sj.allowErrorProps('stack');
    const inner3 = new Error('3', { cause: 'not-an-error' });
    const inner2 = new Error('2', { cause: inner3 });
    const input = new Error('1', { cause: inner2 });
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.cause.message).toBe('2');
    expect(out.cause.cause.message).toBe('3');
    expect(out.cause.cause.cause).toBeUndefined();
  });

  it('handles circular causes cleanly', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'deep' },
    });
    sj.allowErrorProps('stack');
    const a = new Error('a');
    const b = new Error('b');
    (a as any).cause = b;
    (b as any).cause = a;
    expect(() => sj.parse(sj.stringify(a))).not.toThrow();
  });

  it('sanitizes messages', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', sanitizeMessage: true },
    });
    sj.allowErrorProps('stack');
    const input = new Error('failed at https://example.com, ip 1.2.3.4');
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.message).toBe('failed at [redacted], ip [redacted]');
  });

  it('respects classFilter', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', classFilter: ['TypeError'] },
    });
    sj.allowErrorProps('stack');
    const err = new Error('boom');
    const out = sj.parse(sj.stringify(err)) as any;
    expect(out.stack).toBeUndefined();

    const typeErr = new TypeError('boom');
    const out2 = sj.parse(sj.stringify(typeErr)) as any;
    expect(out2.stack.split('\n')[0]).toBe('TypeError: boom');
  });

  it('registerErrorStackProcessor runs after other steps', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', sanitizeMessage: true },
    });
    sj.allowErrorProps('stack');
    sj.allowErrorProps('custom');
    const seen: any[] = [];
    sj.registerErrorStackProcessor('Error', (serialized) => {
      seen.push(serialized);
      return { ...serialized, custom: 'added' };
    });
    const input = new Error('boom https://x.com');
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.custom).toBe('added');
    expect(seen[0].message).toBe('boom [redacted]');
    expect(seen[0].stack).toBeDefined();
  });

  it('round-trips AggregateError errors', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'string' } });
    const agg = new AggregateError([new Error('one'), new Error('two')], 'agg');
    const out = sj.parse(sj.stringify(agg)) as any;
    expect(out).toBeInstanceOf(AggregateError);
    expect(out.message).toBe('agg');
    expect(out.errors).toHaveLength(2);
    expect(out.errors[0]).toBeInstanceOf(Error);
    expect(out.errors[0].message).toBe('one');
  });
});

describe('SuperJSON errorStack frames mode', () => {
  it('serializes stackFrames when allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stackFrames');
    const input = new Error('boom');
    const out = sj.parse(sj.stringify(input)) as any;
    expect(Array.isArray(out.stackFrames)).toBe(true);
    expect(out.stackFrames[0]).toEqual({ raw: 'Error: boom' });
  });

  it('round-trips through container types', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stackFrames');
    const input = new Error('boom');
    const result = sj.serialize(input);
    const out = sj.deserialize(result) as any;
    expect(out.stackFrames[0]).toEqual({ raw: 'Error: boom' });
  });
});

describe('processStackString edge cases', () => {
  const stack = [
    'Error: boom',
    '    at one (/app/src/a.ts:1:2)',
    '    at two (node:internal/foo:3:4)',
    '    at three (/app/src/transformer.ts:5:6)',
    '    at four (/app/src/index.ts:7:8)',
  ].join('\n');

  it('works with raw (non-normalized) options and trims by default', () => {
    const result = processStackString(stack, { mode: 'string' } as any)!;
    expect(result.split('\n')[1]).toBe('at one (/app/src/a.ts:1:2)');
  });

  it('strips superjson internal frames', () => {
    const opts = { mode: 'string', stripInternalFrames: 'superjson' } as any;
    const result = processStackString(stack, opts)!;
    expect(result).not.toContain('src/transformer.ts');
    expect(result).not.toContain('src/index.ts');
    expect(result).toContain('src/a.ts');
  });

  it('strips node_and_superjson frames', () => {
    const opts = { mode: 'string', stripInternalFrames: 'node_and_superjson' } as any;
    const result = processStackString(stack, opts)!;
    expect(result).not.toContain('node:internal');
    expect(result).not.toContain('src/transformer.ts');
    expect(result).not.toContain('src/index.ts');
  });

  it('redacts paths with strip_cwd', () => {
    const opts = { mode: 'string', redactPaths: 'strip_cwd' } as any;
    const result = processStackString(stack, opts)!;
    expect(result).toContain('src/a.ts:1:2');
    expect(result).not.toContain('/app/src/a.ts');
  });

  it('redacts file:// paths with basename', () => {
    const opts = { mode: 'string', redactPaths: 'basename' } as any;
    const fileStack = 'Error: boom\n    at foo (file:///app/src/a.ts:1:2)';
    const result = processStackString(fileStack, opts)!;
    expect(result).toContain('a.ts:1:2');
    expect(result).not.toContain('file:///app');
  });
});

describe('SuperJSON errorStack string mode edge cases', () => {
  it('invalid maxStackLines behaves like mode=off', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', maxStackLines: 0 },
    });
    sj.allowErrorProps('stack');
    const out = sj.parse(sj.stringify(new Error('boom'))) as any;
    expect(out.stack).toBeUndefined();
  });

  it('uses Error/stack annotation in meta for string mode', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'string' } });
    sj.allowErrorProps('stack');
    const result = sj.serialize(new Error('boom'));
    expect((result.meta!.values as any)[0]).toBe('Error/stack');
  });

  it('uses Error annotation when classFilter misses', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', classFilter: ['TypeError'] },
    });
    sj.allowErrorProps('stack');
    const result = sj.serialize(new Error('boom'));
    expect((result.meta!.values as any)[0]).toBe('Error');
  });

  it('empty classFilter matches all errors', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', classFilter: [] },
    });
    sj.allowErrorProps('stack');
    const out = sj.parse(sj.stringify(new Error('boom'))) as any;
    expect(out.stack.split('\n')[0]).toBe('Error: boom');
  });

  it('drops non-Error direct causes', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'direct' },
    });
    const input = new Error('outer', { cause: 'not-an-error' } as any);
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.cause).toBeUndefined();
  });

  it('sanitizes cause messages when deep', () => {
    const sj = new SuperJSON({
      errorStack: {
        mode: 'string',
        includeCauses: 'deep',
        sanitizeMessage: true,
      },
    });
    const input = new Error('outer', {
      cause: new Error('see https://example.com'),
    });
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.cause.message).toBe('see [redacted]');
  });

  it('deep defaults to maxCauseDepth 16', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'deep' },
    });
    let cause: any = new Error('deep-16');
    for (let i = 0; i < 15; i++) {
      cause = new Error('cause-' + (15 - i), { cause });
    }
    const input = new Error('outer', { cause });
    const out = sj.parse(sj.stringify(input)) as any;
    let depth = 0;
    let current = out.cause;
    while (current instanceof Error) {
      depth++;
      current = current.cause;
    }
    expect(depth).toBe(16);
  });

  it('provided errorStack with default includeCauses drops cause', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'string' } });
    const input = new Error('outer', { cause: new Error('inner') });
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.cause).toBeUndefined();
  });

  it('omitting errorStack keeps existing cause behavior', () => {
    const sj = new SuperJSON();
    const input = new Error('outer', { cause: new Error('inner') });
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.cause).toBeInstanceOf(Error);
    expect(out.cause.message).toBe('inner');
  });
});

describe('errorStack frames container round-trip', () => {
  it('round-trips container values inside stackFrames added by a processor', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stackFrames');
    sj.registerErrorStackProcessor('Error', (serialized) => {
      return {
        ...serialized,
        stackFrames: [
          ...serialized.stackFrames,
          { raw: 'custom', meta: new Date('2020-01-01T00:00:00.000Z') },
        ],
      };
    });
    const out = sj.parse(sj.stringify(new Error('boom'))) as any;
    expect(out.stackFrames[0]).toEqual({ raw: 'Error: boom' });
    expect(out.stackFrames[out.stackFrames.length - 1].meta).toBeInstanceOf(Date);
    expect(out.stackFrames[out.stackFrames.length - 1].meta.toISOString()).toBe(
      '2020-01-01T00:00:00.000Z'
    );
  });

  it('uses Error/frames annotation in meta', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stackFrames');
    const result = sj.serialize(new Error('boom'));
    expect((result.meta!.values as any)[0]).toBe('Error/frames');
  });
});

describe('errorStack off mode with other options', () => {
  it('off mode still honors includeCauses', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'off', includeCauses: 'direct' },
    });
    const input = new Error('outer', { cause: new Error('inner') });
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.cause).toBeInstanceOf(Error);
    expect(out.cause.message).toBe('inner');
  });

  it('off mode still honors sanitizeMessage', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'off', sanitizeMessage: true },
    });
    const input = new Error('see https://example.com');
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.message).toBe('see [redacted]');
  });
});

describe('errorStack processor edge cases', () => {
  it('runs on default instance without errorStack', () => {
    const sj = new SuperJSON();
    const seen: any[] = [];
    sj.registerErrorStackProcessor('Error', (serialized) => {
      seen.push(serialized);
      return serialized;
    });
    const out = sj.parse(sj.stringify(new Error('boom'))) as any;
    expect(out.message).toBe('boom');
    expect(seen).toHaveLength(1);
    expect(seen[0].name).toBe('Error');
    expect(seen[0].message).toBe('boom');
  });

  it('registers processors by class name only', () => {
    const sj = new SuperJSON();
    const seen: string[] = [];
    sj.registerErrorStackProcessor('TypeError', (serialized) => {
      seen.push(serialized.name);
      return serialized;
    });
    sj.parse(sj.stringify(new Error('plain')));
    expect(seen).toHaveLength(0);
    sj.parse(sj.stringify(new TypeError('typed')));
    expect(seen).toEqual(['TypeError']);
  });
});

describe('errorStack frames container types', () => {
  it('round-trips Map and Set values inside stackFrames', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stackFrames');
    sj.registerErrorStackProcessor('Error', (serialized) => {
      return {
        ...serialized,
        stackFrames: [
          ...serialized.stackFrames,
          { raw: 'map', map: new Map([['k', 'v']]) },
          { raw: 'set', set: new Set([1, 2]) },
        ],
      };
    });
    const out = sj.parse(sj.stringify(new Error('boom'))) as any;
    const frames = out.stackFrames;
    expect(frames[frames.length - 2].map).toBeInstanceOf(Map);
    expect(frames[frames.length - 2].map.get('k')).toBe('v');
    expect(frames[frames.length - 1].set).toBeInstanceOf(Set);
    expect([...frames[frames.length - 1].set]).toEqual([1, 2]);
  });
});

describe('errorStack cause sanitization', () => {
  it('sanitizes direct cause messages', () => {
    const sj = new SuperJSON({
      errorStack: {
        mode: 'string',
        includeCauses: 'direct',
        sanitizeMessage: true,
      },
    });
    const input = new Error('outer', {
      cause: new Error('email a@b.com'),
    });
    const out = sj.parse(sj.stringify(input)) as any;
    expect(out.cause.message).toBe('email [redacted]');
  });
});
