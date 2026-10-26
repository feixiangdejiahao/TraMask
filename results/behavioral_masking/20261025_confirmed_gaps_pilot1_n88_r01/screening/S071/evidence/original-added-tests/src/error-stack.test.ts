import { describe, expect, it } from 'vitest';
import SuperJSON from './index.js';
import {
  ErrorStackOptions,
  normalizeErrorStackOptions,
} from './error-options.js';
import {
  normalizeStackNewlines,
  processStackFrames,
  processStackString,
} from './error-stack.js';
import { sanitizeMessage } from './error-sanitizer.js';
import { ErrorClassRegistry } from './error-class-registry.js';

const normalize = (options: ErrorStackOptions) =>
  normalizeErrorStackOptions(options)!;

describe('normalizeErrorStackOptions', () => {
  it('returns undefined for non-object input', () => {
    expect(normalizeErrorStackOptions(undefined)).toBeUndefined();
    expect(normalizeErrorStackOptions(null)).toBeUndefined();
    expect(normalizeErrorStackOptions('string')).toBeUndefined();
    expect(normalizeErrorStackOptions(42)).toBeUndefined();
    expect(normalizeErrorStackOptions([])).toBeUndefined();
  });

  it('treats missing or invalid mode as off', () => {
    expect(normalizeErrorStackOptions({})!.mode).toBe('off');
    expect(normalizeErrorStackOptions({ mode: 'bogus' })!.mode).toBe('off');
    expect(normalizeErrorStackOptions({ mode: 1 })!.mode).toBe('off');
  });

  it('applies defaults', () => {
    const options = normalize({ mode: 'string' });
    expect(options.mode).toBe('string');
    expect(options.normalizeNewlines).toBe(false);
    expect(options.trimLeadingWhitespace).toBe(true);
    expect(options.maxStackLines).toBeUndefined();
    expect(options.stripInternalFrames).toBe('none');
    expect(options.redactPaths).toBe('none');
    expect(options.includeCauses).toBe('none');
    expect(options.maxCauseDepth).toBe(16);
    expect(options.sanitizeMessage).toBe(false);
    expect(options.classFilter).toEqual([]);
  });

  it('falls back to off for invalid maxStackLines', () => {
    expect(normalize({ mode: 'string', maxStackLines: 0 })!.mode).toBe('off');
    expect(normalize({ mode: 'string', maxStackLines: -3 })!.mode).toBe('off');
    expect(normalize({ mode: 'string', maxStackLines: 2.5 })!.mode).toBe(
      'off'
    );
    expect(normalize({ mode: 'string', maxStackLines: '5' })!.mode).toBe('off');
  });

  it('falls back to includeCauses=none for invalid maxCauseDepth', () => {
    expect(
      normalize({ includeCauses: 'deep', maxCauseDepth: 1.5 })!.includeCauses
    ).toBe('none');
    expect(
      normalize({ includeCauses: 'deep', maxCauseDepth: '4' })!.includeCauses
    ).toBe('none');
    expect(normalize({ includeCauses: 'deep' })!.maxCauseDepth).toBe(16);
  });

  it('falls back to none for unknown strip/redact values', () => {
    expect(normalize({ stripInternalFrames: 'bogus' })!.stripInternalFrames).toBe(
      'none'
    );
    expect(normalize({ redactPaths: 'bogus' })!.redactPaths).toBe('none');
  });

  it('normalizes classFilter', () => {
    expect(normalize({ classFilter: 'TypeError' })!.classFilter).toEqual([
      'TypeError',
    ]);
    expect(
      normalize({ classFilter: ['TypeError', 'Error'] })!.classFilter
    ).toEqual(['TypeError', 'Error']);
    expect(normalize({ classFilter: [] })!.classFilter).toEqual([]);
  });
});

