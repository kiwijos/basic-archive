const ID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/** Which page a location is, and which document it is about. Anything unknown is "notFound". */
export function parseRoute(location) {
  const path = location.split(/[?#]/)[0];
  const trimmed = path.length > 1 ? path.replace(/\/$/, "") : path;
  if (trimmed === "/") return { name: "home", params: {} };
  if (trimmed === "/review") return { name: "queue", params: {} };
  if (trimmed === "/upload") return { name: "upload", params: {} };
  const review = trimmed.match(/^\/documents\/([^/]+)\/review$/);
  if (review && ID.test(review[1])) return { name: "review", params: { documentId: review[1] } };
  return { name: "notFound", params: {} };
}

/** The address of a page, the inverse of parseRoute. */
export function pathFor(name, params = {}) {
  switch (name) {
    case "home":
      return "/";
    case "queue":
      return "/review";
    case "upload":
      return "/upload";
    case "review":
      return `/documents/${params.documentId}/review`;
    default:
      throw new Error(`No page called ${name}`);
  }
}
