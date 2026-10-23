import assert from "node:assert/strict";
import { test } from "node:test";

import { readContext, recordPath } from "../../src/record-context.js";
import { matchedNameOnPage } from "../../src/view-models.js";

const ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

test("a link to a record can carry the search it came from and the name that matched", () => {
  assert.equal(recordPath("ship", ID), `/ships/${ID}`);
  assert.equal(recordPath("ship", ID, { matchedName: "Vega" }), `/ships/${ID}?name=Vega`);
  assert.equal(recordPath("document", ID, { search: "?q=vega&page=2" }), `/documents/${ID}?from=%3Fq%3Dvega%26page%3D2`);
  assert.equal(
    recordPath("ship", ID, { search: "?q=Vega", matchedName: "Vega" }),
    `/ships/${ID}?from=%3Fq%3DVega&name=Vega`,
  );
});

test("the page reads them back, so reload and shared links keep them", () => {
  const link = recordPath("ship", ID, { search: "?q=Vega&verified_only=1&page=3", matchedName: "Götaverken Vega" });
  const context = readContext(link.slice(link.indexOf("?")));

  assert.deepEqual(context, { back: "/?q=Vega&verified_only=1&page=3", name: "Götaverken Vega" });
});

test("without a search to go back to, back is the plain search page", () => {
  assert.deepEqual(readContext(""), { back: "/", name: null });
  assert.deepEqual(readContext("?name="), { back: "/", name: null });
});

test("whatever the address says is cleaned before it is used", () => {
  assert.equal(readContext("?from=%3Fpage%3Dabc%26scope%3Dboats%26q%3Dx").back, "/?q=x");
  assert.equal(readContext("?from=https%3A%2F%2Fevil.example%2F").back, "/");
  assert.equal(readContext(`?name=${"x".repeat(300)}`).name.length, 100);
});

test("a name is marked on the page only if the record really has that name", () => {
  const names = [{ name: "Vega" }, { name: "Nordstjernan" }];

  assert.equal(matchedNameOnPage("Vega", names), "Vega");
  assert.equal(matchedNameOnPage("Titanic", names), null);
  assert.equal(matchedNameOnPage(null, names), null);
  assert.equal(matchedNameOnPage("vega", names), null);
});
