import { describe } from 'vitest';
import { fail, pass } from '../../test-utils';

describe('Next - Using declarations', () => {
  pass('Next - Using declarations (pass)', [
    // using declarations
    { code: 'using x = 1;', options: { next: true, sourceType: 'module' } },
    { code: 'using x = 1, y = 2;', options: { next: true, sourceType: 'module' } },
    { code: '{ using x = 1; }', options: { next: true } },
    { code: '{ using x = 1; }', options: { next: true, sourceType: 'commonjs' } },
    { code: 'function f(){ using x = 1; }', options: { next: true } },
    { code: 'switch (x) { case 1: using y = 1; }', options: { next: true } },
    { code: 'class C { static { using x = 1; } }', options: { next: true } },

    // await using declarations
    { code: 'await using x = 1;', options: { next: true, sourceType: 'module' } },
    { code: '{ await using x = 1; }', options: { next: true, sourceType: 'module' } },
    { code: 'async function f(){ await using x = 1; }', options: { next: true } },
    { code: 'async () => { await using x = 1; }', options: { next: true } },

    // using / await using in for-of / for-await-of heads
    { code: 'for (using x of y) {}', options: { next: true } },
    { code: 'for (using x of y) {}', options: { next: true, sourceType: 'commonjs' } },
    { code: 'for await (using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for (await using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for await (await using x of y) {}', options: { next: true, sourceType: 'module' } },
    { code: 'async function f(){ for (await using x of y) {} }', options: { next: true } },
    { code: 'async function f(){ for await (using x of y) {} }', options: { next: true } },
    { code: 'async function f(){ for await (await using x of y) {} }', options: { next: true } },

    // `using` is a contextual keyword and may be used as an identifier
    { code: 'for (using of y) {}', options: { next: true } },
    { code: 'using;', options: { next: true } },
    { code: 'using = 1;', options: { next: true } },
    { code: 'using => 1;', options: { next: true } },
    { code: 'let using = 1;', options: { next: true } },
    { code: 'obj.using; using.foo;', options: { next: true } },
    { code: 'using: for(;;) break using;', options: { next: true } },
    // A line terminator between `using` and the binding means `using` is an identifier
    { code: 'using\nx = 1;', options: { next: true } },
  ]);

  fail('Next - Using declarations (fail)', [
    // Script global scope
    { code: 'using x = 1;', options: { next: true } },
    { code: 'using x = 1;', options: { next: true, sourceType: 'commonjs' } },
    // await using outside async / module
    { code: 'await using x = 1;', options: { next: true } },
    { code: 'function f(){ await using x = 1; }', options: { next: true, sourceType: 'module' } },
    { code: 'for (await using x of y) {}', options: { next: true } },
    { code: 'class C { static { await using x = 1; } }', options: { next: true, sourceType: 'module' } },
    // Missing initializer
    { code: 'using x;', options: { next: true, sourceType: 'module' } },
    { code: '{ using x; }', options: { next: true } },
    { code: 'await using x;', options: { next: true, sourceType: 'module' } },
    // Destructuring patterns
    { code: '{ using {a} = x; }', options: { next: true } },
    { code: '{ using [a] = x; }', options: { next: true } },
    { code: 'for (using {a} of y) {}', options: { next: true } },
    // for-in
    { code: 'for (using x in y) {}', options: { next: true } },
    { code: 'for (await using x in y) {}', options: { next: true, sourceType: 'module' } },
    // escaped `using` is not a declaration keyword
    { code: String.raw`\u0075sing x = 1;`, options: { next: true, sourceType: 'module' } },
  ]);
});
