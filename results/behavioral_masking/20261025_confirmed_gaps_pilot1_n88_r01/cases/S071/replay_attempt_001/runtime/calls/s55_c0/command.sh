cd /app && npm run build >/dev/null 2>&1 && cat > /tmp/e2e.mjs <<'EOF'
import SuperJSON, { registerErrorStackProcessor, ErrorStackOptions } from '/app/dist/index.js';
import { processStackString, processStackFrames, normalizeStackNewlines } from '/app/dist/error-stack.js';
import { normalizeErrorStackOptions } from '/app/dist/error-options.js';
import { sanitizeMessage } from '/app/dist/error-sanitizer.js';
import { ErrorClassRegistry } from '/app/dist/error-class-registry.js';

const sj = new SuperJSON({
  errorStack: {
    mode: 'string',
    normalizeNewlines: true,
    maxStackLines: 3,
    stripInternalFrames: 'node_and_superjson',
    redactPaths: 'basename',
    includeCauses: 'deep',
    maxCauseDepth: 2,
    sanitizeMessage: true,
  },
});
sj.allowErrorProps('stack');
const e = new Error('boom at https://example.com and 1.2.3.4', {
  cause: new Error('inner cause'),
});
e.stack = 'Error: boom at https://example.com\n    at foo (/app/src/foo.ts:1:1)\n    at bar (node:internal/x:1:1)\n    at baz (/app/src/transformer.ts:2:2)\n    at qux (/app/src/qux.ts:3:3)';
const res = sj.serialize({ e });
console.log(JSON.stringify(res, null, 2));
const out = sj.deserialize(res);
console.log('message:', out.e.message);
console.log('stack:', JSON.stringify(out.e.stack));
console.log('cause:', out.e.cause && out.e.cause.message);
console.log('cause stack:', out.e.cause && out.e.cause.stack);

// frames
const sjf = new SuperJSON({ errorStack: { mode: 'frames', maxStackLines: 2 } });
sjf.allowErrorProps('stackFrames');
const ef = new Error('frames');
ef.stack = 'Error: frames\n    at a (/app/a.ts:1:1)\n    at b (/app/b.ts:2:2)';
const outf = sjf.deserialize(sjf.serialize({ ef }));
console.log('frames:', JSON.stringify(outf.ef.stackFrames));

// util exports
console.log('normalizeStackNewlines:', JSON.stringify(normalizeStackNewlines('a\r\nb')));
console.log('processStackString:', JSON.stringify(processStackString('E: x\n  at a (/a.ts:1:1)', { mode: 'string', maxStackLines: 2 })));
console.log('processStackFrames:', JSON.stringify(processStackFrames('E: x\n  at a (/a.ts:1:1)', { mode: 'frames', maxStackLines: 2 })));
console.log('sanitizeMessage:', sanitizeMessage('https://x.com a@b.com 10.0.0.1'));
console.log('normalizeErrorStackOptions undefined:', normalizeErrorStackOptions(null));
const reg = new ErrorClassRegistry();
const fn = (o) => ({ ...o, x: 1 });
reg.register('Error', fn);
console.log('registry:', reg.has('Error'), reg.getProcessor('Error') === fn);
console.log('static register:', typeof registerErrorStackProcessor);
console.log('ErrorStackOptions type present:', typeof ErrorStackOptions);
EOF
node /tmp/e2e.mjs