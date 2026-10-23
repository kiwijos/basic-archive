import { pathForRecord, pathFor } from "./router.js";
import { parseSearch, searchQuery } from "./search-state.js";

const MAX_NAME = 100;

/**
 * The address of a record's page, optionally remembering the search it was reached from and the name
 * that search matched. Both are only hints for the page; without them the address still works.
 */
export function recordPath(kind, id, { search, matchedName } = {}) {
  const params = new URLSearchParams();
  if (search) params.set("from", search);
  if (matchedName) params.set("name", matchedName);
  const query = params.toString();
  return pathForRecord(kind, id) + (query ? `?${query}` : "");
}

/** What a record page's address says about how the visitor got there, cleaned before it is used. */
export function readContext(queryString) {
  const params = new URLSearchParams(queryString);
  const name = (params.get("name") ?? "").trim().slice(0, MAX_NAME);
  // Rebuilt from the parsed search, so only a real search of this site can come out of it.
  return { back: pathFor("search") + searchQuery(parseSearch(params.get("from") ?? "")), name: name || null };
}
