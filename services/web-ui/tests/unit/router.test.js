import assert from "node:assert/strict";
import { test } from "node:test";

import { parseRoute, pathFor } from "../../src/router.js";

const ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

test("the known pages are recognised, with or without a trailing slash", () => {
  assert.deepEqual(parseRoute("/"), { name: "home", params: {} });
  assert.deepEqual(parseRoute("/review"), { name: "queue", params: {} });
  assert.deepEqual(parseRoute("/review/"), { name: "queue", params: {} });
  assert.deepEqual(parseRoute("/upload"), { name: "upload", params: {} });
});

test("a document's review page carries the document id", () => {
  assert.deepEqual(parseRoute(`/documents/${ID}/review`), { name: "review", params: { documentId: ID } });
});

test("anything else is not found, including ids that are not ids", () => {
  for (const path of ["/nope", `/documents/${ID}`, "/documents/not-an-id/review", "/documents//review", "/review/extra"]) {
    assert.equal(parseRoute(path).name, "notFound", path);
  }
});

test("a query string or fragment does not change which page it is", () => {
  assert.equal(parseRoute("/review?x=1").name, "queue");
  assert.equal(parseRoute("/upload#top").name, "upload");
});

test("paths are built from the same names the router understands", () => {
  assert.equal(pathFor("queue"), "/review");
  assert.equal(pathFor("upload"), "/upload");
  assert.equal(pathFor("review", { documentId: ID }), `/documents/${ID}/review`);
  for (const [name, params] of [["queue", {}], ["upload", {}], ["review", { documentId: ID }]]) {
    assert.deepEqual(parseRoute(pathFor(name, params)), { name, params });
  }
});
