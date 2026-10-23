// What the public pages say about the archive's records. Kept apart from the DOM code so the
// wording that decides how far a visitor trusts a text can be tested.

const year = (iso) => (iso ? iso.slice(0, 4) : null);

/** How far a Document's text can be trusted. Verified only when a person has checked every page. */
export function verification({ verified, verified_images: checked, image_count: pages }) {
  if (verified) return { status: "verified", label: "Verified by a person" };
  if (pages === 0) return { status: "empty", label: "No pages yet" };
  if (checked > 0) return { status: "partial", label: `Partly verified: ${checked} of ${pages} pages checked` };
  return { status: "machine", label: "Machine-transcribed, not yet checked" };
}

/** The same for one page. */
export function imageVerification({ verified, text_source: source }) {
  if (verified) return { status: "verified", label: "Verified by a person" };
  if (source === "machine") return { status: "machine", label: "Machine-transcribed, not yet checked" };
  return { status: "empty", label: "No text yet" };
}

/** Says which name a search matched when it was not the one the Ship carries now. */
export function matchedNameNote({ name, matched_name: matched }) {
  if (!matched || matched === name) return null;
  return `Matched the former name "${matched}"`;
}

/** A date as it was written, or else as years. */
export function periodText(date) {
  if (!date) return "";
  if (date.date_text) return date.date_text;
  const from = year(date.date_from);
  const to = year(date.date_to);
  if (from && to) return from === to ? from : `${from}–${to}`;
  if (from) return `from ${from}`;
  if (to) return `until ${to}`;
  return "";
}

export function yearsText(from, to) {
  if (from == null) return to == null ? "" : String(to);
  if (to == null || to === from) return String(from);
  return `${from}–${to}`;
}

/** A Ship's names in the order given, each with the period it was carried. */
export function nameTimeline(names) {
  return names.map((n) => ({ name: n.name, period: periodText(n), current: n.current }));
}

const LABELS = {
  built_by: { from: "Built by", to: "Built" },
  owned_by: { from: "Owned by", to: "Owned" },
  operated_by: { from: "Operated by", to: "Operated" },
  rebuilt_from: { from: "Rebuilt from", to: "Rebuilt as" },
};

/** A Relation put into words from the point of view of the record it is shown on. */
export function relationSentence(relation) {
  return {
    label: LABELS[relation.predicate][relation.direction],
    other: { id: relation.other_id, kind: relation.other_kind, name: relation.other_name ?? "Unnamed" },
    when: periodText(relation),
    place: relation.place ?? null,
  };
}

const RIGHTS = {
  CC0: { label: "CC0 1.0: no rights reserved", url: "https://creativecommons.org/publicdomain/zero/1.0/" },
  PDM: { label: "Public Domain Mark 1.0", url: "https://creativecommons.org/publicdomain/mark/1.0/" },
  "CC BY": { label: "Creative Commons Attribution 4.0", url: "https://creativecommons.org/licenses/by/4.0/" },
  reserved: { label: "All rights reserved", url: null },
};

export function rightsInfo(code) {
  const known = RIGHTS[code];
  return known ? { code, ...known } : { code, label: code, url: null };
}

/** The values of one facet, most common first, with the chosen ones marked and kept even at zero. */
export function facetOptions(counts, selected) {
  const options = Object.entries(counts ?? {}).map(([value, count]) => ({ value, count, selected: selected.includes(value) }));
  for (const value of selected) {
    if (!options.some((option) => option.value === value)) options.push({ value, count: 0, selected: true });
  }
  const ranked = options.filter((o) => o.count > 0).sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
  return [...ranked, ...options.filter((o) => o.count === 0)].map(({ value, count, selected: chosen }) => ({ value, count, selected: chosen }));
}

const TITLES = {
  ship_types: "Ship type",
  ship_type: "Ship type",
  builders: "Builder",
  places: "Place",
  document_type: "Document type",
  organisation_type: "Organisation type",
  entity: "Kind",
  verified: "Verification",
};

export const facetTitle = (name) => TITLES[name] ?? name;

export function resultsSummary(total) {
  if (total === 0) return "No results";
  return total === 1 ? "1 result" : `${total} results`;
}

export function pagerInfo({ page, total_pages: pages }) {
  return { text: `Page ${page} of ${pages}`, hasPrevious: page > 1, hasNext: page < pages };
}
