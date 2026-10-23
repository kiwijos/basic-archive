import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, createSearchApi } from "../../src/api.js";
import { parseSearch } from "../../src/search-state.js";

const ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

const json = (status, body, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

function network(...answers) {
  const calls = [];
  return {
    calls,
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      const next = answers.shift();
      if (next instanceof Error) throw next;
      return next;
    },
  };
}

test("a search asks the API for exactly what the address describes, with a relative path and no credentials", async () => {
  const net = network(json(200, { hits: [], total: 0 }));
  const api = createSearchApi({ fetch: net.fetch });

  await api.search(parseSearch("?q=Vega&verified_only=1&ship_type=barque"));

  assert.equal(net.calls[0].url, "/api/search/documents?q=Vega&verified_only=true&ship_type=barque&page=1&page_size=20");
  assert.equal(net.calls[0].options.headers?.Authorization, undefined);
});

test("Subjects are searched in their own place", async () => {
  const net = network(json(200, { hits: [] }));

  await createSearchApi({ fetch: net.fetch }).search(parseSearch("?scope=subjects&q=vega"));

  assert.equal(net.calls[0].url, "/api/search/subjects?q=vega&page=1&page_size=20");
});

test("suggestions and landing records have their own addresses, and ids and words are encoded", async () => {
  const net = network(json(200, { suggestions: [] }), json(200, { id: ID }), json(200, { id: ID }), json(200, { id: ID }));
  const api = createSearchApi({ fetch: net.fetch });

  await api.suggest("Nord & Söner");
  await api.document(ID);
  await api.ship(ID);
  await api.organisation(ID);

  assert.deepEqual(net.calls.map((c) => c.url), [
    "/api/search/suggest?q=Nord+%26+S%C3%B6ner",
    `/api/search/documents/${ID}`,
    `/api/search/subjects/${ID}`,
    `/api/search/subjects/${ID}`,
  ]);
});

test("a page that does not exist is told apart from a search that failed", async () => {
  const api = createSearchApi({ fetch: network(json(404, { detail: "Not found" })).fetch });

  await assert.rejects(api.document(ID), (error) => error instanceof ApiError && error.status === 404 && /does not exist/i.test(error.message));
});

test("asking too often says how long to wait", async () => {
  const api = createSearchApi({ fetch: network(json(429, { detail: "Too many requests" }, { "Retry-After": "12" })).fetch });

  await assert.rejects(api.search(parseSearch("")), (error) => error.status === 429 && /12 seconds/.test(error.message));
});

test("a search that is unavailable or unreachable says so without blaming the visitor", async () => {
  const unavailable = createSearchApi({ fetch: network(json(503, { detail: "Search is not available right now" })).fetch });
  const unreachable = createSearchApi({ fetch: network(new TypeError("fetch failed")).fetch });

  await assert.rejects(unavailable.search(parseSearch("")), /not available right now/i);
  await assert.rejects(unreachable.search(parseSearch("")), (error) => error.status === 0 && /could not reach/i.test(error.message));
});

test("a bad request is explained from what the API said", async () => {
  const api = createSearchApi({ fetch: network(json(422, { detail: [{ loc: ["query", "year_from"], msg: "Input should be greater than or equal to 1" }] })).fetch });

  await assert.rejects(api.search(parseSearch("")), /year_from.*greater than or equal to 1/);
});

test("the API can sit behind a prefix without the pages knowing the host", async () => {
  const net = network(json(200, { hits: [] }));

  await createSearchApi({ fetch: net.fetch, base: "/archive" }).search(parseSearch(""));

  assert.equal(net.calls[0].url, "/archive/api/search/documents?page=1&page_size=20");
});
