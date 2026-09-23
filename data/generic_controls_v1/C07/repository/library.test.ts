import { strict as assert } from "node:assert";
import { test } from "node:test";
import { Queue } from "./library.ts";
test("one front element", () => {
  const q = new Queue([1, 2]);
  assert.deepEqual(q.take(1), [1]);
  assert.deepEqual(q.remaining(), [2]);
});
test("short queue", () => {
  const q = new Queue([1]);
  assert.deepEqual(q.take(2), [1]);
});
test("same present observation", () => {
  assert.equal(new Queue([1]).peek(), 1);
  assert.equal(new Queue([1, 2]).peek(), 1);
});