describe('error-stack processing', () => {
  const stack =
    'Error: boom\n' +
    '    at alpha (/app/src/alpha.ts:1:1)\n' +
    '    at beta (node:internal/modules/run_main.js:1:1)\n' +
    '    at gamma (/app/src/transformer.ts:2:2)\n' +
    '    at delta (/app/src/delta.ts:3:3)';

  it('normalizeStackNewlines converts CRLF and CR to LF', () => {
    expect(normalizeStackNewlines('a\r\nb\rc')).toBe('a\nb\nc');
  });

  it('normalizeNewlines option controls CRLF/CR conversion', () => {
    const crlf = 'Error: boom\r\n    at a (/app/a.ts:1:1)\r\n    at b (/app/b.ts:2:2)\r';
    expect(processStackString(crlf, normalize({ mode: 'string' }))).toBe(
      'Error: boom\r\nat a (/app/a.ts:1:1)\r\nat b (/app/b.ts:2:2)\r'
    );
    expect(
      processStackString(
        crlf,
        normalize({ mode: 'string', normalizeNewlines: true })
      )
    ).toBe('Error: boom\nat a (/app/a.ts:1:1)\nat b (/app/b.ts:2:2)');
  });

  it('trims leading whitespace by default, preserves it when disabled', () => {
    const options = normalize({ mode: 'string' });
    expect(processStackString(stack, options)).toBe(
      'Error: boom\n' +
        'at alpha (/app/src/alpha.ts:1:1)\n' +
        'at beta (node:internal/modules/run_main.js:1:1)\n' +
        'at gamma (/app/src/transformer.ts:2:2)\n' +
        'at delta (/app/src/delta.ts:3:3)'
    );

    const untrimmed = normalize({ mode: 'string', trimLeadingWhitespace: false });
    expect(processStackString(stack, untrimmed)).toBe(
      'Error: boom\n' +
        '    at alpha (/app/src/alpha.ts:1:1)\n' +
        '    at beta (node:internal/modules/run_main.js:1:1)\n' +
        '    at gamma (/app/src/transformer.ts:2:2)\n' +
        '    at delta (/app/src/delta.ts:3:3)'
    );
  });

  it('maxStackLines counts the header line', () => {
    const options = normalize({ mode: 'string', maxStackLines: 2 });
    expect(processStackString(stack, options)).toBe(
      'Error: boom\nat alpha (/app/src/alpha.ts:1:1)'
    );
  });

  it('string mode applies maxStackLines before stripInternalFrames', () => {
    const options = normalize({
      mode: 'string',
      maxStackLines: 3,
      stripInternalFrames: 'node',
    });
    expect(processStackString(stack, options)).toBe(
      'Error: boom\nat alpha (/app/src/alpha.ts:1:1)'
    );
  });

  it('frames mode applies stripInternalFrames before maxStackLines', () => {
    const options = normalize({
      mode: 'frames',
      maxStackLines: 3,
      stripInternalFrames: 'node',
    });
    expect(processStackFrames(stack, options)).toEqual([
      { raw: 'Error: boom' },
      { raw: 'at alpha (/app/src/alpha.ts:1:1)' },
      { raw: 'at gamma (/app/src/transformer.ts:2:2)' },
    ]);
  });

  it('strips node internal frames', () => {
    const options = normalize({ mode: 'string', stripInternalFrames: 'node' });
    const output = processStackString(stack, options);
    expect(output).not.toContain('node:internal');
    expect(output).toContain('at alpha');
  });

  it('strips superjson internal frames', () => {
    const options = normalize({
      mode: 'string',
      stripInternalFrames: 'superjson',
    });
    const output = processStackString(stack, options);
    expect(output).not.toContain('src/transformer.ts');
    expect(output).toContain('at alpha');
    expect(output).toContain('at beta');
  });

  it('strips both node and superjson frames', () => {
    const options = normalize({
      mode: 'string',
      stripInternalFrames: 'node_and_superjson',
    });
    const output = processStackString(stack, options);
    expect(output).not.toContain('node:internal');
    expect(output).not.toContain('src/transformer.ts');
    expect(output).toContain('at delta');
  });

  it('never removes the header line', () => {
    const options = normalize({
      mode: 'string',
      stripInternalFrames: 'node_and_superjson',
      maxStackLines: 1,
    });
    expect(processStackString(stack, options)).toBe('Error: boom');
    expect(processStackFrames(stack, options)).toEqual([{ raw: 'Error: boom' }]);
  });

  it('redacts paths to basenames', () => {
    const options = normalize({ mode: 'string', redactPaths: 'basename' });
    expect(processStackString(stack, options)).toBe(
      'Error: boom\n' +
        'at alpha (alpha.ts:1:1)\n' +
        'at beta (run_main.js:1:1)\n' +
        'at gamma (transformer.ts:2:2)\n' +
        'at delta (delta.ts:3:3)'
    );
  });

  it('removes the cwd prefix', () => {
    const options = normalize({ mode: 'string', redactPaths: 'strip_cwd' });
    const output = processStackString(stack, options);
    expect(output).not.toContain(process.cwd());
    expect(output).toContain('at alpha (/src/alpha.ts:1:1)');
  });

  it('frames output starts with the header as the first raw entry', () => {
    const options = normalize({ mode: 'frames' });
    const frames = processStackFrames(stack, options);
    expect(frames[0]).toEqual({ raw: 'Error: boom' });
    expect(frames.length).toBe(5);
  });

  it('accepts raw (non-normalized) options', () => {
    const raw = { mode: 'string', maxStackLines: 2 } as ErrorStackOptions;
    expect(processStackString(stack, raw)).toBe(
      'Error: boom\nat alpha (/app/src/alpha.ts:1:1)'
    );
    const rawFrames = { mode: 'frames', maxStackLines: 2 } as ErrorStackOptions;
    expect(processStackFrames(stack, rawFrames)).toEqual([
      { raw: 'Error: boom' },
      { raw: 'at alpha (/app/src/alpha.ts:1:1)' },
    ]);
  });
});

