cd /app && cat > src/tmp-error-stack.test.ts <<'EOF'
import { describe, it, expect } from 'vitest';
import SuperJSON from './index.js';
import {
  normalizeErrorStackOptions,
} from './error-options.js';
import {
  processStackString,
  processStackFrames,
  normalizeStackNewlines,
} from './error-stack.js';
import { sanitizeMessage } from './error-sanitizer.js';

describe('tmp error stack', () => {
  it('basic string mode', () => {
    const sj = new SuperJSON({
      errorStack: {
        mode: 'string',
        maxStackLines: 3,
        stripInternalFrames: 'node',
      },
    });
    sj.allowErrorProps('stack');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)\n    at b (node:internal/x:1:1)\n    at c (/app/c.ts:3:3)';
    const res = sj.serialize({ e });
    console.log(JSON.stringify(res, null, 2));
    const out: any = sj.deserialize(res);
    console.log('deserialized stack:', JSON.stringify(out.e.stack));
    expect(out.e.stack).toBe('Error: hello\n    at a (/app/a.ts:1:1)\n    at c (/app/c.ts:3:3)');
  });

  it('frames mode', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'frames', maxStackLines: 3, stripInternalFrames: 'node' },
    });
    sj.allowErrorProps('stackFrames');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)\n    at b (node:internal/x:1:1)\n    at c (/app/c.ts:3:3)';
    const res = sj.serialize({ e });
    console.log(JSON.stringify(res, null, 2));
    const out: any = sj.deserialize(res);
    console.log('deserialized stackFrames:', JSON.stringify(out.e.stackFrames));
    expect(out.e.stackFrames).toEqual([
      { raw: 'Error: hello' },
      { raw: 'at a (/app/a.ts:1:1)' },
      { raw: 'at c (/app/c.ts:3:3)' },
    ]);
  });

  it('off mode never serializes stack even if allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    sj.allowErrorProps('stack');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\n    at a (/app/a.ts:1:1)';
    const res = sj.serialize({ e });
    const out: any = sj.deserialize(res);
    expect(out.e.stack).toBeUndefined();
  });

  it('normalizeErrorStackOptions', () => {
    expect(normalizeErrorStackOptions(undefined)).toBeUndefined();
    expect(normalizeErrorStackOptions(null)).toBeUndefined();
    expect(normalizeErrorStackOptions('x')).toBeUndefined();
    expect(normalizeErrorStackOptions({})!.mode).toBe('off');
    expect(normalizeErrorStackOptions({ mode: 'bogus' })!.mode).toBe('off');
    expect(normalizeErrorStackOptions({ mode: 'string', maxStackLines: 0 })!.mode).toBe('off');
    expect(normalizeErrorStackOptions({ mode: 'string', maxStackLines: 1.5 })!.mode).toBe('off');
    expect(normalizeErrorStackOptions({ includeCauses: 'deep', maxCauseDepth: 1.5 })!.includeCauses).toBe('none');
    expect(normalizeErrorStackOptions({ stripInternalFrames: 'bogus' })!.stripInternalFrames).toBe('none');
    expect(normalizeErrorStackOptions({ redactPaths: 'bogus' })!.redactPaths).toBe('none');
  });

  it('sanitizeMessage', () => {
    expect(sanitizeMessage('go to https://example.com/a?b=1 ok')).toBe('go to [redacted] ok');
    expect(sanitizeMessage('mail me at a.b@example.co.uk please')).toBe('mail me at [redacted] please');
    expect(sanitizeMessage('ip 192.168.1.1 here')).toBe('ip [redacted] here');
  });

  it('process functions', () => {
    const opts = normalizeErrorStackOptions({ mode: 'string', maxStackLines: 2 })!;
    const stack = 'Error: x\r\n    at a (/app/a.ts:1:1)\r\n    at b (/app/b.ts:2:2)\r\n    at c (/app/c.ts:3:3)';
    expect(normalizeStackNewlines(stack)).toBe('Error: x\n    at a (/app/a.ts:1:1)\n    at b (/app/b.ts:2:2)\n    at c (/app/c.ts:3:3)');
    expect(processStackString(stack, opts)).toBe('Error: x\n    at a (/app/a.ts:1:1)');
    expect(processStackFrames(stack, opts)).toEqual([
      { raw: 'Error: x' },
      { raw: 'at a (/app/a.ts:1:1)' },
    ]);
  });
});
EOF
npx vitest run src/tmp-error-stack.test.ts 2>&1 | tail -60