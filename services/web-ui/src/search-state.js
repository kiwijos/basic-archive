// The search page keeps everything it shows in its address, so reload, back and shared links all work.
// This module turns an address into a search and back, and a search into a request for the API.

const MAX_TEXT = 200;
const MAX_VALUE = 100;
const MAX_VALUES = 10;
const MAX_PAGE = 1000; // what the API accepts
const PAGE_SIZE = 20;

const LISTS = { ship_type: "shipType", builder: "builder", place: "place", document_type: "documentType" };

const empty = () => ({
  scope: "documents", q: "", verifiedOnly: false, shipType: [], builder: [], place: [], documentType: [], kind: "", yearFrom: null, yearTo: null, page: 1,
});

function whole(value, min, max) {
  if (value === null || !/^\d+$/.test(value)) return null;
  const number = Number(value);
  return number >= min && number <= max ? number : null;
}

function values(params, name) {
  const seen = [];
  for (const raw of params.getAll(name)) {
    const value = raw.trim().slice(0, MAX_VALUE);
    if (value && !seen.includes(value)) seen.push(value);
  }
  return seen.slice(0, MAX_VALUES);
}

function inOrder(state) {
  if (state.yearFrom !== null && state.yearTo !== null && state.yearFrom > state.yearTo) {
    return { ...state, yearFrom: state.yearTo, yearTo: state.yearFrom };
  }
  return state;
}

/** The search an address describes. Anything in it that makes no sense is left out. */
export function parseSearch(queryString) {
  const params = new URLSearchParams(queryString);
  const state = empty();
  state.q = (params.get("q") ?? "").trim().slice(0, MAX_TEXT);
  state.scope = params.get("scope") === "subjects" ? "subjects" : "documents";
  state.kind = ["ship", "organisation"].includes(params.get("kind")) ? params.get("kind") : "";
  state.verifiedOnly = params.get("verified_only") === "1";
  for (const [name, key] of Object.entries(LISTS)) state[key] = values(params, name);
  state.yearFrom = whole(params.get("year_from"), 1, 9999);
  state.yearTo = whole(params.get("year_to"), 1, 9999);
  state.page = whole(params.get("page"), 1, MAX_PAGE) ?? 1;
  return inOrder(state);
}

function entries(state, { forApi }) {
  const out = [];
  const documents = state.scope === "documents";
  if (state.q) out.push(["q", state.q]);
  if (!forApi && state.scope === "subjects") out.push(["scope", "subjects"]);
  if (!documents && state.kind) out.push(["kind", state.kind]);
  if (state.verifiedOnly && (documents || !forApi)) out.push(["verified_only", forApi ? "true" : "1"]);
  for (const [name, key] of Object.entries(LISTS)) {
    if (name === "document_type" && !documents) continue;
    for (const value of state[key]) out.push([name, value]);
  }
  if (state.yearFrom !== null) out.push(["year_from", String(state.yearFrom)]);
  if (state.yearTo !== null) out.push(["year_to", String(state.yearTo)]);
  if (forApi || state.page > 1) out.push(["page", String(state.page)]);
  if (forApi) out.push(["page_size", String(PAGE_SIZE)]);
  return out;
}

/** The address for a search, written the same way every time. Empty for the default search. */
export function searchQuery(state) {
  const text = new URLSearchParams(entries(state, { forApi: false })).toString();
  return text ? `?${text}` : "";
}

/** The query string to send to search-api for a search. Every value is encoded. */
export function apiQuery(state) {
  return new URLSearchParams(entries(state, { forApi: true })).toString();
}

/** A changed search. Anything but turning the page starts again from the first page. */
export function withChange(state, change) {
  return inOrder({ ...state, ...change, page: change.page ?? 1 });
}

/** Switches one facet value on or off. */
export function toggleValue(state, key, value) {
  const current = state[key];
  const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value].slice(0, MAX_VALUES);
  return withChange(state, { [key]: next });
}

export function hasFilters(state) {
  return (
    state.verifiedOnly || state.kind !== "" || state.yearFrom !== null || state.yearTo !== null ||
    Object.values(LISTS).some((key) => state[key].length > 0)
  );
}

/** The same words and scope with every filter removed. */
export function clearFilters(state) {
  return { ...empty(), q: state.q, scope: state.scope };
}
