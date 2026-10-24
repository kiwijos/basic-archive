// What the staff page says about Wikidata candidates and the matches already stored on a Ship.

const WIKIDATA_ITEM = /^https:\/\/www\.wikidata\.org\/wiki\/Q[1-9][0-9]*$/;
const MAX_QUERY = 200;

/** An address from an outside service, or null unless it is an item page on Wikidata, so no page links anywhere else. */
export function safeWikidataUrl(url) {
  return typeof url === "string" && WIKIDATA_ITEM.test(url) ? url : null;
}

/** The day a stored match was fetched, or null when that is not known. */
export function fetchedOn(reference) {
  return reference?.retrieved_at ? reference.retrieved_at.slice(0, 10) : null;
}

/** The Wikidata matches among a record's outside references. */
export function wikidataRefs(record) {
  return (record?.external_refs ?? []).filter((reference) => reference.source === "wikidata");
}

/** One row per candidate: its words, whether this Ship already has it, and a link only if it points at Wikidata. */
export function candidateRows(candidates, storedIds) {
  return candidates.map((candidate) => ({
    id: candidate.id,
    label: candidate.label,
    description: candidate.description || "No description on Wikidata",
    url: safeWikidataUrl(candidate.url),
    chosen: storedIds.includes(candidate.id),
  }));
}

export function candidatesSummary(count, query) {
  if (count === 0) return `No matches for "${query}" on Wikidata. Try a different spelling or a former name.`;
  if (count === 1) return `Found 1 possible match for "${query}". Choose it only if it is this ship.`;
  return `Found ${count} possible matches for "${query}". Choose the one that is this ship.`;
}

/** A stored match in one line. */
export function referenceLine(reference) {
  const day = fetchedOn(reference);
  const when = day ? `, fetched ${day}` : "";
  return `${reference.label} (Wikidata ${reference.id})${when}`;
}

/** What to search for from what was typed: trimmed, not empty, and no longer than the API accepts. */
export function validQuery(text) {
  const query = text.trim().slice(0, MAX_QUERY);
  return query === "" ? null : query;
}
