import assert from "node:assert/strict";
import { test } from "node:test";

import {
  facetOptions, facetTitle, imageVerification, matchedNameNote, nameTimeline, pagerInfo, periodText, relationSentence, resultsSummary, rightsInfo, verification, yearsText,
} from "../../src/view-models.js";

test("a Document is called verified only when a person has checked every page", () => {
  assert.deepEqual(verification({ verified: true, verified_images: 2, image_count: 2 }), { status: "verified", label: "Verified by a person" });
  assert.deepEqual(verification({ verified: false, verified_images: 0, image_count: 2 }), { status: "machine", label: "Machine-transcribed, not yet checked" });
  assert.deepEqual(verification({ verified: false, verified_images: 1, image_count: 2 }), { status: "partial", label: "Partly verified: 1 of 2 pages checked" });
  assert.deepEqual(verification({ verified: false, verified_images: 0, image_count: 0 }), { status: "empty", label: "No pages yet" });
});

test("a Document is never shown as verified because of its page count alone", () => {
  assert.equal(verification({ verified: false, verified_images: 2, image_count: 2 }).status, "partial");
  assert.equal(verification({ verified: false, verified_images: 1, image_count: 1 }).status, "partial");
});

test("each page says who wrote its text", () => {
  assert.equal(imageVerification({ verified: true, text_source: "human" }).label, "Verified by a person");
  assert.equal(imageVerification({ verified: false, text_source: "machine" }).label, "Machine-transcribed, not yet checked");
  assert.equal(imageVerification({ verified: false, text_source: null }).label, "No text yet");
  assert.equal(imageVerification({ verified: false, text_source: null }).status, "empty");
});

test("a result found by an old name says which name matched, and stays quiet when the name is the current one", () => {
  assert.equal(matchedNameNote({ name: "Nordstjernan", matched_name: "Vega" }), 'Matched the former name "Vega"');
  assert.equal(matchedNameNote({ name: "Nordstjernan", matched_name: "Nordstjernan" }), null);
  assert.equal(matchedNameNote({ name: "Nordstjernan", matched_name: null }), null);
});

test("a period is shown as it was written, or as years when only dates are known", () => {
  assert.equal(periodText({ date_text: "ca 1890", date_from: "1889-01-01", date_to: "1891-12-31" }), "ca 1890");
  assert.equal(periodText({ date_text: null, date_from: "1889-01-01", date_to: "1899-12-31" }), "1889–1899");
  assert.equal(periodText({ date_text: null, date_from: "1900-05-01", date_to: null }), "from 1900");
  assert.equal(periodText({ date_text: null, date_from: null, date_to: "1899-12-31" }), "until 1899");
  assert.equal(periodText({ date_text: null, date_from: "1890-01-01", date_to: "1890-12-31" }), "1890");
  assert.equal(periodText({ date_text: null, date_from: null, date_to: null }), "");
  assert.equal(periodText(null), "");
});

test("years are shown as one year or a range", () => {
  assert.equal(yearsText(1890, 1890), "1890");
  assert.equal(yearsText(1889, 1891), "1889–1891");
  assert.equal(yearsText(null, null), "");
  assert.equal(yearsText(1889, null), "1889");
});

test("a ship's names are listed over time with the current one marked", () => {
  const names = [
    { name: "Vega", date_text: null, date_from: "1889-01-01", date_to: "1899-12-31", current: false },
    { name: "Nordstjernan", date_text: "från 1900", date_from: "1900-01-01", date_to: null, current: true },
    { name: "Freja", date_text: null, date_from: null, date_to: null, current: false },
  ];

  assert.deepEqual(nameTimeline(names), [
    { name: "Vega", period: "1889–1899", current: false },
    { name: "Nordstjernan", period: "från 1900", current: true },
    { name: "Freja", period: "", current: false },
  ]);
});

test("relations read naturally from either end", () => {
  const other = { other_id: "id-1", other_kind: "ship", other_name: "Skrovet" };
  const dated = { date_text: "1899", date_from: null, date_to: null, place: "Göteborg", source: null };

  assert.deepEqual(relationSentence({ predicate: "rebuilt_from", direction: "from", ...other, ...dated }), {
    label: "Rebuilt from", other: { id: "id-1", kind: "ship", name: "Skrovet" }, when: "1899", place: "Göteborg",
  });
  assert.equal(relationSentence({ predicate: "rebuilt_from", direction: "to", ...other, ...dated }).label, "Rebuilt as");
  assert.equal(relationSentence({ predicate: "built_by", direction: "from", ...other, ...dated }).label, "Built by");
  assert.equal(relationSentence({ predicate: "built_by", direction: "to", ...other, ...dated }).label, "Built");
  assert.equal(relationSentence({ predicate: "owned_by", direction: "from", ...other, ...dated }).label, "Owned by");
  assert.equal(relationSentence({ predicate: "owned_by", direction: "to", ...other, ...dated }).label, "Owned");
  assert.equal(relationSentence({ predicate: "operated_by", direction: "from", ...other, ...dated }).label, "Operated by");
  assert.equal(relationSentence({ predicate: "operated_by", direction: "to", ...other, ...dated }).label, "Operated");
});

test("a record with no name is still given something to show", () => {
  const sentence = relationSentence({ predicate: "built_by", direction: "from", other_id: "i", other_kind: "organisation", other_name: null, place: null, date_text: null, date_from: null, date_to: null });

  assert.equal(sentence.other.name, "Unnamed");
});

test("the rights of an image are explained in words, with a link to the terms where there are any", () => {
  assert.deepEqual(rightsInfo("CC0"), { code: "CC0", label: "CC0 1.0: no rights reserved", url: "https://creativecommons.org/publicdomain/zero/1.0/" });
  assert.equal(rightsInfo("PDM").label, "Public Domain Mark 1.0");
  assert.equal(rightsInfo("CC BY").url, "https://creativecommons.org/licenses/by/4.0/");
  assert.deepEqual(rightsInfo("reserved"), { code: "reserved", label: "All rights reserved", url: null });
  assert.deepEqual(rightsInfo("odd"), { code: "odd", label: "odd", url: null });
});

test("facet values are listed most common first, with the chosen ones marked and kept even when nothing matches", () => {
  const options = facetOptions({ barque: 2, steamer: 5, brig: 5 }, ["barque", "schooner"]);

  assert.deepEqual(options, [
    { value: "brig", count: 5, selected: false },
    { value: "steamer", count: 5, selected: false },
    { value: "barque", count: 2, selected: true },
    { value: "schooner", count: 0, selected: true },
  ]);
  assert.deepEqual(facetOptions(undefined, []), []);
});

test("facets have titles a person understands", () => {
  assert.equal(facetTitle("ship_types"), "Ship type");
  assert.equal(facetTitle("builders"), "Builder");
  assert.equal(facetTitle("places"), "Place");
  assert.equal(facetTitle("verified"), "Verification");
  assert.equal(facetTitle("whatever"), "whatever");
});

test("the number of results and the page are put into words", () => {
  assert.equal(resultsSummary(0), "No results");
  assert.equal(resultsSummary(1), "1 result");
  assert.equal(resultsSummary(93), "93 results");
  assert.deepEqual(pagerInfo({ page: 2, total_pages: 5 }), { text: "Page 2 of 5", hasPrevious: true, hasNext: true });
  assert.deepEqual(pagerInfo({ page: 1, total_pages: 1 }), { text: "Page 1 of 1", hasPrevious: false, hasNext: false });
  assert.deepEqual(pagerInfo({ page: 3, total_pages: 3 }), { text: "Page 3 of 3", hasPrevious: true, hasNext: false });
});
