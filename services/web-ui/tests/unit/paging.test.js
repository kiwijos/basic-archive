import assert from "node:assert/strict";
import { test } from "node:test";
import { pageFromQuery, pageRequest, pageResult } from "../../src/paging.js";

test("the first page asks for one extra entry, to learn whether another page follows", () => {
  assert.deepEqual(pageRequest(1, 50), { limit: 51, offset: 0 });
  assert.deepEqual(pageRequest(3, 50), { limit: 51, offset: 100 });
});

test("a full page with something after it has a next page", () => {
  const entries = Array.from({ length: 51 }, (_, index) => index);
  const result = pageResult(entries, 2, 50);
  assert.equal(result.entries.length, 50);
  assert.equal(result.hasNext, true);
  assert.equal(result.hasPrevious, true);
});

test("exactly a full page, with nothing after it, is the last page", () => {
  const result = pageResult(Array.from({ length: 50 }, (_, index) => index), 1, 50);
  assert.equal(result.entries.length, 50);
  assert.equal(result.hasNext, false);
  assert.equal(result.hasPrevious, false);
});

test("the page number comes from the query string and falls back to 1 when it makes no sense", () => {
  assert.equal(pageFromQuery("?page=3"), 3);
  assert.equal(pageFromQuery(""), 1);
  assert.equal(pageFromQuery("?page=0"), 1);
  assert.equal(pageFromQuery("?page=-2"), 1);
  assert.equal(pageFromQuery("?page=abc"), 1);
  assert.equal(pageFromQuery("?page=2.5"), 1);
  assert.equal(pageFromQuery("?page=99999999999"), 1);
});
