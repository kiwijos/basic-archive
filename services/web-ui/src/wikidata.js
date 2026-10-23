// What the staff page says about Wikidata candidates and the matches already stored on a Ship.

const WIKIDATA_ITEM = /^https:\/\/www\.wikidata\.org\/wiki\/Q[1-9][0-9]*$/;
const MAX_QUERY = 200;

/** One row per candidate: its words, whether this Ship already has it, and a link only if it points at Wikidata. */
export function candidateRows(candidates, storedIds) {
  return candidates.map((candidate) => ({
    id: candidate.id,
    label: candidate.label,
    description: candidate.description || "No description on Wikidata",
    // The address comes from an outside service, so it is used only when it is an item page on Wikidata.
    url: WIKIDATA_ITEM.test(candidate.url ?? "") ? candidate.url : null,
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
  const when = reference.retrieved_at ? `, fetched ${reference.retrieved_at.slice(0, 10)}` : "";
  return `${reference.label} (Wikidata ${reference.id})${when}`;
}

/** What to search for from what was typed: trimmed, not empty, and no longer than the API accepts. */
export function validQuery(text) {
  const query = text.trim().slice(0, MAX_QUERY);
  return query === "" ? null : query;
}
