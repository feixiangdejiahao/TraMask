import { outdent } from 'outdent';
import { describe } from 'vitest';
import { fail, pass } from '../../test-utils';

describe('Statements - Using', () => {
  pass('Using declarations (pass)', [
    { code: 'using foo = null', options: { next: true, sourceType: 'module' } },
    { code: 'await using foo = null', options: { next: true, sourceType: 'module' } },
    { code: 'using foo = 1, bar = 2', options: { next: true, sourceType: 'module' } },
    { code: '{ using foo = null; }', options: { next: true } },
    { code: 'function f() { using x = 1; }', options: { next: true } },
    { code: 'async function f() { await using x = 1; }', options: { next: true } },
    { code: '{ await using x = y; }', options: { next: true, sourceType: 'module' } },
    { code: 'for (using x of y) {}', options: { next: true } },
    { code: 'for (using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for (await using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for await (using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for await (await using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'async function f() { for await (using x of y) {} }', options: { next: true } },
    { code: 'async function f() { for await (await using x of y) {} }', options: { next: true } },
    { code: 'function f() { for (using x = 0; ; ) {} }', options: { next: true } },
    { code: 'async function f() { for (await using x = 0; ; ) {} }', options: { next: true } },
    { code: 'function f() { for (using of = 0; ; ) {} }', options: { next: true } },
    { code: 'class C { static { using x = y; } }', options: { next: true } },
    // `using` and `await using` as regular identifiers when not followed by a binding on the same line
    { code: 'using = foo', options: { next: true } },
    { code: 'function f() { using(x); }', options: { next: true } },
    { code: 'using: foo', options: { next: true } },
    {
      code: outdent`
        using
        foo = null
      `,
      options: { next: true },
    },
    { code: 'function f() { for (using of y) {} }', options: { next: true } },
    { code: 'function f() { for (using in y) {} }', options: { next: true } },
  ]);

  fail('Using declarations (fail)', [
    { code: 'using foo = null', options: { next: true } },
    { code: 'using foo', options: { next: true } },
    { code: 'function f() { using foo; }', options: { next: true } },
    { code: 'async function f() { await using foo; }', options: { next: true } },
    { code: 'await using foo = null', options: { next: true } },
    { code: 'function f() { await using foo = null; }', options: { next: true } },
    { code: 'for (using x in y) {}', options: { next: true } },
    { code: 'for (using x in y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for (await using x in y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'function f() { using { x } = y; }', options: { next: true } },
    { code: 'using { x } = y', options: { next: true } },
    { code: 'function f() { using let = x; }', options: { next: true } },
    { code: 'class C { static { await using x = y; } }', options: { next: true } },
  ]);
});
