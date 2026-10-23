import assert from "node:assert/strict";
import { test } from "node:test";

import { parsePage, viewerLabel, viewerOptions, viewerPages } from "../../src/viewer.js";

const ID_1 = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";
const ID_2 = "5b1d0f0e-0000-4000-8000-000000000002";
const image = (id, page_no, extra = {}) => ({ id, page_no, mime: "image/tiff", iiif_info: `/iiif/3/${id}/info.json`, ...extra });

test("the viewer is told where the image's information is, by the same relative address the API gave", () => {
  const options = viewerOptions(`/iiif/3/${ID_1}/info.json`);

  assert.equal(options.tileSources, `/iiif/3/${ID_1}/info.json`);
  assert.doesNotMatch(JSON.stringify(options), /https?:/);
});

test("the viewer's own buttons replace the library's picture buttons, so nothing is fetched from elsewhere", () => {
  const options = viewerOptions(`/iiif/3/${ID_1}/info.json`);

  assert.equal(options.showNavigationControl, false);
  assert.equal(options.prefixUrl, undefined);
  assert.equal(options.crossOriginPolicy, undefined);
});

test("a blueprint can be zoomed well past its own pixels and the whole picture is never lost", () => {
  const options = viewerOptions(`/iiif/3/${ID_1}/info.json`);

  assert.ok(options.maxZoomPixelRatio >= 2, "zooming in far enough to read fine detail");
  assert.ok(options.minZoomImageRatio <= 1, "zooming out to see the whole picture");
  assert.equal(options.constrainDuringPan, true);
  assert.ok(options.visibilityRatio >= 0.5, "part of the picture always stays in view");
  assert.ok(options.animationTime > 0.2, "movements are animated, not jumps");
});

test("each page of a document that can be shown is offered, in page order", () => {
  const pages = viewerPages([image(ID_2, 2), image(ID_1, 1)]);

  assert.deepEqual(pages, [
    { pageNo: 1, label: "Page 1", infoUrl: `/iiif/3/${ID_1}/info.json`, imageId: ID_1 },
    { pageNo: 2, label: "Page 2", infoUrl: `/iiif/3/${ID_2}/info.json`, imageId: ID_2 },
  ]);
});

test("a single page is called the page, and a page with no image service is left out", () => {
  assert.equal(viewerPages([image(ID_1, 1)])[0].label, "Scan");
  assert.deepEqual(viewerPages([{ id: ID_1, page_no: 1, mime: "image/png" }]), []);
  assert.deepEqual(viewerPages([]), []);
  assert.deepEqual(viewerPages(undefined), []);
});

test("the page to open comes from the address when it names a real page, and is otherwise the first", () => {
  const pages = viewerPages([image(ID_1, 1), image(ID_2, 2)]);

  assert.equal(parsePage("?page=2", pages).pageNo, 2);
  assert.equal(parsePage("?page=9", pages).pageNo, 1);
  assert.equal(parsePage("?page=abc", pages).pageNo, 1);
  assert.equal(parsePage("?page=-1", pages).pageNo, 1);
  assert.equal(parsePage("", pages).pageNo, 1);
  assert.equal(parsePage("?page=1", []), null);
});

test("the viewer says what it shows and how to use it, for people who cannot see it", () => {
  const label = viewerLabel("Linjeritning", { pageNo: 2, label: "Page 2" }, 2);

  assert.match(label, /Linjeritning/);
  assert.match(label, /page 2 of 2/i);
  assert.match(label, /plus and minus/i);
  assert.match(label, /arrow keys/i);
  assert.doesNotMatch(viewerLabel("Brev", { pageNo: 1, label: "Scan" }, 1), /page 1 of/i);
});