describe('sanitizeMessage', () => {
  it('redacts URLs, emails, and IPv4 addresses', () => {
    expect(
      sanitizeMessage('see https://example.com/path?q=1 and http://a.b')
    ).toBe('see [redacted] and [redacted]');
    expect(sanitizeMessage('contact john.doe@example.co.uk now')).toBe(
      'contact [redacted] now'
    );
    expect(sanitizeMessage('server at 192.168.1.1 is down')).toBe(
      'server at [redacted] is down'
    );
  });
});

describe('ErrorClassRegistry', () => {
  it('registers, checks and retrieves processors', () => {
    const registry = new ErrorClassRegistry();
    const fn = () => ({});
    expect(registry.has('Error')).toBe(false);
    expect(registry.getProcessor('Error')).toBeUndefined();
    registry.register('Error', fn);
    expect(registry.has('Error')).toBe(true);
    expect(registry.getProcessor('Error')).toBe(fn);
  });
});

describe('SuperJSON error stack integration', () => {
  it('keeps existing behavior when errorStack is omitted', () => {
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';

    const withoutAllow = SuperJSON.parse(SuperJSON.stringify(e)) as any;
    expect(withoutAllow.stack).toBeUndefined();

    const sj = new SuperJSON();
    sj.allowErrorProps('stack');
    const withAllow = sj.parse(sj.stringify(e)) as any;
    expect(withAllow.stack).toBe(e.stack);
  });

  it('off mode never serializes stack even when allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    sj.allowErrorProps('stack');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stack).toBeUndefined();
  });

  it('off mode never serializes stackFrames even when allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    sj.allowErrorProps('stackFrames');
    const e: any = new Error('hello');
    e.stackFrames = [{ raw: 'Error: hello' }];
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stackFrames).toBeUndefined();
  });

  it('string mode does not serialize stackFrames', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'string' } });
    sj.allowErrorProps('stack', 'stackFrames');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';
    e.stackFrames = [{ raw: 'should not appear' }];
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stack).toBe('Error: hello\nat a (/app/a.ts:1:1)');
    expect(out.stackFrames).toBeUndefined();
  });

  it('frames mode does not serialize stack', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stack', 'stackFrames');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stackFrames).toEqual([
      { raw: 'Error: hello' },
      { raw: 'at a (/app/a.ts:1:1)' },
    ]);
    expect(out.stack).toBeUndefined();
  });

  it('string mode serializes and restores a processed stack', () => {
    const sj = new SuperJSON({
      errorStack: {
        mode: 'string',
        maxStackLines: 2,
        trimLeadingWhitespace: false,
      },
    });
    sj.allowErrorProps('stack');
    const e: any = new Error('hello');
    e.stack =
      'Error: hello\n    at a (/app/a.ts:1:1)\n    at b (/app/b.ts:2:2)';

    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stack).toBe('Error: hello\n    at a (/app/a.ts:1:1)');
  });

  it('frames mode serializes and restores stackFrames', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stackFrames');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)\n    at b (/app/b.ts:2:2)';

    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stackFrames).toEqual([
      { raw: 'Error: hello' },
      { raw: 'at a (/app/a.ts:1:1)' },
      { raw: 'at b (/app/b.ts:2:2)' },
    ]);
  });

  it('classFilter restricts processing to matching error names', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', classFilter: ['TypeError'] },
    });
    sj.allowErrorProps('stack');
    const plain: any = new Error('plain');
    plain.stack = 'Error: plain\n    at a (/app/a.ts:1:1)';
    const type: any = new TypeError('type');
    type.stack = 'TypeError: type\n    at a (/app/a.ts:1:1)';

    const out = sj.parse(sj.stringify({ plain, type })) as any;
    expect(out.plain.stack).toBeUndefined();
    expect(out.type.stack).toBe('TypeError: type\nat a (/app/a.ts:1:1)');
  });

  it('empty classFilter means all errors', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', classFilter: [] },
    });
    sj.allowErrorProps('stack');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stack).toBe('Error: hello\nat a (/app/a.ts:1:1)');
  });

  it('includeCauses direct keeps the immediate cause', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'direct' },
    });
    sj.allowErrorProps('stack');
    const e = new Error('outer', { cause: new Error('inner') });
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.cause).toBeInstanceOf(Error);
    expect(out.cause.message).toBe('inner');
    expect('cause' in out.cause).toBe(false);
  });

  it('includeCauses deep keeps causes up to maxCauseDepth', () => {
    const sj = new SuperJSON({
      errorStack: {
        mode: 'string',
        includeCauses: 'deep',
        maxCauseDepth: 2,
      },
    });
    sj.allowErrorProps('stack');
    const e = new Error('1', { cause: new Error('2', { cause: new Error('3') }) });
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.cause.message).toBe('2');
    expect(out.cause.cause.message).toBe('3');
    expect('cause' in out.cause.cause).toBe(false);
  });

  it('drops non-Error causes', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'deep' },
    });
    sj.allowErrorProps('stack');
    const e: any = new Error('outer');
    e.cause = 'not an error';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.cause).toBeUndefined();
  });

  it('drops non-Error causes in direct mode', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'direct' },
    });
    sj.allowErrorProps('stack');
    const e: any = new Error('outer');
    e.cause = 'not an error';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.cause).toBeUndefined();
  });

  it('round-trips AggregateError when errorStack is configured in off mode', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    const e = new AggregateError([new Error('one')], 'agg');
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.name).toBe('AggregateError');
    expect(out.errors).toHaveLength(1);
    expect(out.errors[0].message).toBe('one');
  });

  it('still copies non-stack allowed props in off mode', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    sj.allowErrorProps('code');
    const e: any = new Error('hello');
    e.code = 'P2002';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.code).toBe('P2002');
    expect(out.stack).toBeUndefined();
  });

  it('uses Error/stack rule even when stack is not allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'string' } });
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';
    const res = sj.serialize({ e });
    expect((res.meta!.values as any).e).toEqual(['Error/stack']);
    const out = sj.deserialize(res) as any;
    expect(out.e.stack).toBeUndefined();
  });

  it('uses the correct annotation per mode', () => {
    const off = new SuperJSON({ errorStack: { mode: 'off' } });
    const string = new SuperJSON({ errorStack: { mode: 'string' } });
    string.allowErrorProps('stack');
    const frames = new SuperJSON({ errorStack: { mode: 'frames' } });
    frames.allowErrorProps('stackFrames');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';

    const offRes = off.serialize({ e });
    expect((offRes.meta!.values as any).e).toEqual(['Error']);

    const stringRes = string.serialize({ e });
    expect((stringRes.meta!.values as any).e).toEqual(['Error/stack']);

    const framesRes = frames.serialize({ e });
    expect((framesRes.meta!.values as any).e).toEqual(['Error/frames']);
  });

  it('round-trips AggregateError in frames mode', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stackFrames');
    const e: any = new AggregateError(
      [new Error('one'), new TypeError('two')],
      'agg'
    );
    e.stack = 'AggregateError: agg\n    at a (/app/a.ts:1:1)';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.errors).toHaveLength(2);
    expect(out.errors[0].message).toBe('one');
    expect(out.stackFrames[0]).toEqual({ raw: 'AggregateError: agg' });
  });

  it('round-trips an AggregateError as a deep cause', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'deep', maxCauseDepth: 2 },
    });
    sj.allowErrorProps('stack');
    const e = new Error('outer', {
      cause: new AggregateError([new Error('inner')], 'aggregated'),
    });
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.cause).toBeInstanceOf(Error);
    expect(out.cause.name).toBe('AggregateError');
    expect(out.cause.errors).toHaveLength(1);
    expect(out.cause.errors[0].message).toBe('inner');
  });

  it('stops cleanly on circular cause chains', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'deep', maxCauseDepth: 3 },
    });
    sj.allowErrorProps('stack');
    const e: any = new Error('outer');
    e.cause = e;
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.cause).toBeDefined();
  });

  it('sanitizes the error message and every kept cause message', () => {
    const sj = new SuperJSON({
      errorStack: {
        mode: 'string',
        sanitizeMessage: true,
        includeCauses: 'deep',
        maxCauseDepth: 2,
      },
    });
    sj.allowErrorProps('stack');
    const e = new Error('visit https://example.com', {
      cause: new Error('mail a@b.com'),
    });
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.message).toBe('visit [redacted]');
    expect(out.cause.message).toBe('mail [redacted]');
  });

  it('serializes AggregateError errors as-is and restores them', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'string' } });
    sj.allowErrorProps('stack');
    const e = new AggregateError([new Error('one'), new TypeError('two')], 'agg');
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.name).toBe('AggregateError');
    expect(out.message).toBe('agg');
    expect(out.errors).toHaveLength(2);
    expect(out.errors[0]).toBeInstanceOf(Error);
    expect(out.errors[0].message).toBe('one');
    expect(out.errors[1].name).toBe('TypeError');
  });

  it('runs registerErrorStackProcessor after all serialization steps', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', sanitizeMessage: true, maxStackLines: 2 },
    });
    sj.allowErrorProps('stack');
    sj.registerErrorStackProcessor('Error', (serialized) => {
      expect(serialized.message).toBe('visit [redacted]');
      expect(serialized.stack).toContain('Error: visit https://example.com');
      return { ...serialized, extra: 'added' };
    });
    const e: any = new Error('visit https://example.com');
    e.stack = 'Error: visit https://example.com\n    at a (/app/a.ts:1:1)\n    at b (/app/b.ts:2:2)';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.extra).toBe('added');
    expect(out.message).toBe('visit [redacted]');
  });

  it('runs the processor once for the top-level error, not for causes', () => {
    const sj = new SuperJSON({
      errorStack: {
        mode: 'string',
        includeCauses: 'deep',
        maxCauseDepth: 3,
      },
    });
    sj.allowErrorProps('stack');
    let calls = 0;
    sj.registerErrorStackProcessor('Error', (serialized) => {
      calls++;
      return serialized;
    });
    const e = new Error('outer', { cause: new Error('inner') });
    sj.serialize(e);
    expect(calls).toBe(1);
  });

  it('does not run the processor for non-matching classes', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', classFilter: ['TypeError'] },
    });
    sj.allowErrorProps('stack');
    let calls = 0;
    sj.registerErrorStackProcessor('Error', () => {
      calls++;
      return {};
    });
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';
    sj.serialize(e);
    expect(calls).toBe(0);
  });

  it('round-trips container types inside stackFrames', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stackFrames');
    sj.registerErrorStackProcessor('Error', (serialized) => ({
      ...serialized,
      stackFrames: [
        { raw: 'Error: hello', date: new Date(2020, 1, 1) },
        ...serialized.stackFrames.slice(1),
      ],
    }));
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stackFrames[0].date).toBeInstanceOf(Date);
    expect(out.stackFrames[0].date.getTime()).toBe(new Date(2020, 1, 1).getTime());
  });
});
