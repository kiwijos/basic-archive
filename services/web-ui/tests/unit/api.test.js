import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, createApi, describeFailure } from "../../src/api.js";

const ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

function json(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** A fetch that answers from a queue and remembers what it was asked. */
function fakeNetwork(...answers) {
  const calls = [];
  const fetch = async (url, options = {}) => {
    calls.push({ url, options });
    const next = answers.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  return { fetch, calls };
}

function clientFor(network, { token = "secret-token" } = {}) {
  const signedOut = [];
  const api = createApi({ fetch: network.fetch, getToken: () => token, onUnauthorized: (message) => signedOut.push(message) });
  return { api, signedOut };
}

test("failures become messages a person can act on", () => {
  assert.match(describeFailure(401, {}), /token was not accepted/i);
  assert.equal(describeFailure(413, { detail: "The file is larger than the 100 byte limit" }), "The file is larger than the 100 byte limit");
  assert.match(describeFailure(415, { detail: "Only TIFF, JPEG and PNG files are accepted. Convert PDF and HEIC files first." }), /PDF and HEIC/);
  assert.equal(describeFailure(404, { detail: "Image not found" }), "Image not found");
  assert.equal(describeFailure(409, { detail: "This Image is verified" }), "This Image is verified");
  assert.match(describeFailure(502, { detail: "Object storage is unavailable" }), /file store is not available/i);
  assert.match(describeFailure(500, { detail: "Internal server error" }), /problem.*500/i);
  assert.match(describeFailure(0, null), /could not reach the archive/i);
});

test("a validation failure names the field and the problem", () => {
  const body = { detail: [{ loc: ["body", "title"], msg: "Field required" }] };

  assert.equal(describeFailure(422, body), "title: Field required");
});

test("an error body that is not JSON is still described", () => {
  assert.match(describeFailure(500, "Internal Server Error"), /problem/i);
  assert.match(describeFailure(503, undefined), /problem/i);
});

test("every call carries the token and goes to the catalog API", async () => {
  const network = fakeNetwork(json(200, { name: "alice" }), json(200, []));
  const { api } = clientFor(network);

  await api.me();
  await api.reviewQueue({ limit: 20, offset: 40 });

  assert.equal(network.calls[0].url, "/api/catalog/me");
  assert.equal(network.calls[1].url, "/api/catalog/review-queue?limit=20&offset=40");
  for (const call of network.calls) assert.equal(call.options.headers.Authorization, "Bearer secret-token");
});

test("a refused token signs the person out, and says so", async () => {
  const network = fakeNetwork(json(401, { detail: "A valid staff token is required" }));
  const { api, signedOut } = clientFor(network);

  await assert.rejects(api.reviewQueue(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 401);
    assert.match(error.message, /token was not accepted/i);
    return true;
  });
  assert.equal(signedOut.length, 1);
  assert.match(signedOut[0], /token was not accepted/);
});

test("checking a token at sign-in reports the refusal without signing out of anything", async () => {
  const network = fakeNetwork(json(401, { detail: "A valid staff token is required" }));
  const { api, signedOut } = clientFor(network, { token: "typed-just-now" });

  await assert.rejects(api.me(), (error) => error.status === 401);
  assert.equal(signedOut.length, 0);
});

test("a lost connection is an error with its own message, not a crash", async () => {
  const network = fakeNetwork(new TypeError("Failed to fetch"));
  const { api } = clientFor(network);

  await assert.rejects(api.reviewQueue(), (error) => {
    assert.equal(error.status, 0);
    assert.match(error.message, /could not reach the archive/i);
    return true;
  });
});

test("an upload sends the form as it is, so the browser can set the multipart boundary", async () => {
  const network = fakeNetwork(json(201, { id: ID, images: [] }));
  const { api } = clientFor(network);
  const form = new FormData();
  form.set("title", "Letter");

  await api.uploadDocument(form);

  const { url, options } = network.calls[0];
  assert.equal(url, "/api/catalog/documents");
  assert.equal(options.method, "POST");
  assert.equal(options.body, form);
  assert.equal(options.headers["Content-Type"], undefined);
});

test("a correction is a human transcription with the text as typed", async () => {
  const network = fakeNetwork(json(201, { id: "t1" }));
  const { api } = clientFor(network);

  await api.saveCorrection(ID, "Skeppet Vega\nlämnade Göteborg");

  const { url, options } = network.calls[0];
  assert.equal(url, `/api/catalog/images/${ID}/transcriptions`);
  assert.equal(options.method, "POST");
  assert.equal(options.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(options.body), { source: "human", text: "Skeppet Vega\nlämnade Göteborg" });
});

test("reading an image again, and loading a document and its history, use the documented routes", async () => {
  const network = fakeNetwork(json(202, {}), json(200, { id: ID }), json(200, []));
  const { api } = clientFor(network);

  await api.readAgain(ID);
  await api.document(ID);
  await api.transcriptions(ID);

  assert.deepEqual(
    network.calls.map(({ url, options }) => `${options.method ?? "GET"} ${url}`),
    [
      `POST /api/catalog/images/${ID}/ocr`,
      `GET /api/catalog/documents/${ID}`,
      `GET /api/catalog/images/${ID}/transcriptions`,
    ],
  );
});

test("an image's bytes come back as a blob the page can show", async () => {
  const bytes = new Response(new Uint8Array([137, 80, 78, 71]), { status: 200, headers: { "Content-Type": "image/png" } });
  const network = fakeNetwork(bytes);
  const { api } = clientFor(network);

  const blob = await api.imageContent(ID);

  assert.equal(network.calls[0].url, `/api/catalog/images/${ID}/content`);
  assert.equal(blob.type, "image/png");
  assert.equal(blob.size, 4);
});
