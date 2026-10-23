import assert from "node:assert/strict";
import { test } from "node:test";

import { badgeFor, describeProgress } from "../../src/badges.js";

test("each Review status has its own label and tone, and keeps its code for tests and styling", () => {
  assert.deepEqual(badgeFor("pending"), { status: "pending", label: "Pending", tone: "waiting" });
  assert.deepEqual(badgeFor("ocr_done"), { status: "ocr_done", label: "OCR done", tone: "info" });
  assert.deepEqual(badgeFor("verified"), { status: "verified", label: "Verified", tone: "good" });
  assert.deepEqual(badgeFor("failed"), { status: "failed", label: "Failed", tone: "bad" });
});

test("the four labels are different, so a badge is never told apart by colour alone", () => {
  const labels = ["pending", "ocr_done", "verified", "failed"].map((status) => badgeFor(status).label);
  assert.equal(new Set(labels).size, 4);
});

test("an unknown status is shown as unknown instead of breaking the page", () => {
  assert.deepEqual(badgeFor("something_new"), { status: "something_new", label: "Unknown", tone: "unknown" });
});

test("progress reads naturally for one image and for several", () => {
  assert.equal(describeProgress(0, 1), "0 of 1 image verified");
  assert.equal(describeProgress(1, 2), "1 of 2 images verified");
  assert.equal(describeProgress(3, 3), "3 of 3 images verified");
  assert.equal(describeProgress(0, 0), "No images");
});
