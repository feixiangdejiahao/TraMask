import { strict as assert } from "node:assert";
import { test } from "node:test";
import { summarize } from "./library.ts";
test("count", () => {
  assert.equal(summarize([1, 2]).count, 2);
  assert.equal(summarize([2, 1]).count, 2);
});
test("first", () => {
  assert.equal(summarize([1, 2]).first, 1);
});
test("empty", () => {
  assert.deepEqual(summarize([]), { count: 0, first: null });
});
