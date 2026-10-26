import { describe } from 'vitest';
import { fail, pass } from '../../test-utils';

describe('Statements - Using', () => {
  pass('Using (pass)', [
    // using declarations in blocks and function bodies
    { code: '{ using x = null; }', options: { next: true } },
    { code: 'function f() { using x = null; }', options: { next: true } },
    { code: '{ using x = null, y = null; }', options: { next: true } },
    // module top-level
    { code: 'using x = null;', options: { next: true, sourceType: 'module' } },
    { code: 'await using x = null;', options: { next: true, sourceType: 'module' } },
    { code: '{ await using x = null; }', options: { next: true, sourceType: 'module' } },
    // async function body
    { code: 'async function f() { await using x = null; }', options: { next: true } },
    // for-of and for-await-of heads
    { code: 'for (using x of []) {}', options: { next: true } },
    { code: 'for (using x of []) {}', options: { next: true, sourceType: 'module' } },
    { code: 'async function f() { for (await using x of []) {} }', options: { next: true } },
    { code: 'for (await using x of []) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for await (using x of []) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for await (await using x of []) {}', options: { next: true, sourceType: 'module' } },
    { code: 'for (using x = null;;) break;', options: { next: true } },
    { code: 'for (using of = null;;) break;', options: { next: true } },
    { code: 'async function f() { for (await using of of []) {} }', options: { next: true } },
    // a block inside a switch case is a valid container
    { code: 'function f() { switch (x) { case 1: { using y = null; } } }', options: { next: true } },
    // `using` remains usable as an identifier
    { code: 'using = 1;', options: { next: true, sourceType: 'module' } },
    { code: 'using = 1;', options: { sourceType: 'module' } },
    { code: '{ using[x] = null; }', options: { next: true } },
    { code: 'using\nx = 1;', options: { next: true } },
    // export
    { code: 'export using x = null;', options: { next: true, sourceType: 'module' } },
    { code: 'export await using x = null;', options: { next: true, sourceType: 'module' } },
  ]);

  fail('Using (fail)', [
    // script global scope
    { code: 'using x = null;', options: { next: true } },
    { code: 'using x = null;', options: { next: true, sourceType: 'commonjs' } },
    // await using outside async/module
    { code: 'await using x = null;', options: { next: true } },
    { code: 'await using x = null;', options: { next: true, sourceType: 'commonjs' } },
    { code: 'function f() { await using x = null; }', options: { next: true, sourceType: 'module' } },
    // missing initializer
    { code: '{ using x; }', options: { next: true } },
    { code: 'async function f() { await using x; }', options: { next: true } },
    // for-in is not allowed
    { code: 'for (using x in y) {}', options: { next: true } },
    { code: 'async function f() { for (await using x in y) {} }', options: { next: true } },
    // destructuring is not allowed
    { code: '{ using [a] = null; }', options: { next: true } },
    { code: '{ using [] = null; }', options: { next: true } },
    { code: '{ using {a} = null; }', options: { next: true } },
    { code: 'async function f() { await using [a] = null; }', options: { next: true } },
    { code: 'async function f() { await using [] = null; }', options: { next: true } },
    // switch case is not allowed
    { code: 'function f() { switch (x) { case 1: using y = null; } }', options: { next: true } },
    // `let` cannot be a using binding
    { code: '{ using let = null; }', options: { next: true } },
    { code: 'async function f() { await using let = null; }', options: { next: true } },
  ]);
});
