import { describe } from 'vitest';
import { fail, pass } from '../../test-utils';

describe('Using declarations', () => {
  pass('Using declarations (pass)', [
    { code: 'using foo = null', options: { next: true, sourceType: 'module' } },
    { code: 'function f() { using foo = null; }', options: { next: true } },
    { code: 'function f() { using a = 1, b = 2; }', options: { next: true } },
    { code: '{ using foo = null; }', options: { next: true } },
    { code: 'class A { static { using x = 1; } }', options: { next: true } },
    { code: 'async function f() { await using foo = null; }', options: { next: true } },
    { code: 'await using foo = null', options: { next: true, sourceType: 'module' } },
    { code: '{ await using foo = null; }', options: { next: true, sourceType: 'module' } },
    { code: 'async () => { await using foo = null; }', options: { next: true } },
    // using / await using in for-of heads
    { code: 'for (using x of y) {}', options: { next: true } },
    { code: 'for (using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'async function f() { for (await using x of y) {} }', options: { next: true } },
    { code: 'for (await using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'async function f() { for await (using x of y) {} }', options: { next: true } },
    { code: 'async function f() { for await (await using x of y) {} }', options: { next: true } },
    { code: 'for await (using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for await (await using x of y) {}', options: { next: true, sourceType: 'module' } },
    // A line break after `using` means `using` is an identifier
    { code: 'using\nfoo = 1', options: { next: true } },
    // `using` remains usable as an identifier
    { code: 'var using = 1;', options: { next: true } },
    { code: 'using = 5', options: { next: true } },
    { code: 'using(foo)', options: { next: true } },
  ]);

  fail('Using declarations (fail)', [
    // Script global scope
    { code: 'using foo = null', options: { next: true } },
    { code: 'using foo = null', options: { next: true, sourceType: 'commonjs' } },
    // await using outside async/module context
    { code: 'await using foo = null', options: { next: true } },
    { code: 'function f() { await using foo = null; }', options: { next: true } },
    { code: 'class A { static { await using x = 1; } }', options: { next: true } },
    { code: 'for (await using x of y) {}', options: { next: true } },
    // Missing initializer
    { code: 'function f() { using foo; }', options: { next: true } },
    { code: 'function f() { await using foo; }', options: { next: true } },
    // For-in loops
    { code: 'function f() { for (using x in y) {} }', options: { next: true } },
    { code: 'for (using x in y) {}', options: { next: true, sourceType: 'module' } },
    // Destructuring patterns
    { code: 'function f() { using [a] = b; }', options: { next: true } },
    { code: 'function f() { using { a } = b; }', options: { next: true } },
  ]);
});
