import assert from "node:assert/strict";
import { test } from "node:test";

import { apiQuery, clearFilters, hasFilters, parseSearch, searchQuery, toggleValue, withChange } from "../../src/search-state.js";

test("an empty address is a search for everything, in Documents, on page 1", () => {
  assert.deepEqual(parseSearch(""), {
    scope: "documents", q: "", verifiedOnly: false, shipType: [], builder: [], place: [], documentType: [], kind: "", yearFrom: null, yearTo: null, page: 1,
  });
  assert.equal(searchQuery(parseSearch("")), "");
});

test("what is in the address is what the page shows, so reload and sharing work", () => {
  const address = "?q=Nordstjernan&verified_only=1&ship_type=barque&ship_type=steamer&builder=G%C3%B6taverken&place=G%C3%B6teborg&year_from=1880&year_to=1900&page=3";
  const state = parseSearch(address);

  assert.equal(state.q, "Nordstjernan");
  assert.equal(state.verifiedOnly, true);
  assert.deepEqual(state.shipType, ["barque", "steamer"]);
  assert.deepEqual([state.builder, state.place], [["Götaverken"], ["Göteborg"]]);
  assert.deepEqual([state.yearFrom, state.yearTo, state.page], [1880, 1900, 3]);
  assert.deepEqual(parseSearch(searchQuery(state)), state);
});

test("the address is written the same way every time", () => {
  const a = parseSearch("?page=2&q=vega&ship_type=barque&verified_only=1");
  const b = parseSearch("?verified_only=1&ship_type=barque&q=vega&page=2");

  assert.equal(searchQuery(a), searchQuery(b));
  assert.equal(searchQuery(a), "?q=vega&verified_only=1&ship_type=barque&page=2");
});

test("Subjects have their own scope and kind, and the Document-only filters do not follow", () => {
  const state = parseSearch("?scope=subjects&kind=ship&q=vega&verified_only=1&document_type=letter&builder=Yard");

  assert.equal(state.scope, "subjects");
  assert.equal(apiQuery(state), "q=vega&kind=ship&builder=Yard&page=1&page_size=20");
  assert.equal(apiQuery(parseSearch("?q=vega&verified_only=1&document_type=letter")), "q=vega&verified_only=true&document_type=letter&page=1&page_size=20");
});

test("anything in the address that makes no sense falls back instead of breaking the page", () => {
  assert.equal(parseSearch("?scope=boats").scope, "documents");
  assert.equal(parseSearch("?kind=boat&scope=subjects").kind, "");
  for (const bad of ["abc", "0", "-3", "2.5", "99999999999", ""]) assert.equal(parseSearch(`?page=${bad}`).page, 1, bad);
  for (const bad of ["abc", "0", "10000", "-1", "1e3"]) assert.equal(parseSearch(`?year_from=${bad}`).yearFrom, null, bad);
  assert.equal(parseSearch("?verified_only=yes").verifiedOnly, false);
  assert.equal(parseSearch(`?q=${"x".repeat(500)}`).q.length, 200);
  assert.equal(parseSearch(`?ship_type=${"y".repeat(300)}`).shipType[0].length, 100);
  assert.equal(parseSearch(`?${Array.from({ length: 30 }, (_, i) => `place=p${i}`).join("&")}`).place.length, 10);
  assert.deepEqual(parseSearch("?place=&place=%20&place=Göteborg").place, ["Göteborg"]);
});

test("a year range given backwards is turned the right way round", () => {
  const state = parseSearch("?year_from=1900&year_to=1880");

  assert.deepEqual([state.yearFrom, state.yearTo], [1880, 1900]);
});

test("changing the search or a filter goes back to page 1, but turning the page does not", () => {
  const onPageThree = parseSearch("?q=vega&page=3");

  assert.equal(withChange(onPageThree, { q: "freja" }).page, 1);
  assert.equal(withChange(onPageThree, { verifiedOnly: true }).page, 1);
  assert.equal(withChange(onPageThree, { page: 4 }).page, 4);
});

test("a facet value is switched on and off without touching the others", () => {
  let state = parseSearch("?ship_type=barque&place=Göteborg&page=2");

  state = toggleValue(state, "shipType", "steamer");
  assert.deepEqual(state.shipType, ["barque", "steamer"]);
  assert.equal(state.page, 1);
  state = toggleValue(state, "shipType", "barque");
  assert.deepEqual(state.shipType, ["steamer"]);
  assert.deepEqual(state.place, ["Göteborg"]);
});

test("filters can be told from the search words and cleared without losing them", () => {
  const state = parseSearch("?q=vega&builder=Yard&year_from=1880&verified_only=1&scope=subjects");

  assert.equal(hasFilters(state), true);
  assert.equal(hasFilters(parseSearch("?q=vega")), false);
  const cleared = clearFilters(state);
  assert.equal(hasFilters(cleared), false);
  assert.deepEqual([cleared.q, cleared.scope], ["vega", "subjects"]);
});

test("everything sent to the API is encoded, so a search cannot add parameters of its own", () => {
  const state = parseSearch(`?q=${encodeURIComponent("a&verified_only=true#x")}`);

  assert.equal(apiQuery(state), "q=a%26verified_only%3Dtrue%23x&page=1&page_size=20");
});
