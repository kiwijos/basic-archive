import assert from "node:assert/strict";
import { test } from "node:test";

import { candidateRows, candidatesSummary, fetchedOn, referenceLine, safeWikidataUrl, validQuery, wikidataRefs } from "../../src/wikidata.js";

const candidate = (id, extra = {}) => ({ id, label: `Label ${id}`, description: `About ${id}`, url: `https://www.wikidata.org/wiki/${id}`, ...extra });

test("each candidate shows what Wikidata says about it and whether this Ship already has it", () => {
  const rows = candidateRows([candidate("Q1"), candidate("Q2", { description: null }), candidate("Q3")], ["Q3"]);

  assert.deepEqual(rows, [
    { id: "Q1", label: "Label Q1", description: "About Q1", url: "https://www.wikidata.org/wiki/Q1", chosen: false },
    { id: "Q2", label: "Label Q2", description: "No description on Wikidata", url: "https://www.wikidata.org/wiki/Q2", chosen: false },
    { id: "Q3", label: "Label Q3", description: "About Q3", url: "https://www.wikidata.org/wiki/Q3", chosen: true },
  ]);
  assert.deepEqual(candidateRows([], []), []);
});

test("a link to Wikidata is offered only if it really points there", () => {
  const rows = candidateRows([candidate("Q1", { url: "javascript:alert(1)" }), candidate("Q2", { url: "https://evil.example/Q2" }), candidate("Q3")], []);

  assert.deepEqual(rows.map((row) => row.url), [null, null, "https://www.wikidata.org/wiki/Q3"]);
});

test("the number of candidates is put into words, and an empty list says what to try", () => {
  assert.equal(candidatesSummary(3, "Vasa"), 'Found 3 possible matches for "Vasa". Choose the one that is this ship.');
  assert.equal(candidatesSummary(1, "Vasa"), 'Found 1 possible match for "Vasa". Choose it only if it is this ship.');
  assert.match(candidatesSummary(0, "Vasa"), /No matches for "Vasa" on Wikidata/);
  assert.match(candidatesSummary(0, "Vasa"), /different spelling or a former name/);
});

test("a stored match says what it is, where it came from and when it was fetched", () => {
  assert.equal(
    referenceLine({ source: "wikidata", id: "Q219821", label: "Vasa", retrieved_at: "2026-10-23T21:04:05.123456+00:00" }),
    "Vasa (Wikidata Q219821), fetched 2026-10-23",
  );
  assert.equal(referenceLine({ source: "wikidata", id: "Q1", label: "X", retrieved_at: null }), "X (Wikidata Q1)");
});

test("what is typed in the search box must be something to ask for", () => {
  assert.equal(validQuery("  Vasa "), "Vasa");
  assert.equal(validQuery("   "), null);
  assert.equal(validQuery(""), null);
  assert.equal(validQuery("x".repeat(201)), "x".repeat(200));
});

test("a link to Wikidata is used only when it really is an item page on Wikidata, wherever it is shown", () => {
  assert.equal(safeWikidataUrl("https://www.wikidata.org/wiki/Q219821"), "https://www.wikidata.org/wiki/Q219821");
  for (const bad of ["javascript:alert(1)", "https://www.wikidata.org.evil.example/wiki/Q1", "http://www.wikidata.org/wiki/Q1", "https://www.wikidata.org/wiki/Q1?x=1", "https://www.wikidata.org/wiki/P31", "", null, undefined]) {
    assert.equal(safeWikidataUrl(bad), null, String(bad));
  }
});

test("the day a match was fetched is shown when known and left out when not", () => {
  assert.equal(fetchedOn({ retrieved_at: "2026-10-23T21:04:05+00:00" }), "2026-10-23");
  assert.equal(fetchedOn({ retrieved_at: null }), null);
  assert.equal(fetchedOn({}), null);
});

test("only the Wikidata matches of a record are picked out of its outside references", () => {
  const ship = { external_refs: [{ source: "wikidata", id: "Q1" }, { source: "other", id: "X" }, { source: "wikidata", id: "Q2" }] };

  assert.deepEqual(wikidataRefs(ship).map((ref) => ref.id), ["Q1", "Q2"]);
  assert.deepEqual(wikidataRefs({}), []);
  assert.deepEqual(wikidataRefs(null), []);
});
