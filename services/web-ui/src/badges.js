const BADGES = {
  pending: { label: "Pending", tone: "waiting" },
  ocr_done: { label: "OCR done", tone: "info" },
  verified: { label: "Verified", tone: "good" },
  failed: { label: "Failed", tone: "bad" },
};

/** How a Review status is shown. The label differs for every status, so colour is never the only cue. */
export function badgeFor(status) {
  const known = BADGES[status];
  return known ? { status, ...known } : { status, label: "Unknown", tone: "unknown" };
}

/** "1 of 2 images verified": how far a Document has got. */
export function describeProgress(verified, total) {
  if (total === 0) return "No images";
  return `${verified} of ${total} ${total === 1 ? "image" : "images"} verified`;
}
