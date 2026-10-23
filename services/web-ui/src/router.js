const ID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

// The permanent address of a record's own page, by what kind of record it is.
const RECORD_PATHS = { ship: "ships", organisation: "organisations", document: "documents" };
const RECORD_ROUTES = { ships: "ship", organisations: "organisation", documents: "document" };

/** Which page a location is, and which record it is about. Anything unknown is "notFound". */
export function parseRoute(location) {
  const path = location.split(/[?#]/)[0];
  const trimmed = path.length > 1 ? path.replace(/\/$/, "") : path;
  if (trimmed === "/") return { name: "search", params: {} };
  if (trimmed === "/review") return { name: "queue", params: {} };
  if (trimmed === "/upload") return { name: "upload", params: {} };
  const review = trimmed.match(/^\/documents\/([^/]+)\/review$/);
  if (review && ID.test(review[1])) return { name: "review", params: { documentId: review[1] } };
  const record = trimmed.match(/^\/(ships|organisations|documents)\/([^/]+)$/);
  if (record && ID.test(record[2])) return { name: RECORD_ROUTES[record[1]], params: { id: record[2] } };
  return { name: "notFound", params: {} };
}

/** The address of a page, the inverse of parseRoute. */
export function pathFor(name, params = {}) {
  switch (name) {
    case "search":
      return "/";
    case "queue":
      return "/review";
    case "upload":
      return "/upload";
    case "review":
      return `/documents/${params.documentId}/review`;
    case "ship":
      return `/ships/${params.id}`;
    case "organisation":
      return `/organisations/${params.id}`;
    case "document":
      return `/documents/${params.id}`;
    default:
      throw new Error(`No page called ${name}`);
  }
}

/** The address of a record's own page from its kind ("ship", "organisation" or "document"). */
export function pathForRecord(kind, id) {
  const prefix = RECORD_PATHS[kind];
  if (!prefix) throw new Error(`No page for a ${kind}`);
  return `/${prefix}/${id}`;
}
