import assert from "node:assert/strict";
import { test } from "node:test";

import { parseRoute, pathFor, pathForRecord } from "../../src/router.js";

const ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

test("the known pages are recognised, with or without a trailing slash", () => {
  assert.deepEqual(parseRoute("/"), { name: "search", params: {} });
  assert.deepEqual(parseRoute("/review"), { name: "queue", params: {} });
  assert.deepEqual(parseRoute("/review/"), { name: "queue", params: {} });
  assert.deepEqual(parseRoute("/upload"), { name: "upload", params: {} });
});

test("a document's review page carries the document id", () => {
  assert.deepEqual(parseRoute(`/documents/${ID}/review`), { name: "review", params: { documentId: ID } });
});

test("every Ship, Organisation and Document has a permanent address of its own", () => {
  assert.deepEqual(parseRoute(`/ships/${ID}`), { name: "ship", params: { id: ID } });
  assert.deepEqual(parseRoute(`/organisations/${ID}`), { name: "organisation", params: { id: ID } });
  assert.deepEqual(parseRoute(`/documents/${ID}`), { name: "document", params: { id: ID } });
  assert.deepEqual(parseRoute(`/documents/${ID}/`), { name: "document", params: { id: ID } });
  assert.deepEqual(parseRoute(`/ships/${ID}?q=vega#names`), { name: "ship", params: { id: ID } });
});

test("the public search page keeps its query in the address without changing which page it is", () => {
  assert.equal(parseRoute("/?q=vega&verified_only=1&page=2").name, "search");
});

test("anything else is not found, including ids that are not ids", () => {
  for (const path of ["/nope", "/documents/not-an-id", "/ships/", "/ships/not-an-id", `/ships/${ID}/extra`, `/boats/${ID}`, "/documents/not-an-id/review", "/documents//review", "/review/extra"]) {
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
  assert.equal(pathFor("search"), "/");
  assert.equal(pathFor("ship", { id: ID }), `/ships/${ID}`);
  assert.equal(pathFor("organisation", { id: ID }), `/organisations/${ID}`);
  assert.equal(pathFor("document", { id: ID }), `/documents/${ID}`);
  for (const [name, params] of [["search", {}], ["queue", {}], ["upload", {}], ["review", { documentId: ID }], ["ship", { id: ID }], ["organisation", { id: ID }], ["document", { id: ID }]]) {
    assert.deepEqual(parseRoute(pathFor(name, params)), { name, params });
  }
});

test("a Subject's address follows from its kind", () => {
  assert.equal(pathForRecord("ship", ID), `/ships/${ID}`);
  assert.equal(pathForRecord("organisation", ID), `/organisations/${ID}`);
  assert.equal(pathForRecord("document", ID), `/documents/${ID}`);
  assert.throws(() => pathForRecord("boat", ID));
});
