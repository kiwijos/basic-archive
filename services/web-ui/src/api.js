export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Turns a failed answer into a sentence for the person using the page. Status 0 means no answer at all. */
export function describeFailure(status, body) {
  const detail = body && typeof body === "object" ? body.detail : undefined;
  if (status === 0) return "Could not reach the archive. Check your connection and try again.";
  if (status === 401) return "Your token was not accepted. Sign in again with a valid staff token.";
  if (status === 502) return "The file store is not available right now. Try again in a moment.";
  if (status >= 500) return `The archive had a problem (status ${status}). Try again in a moment.`;
  if (Array.isArray(detail)) {
    return detail.map((problem) => `${problem.loc.slice(1).join(".")}: ${problem.msg}`).join("; ");
  }
  if (typeof detail === "string") return detail;
  return `The request was refused (status ${status}).`;
}

/**
 * The calls the pages make to catalog-api. fetch is passed in so tests can stand in for the network,
 * and every call carries the staff token.
 */
export function createApi({ fetch, getToken, onUnauthorized, base = "" }) {
  async function request(path, { method, json, body, as = "json", signOutOn401 = true } = {}) {
    const headers = { Authorization: `Bearer ${getToken()}` };
    let payload = body;
    if (json !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(json);
    }
    let response;
    try {
      response = await fetch(base + path, { method, headers, body: payload });
    } catch {
      throw new ApiError(0, describeFailure(0));
    }
    if (!response.ok) {
      const parsed = await response.json().catch(() => undefined);
      const message = describeFailure(response.status, parsed);
      if (response.status === 401 && signOutOn401) onUnauthorized(message);
      throw new ApiError(response.status, message);
    }
    return as === "blob" ? response.blob() : response.json();
  }

  const catalog = "/api/catalog";
  return {
    // Checking a token as it is typed in must not sign out of the session that may already exist.
    me: () => request(`${catalog}/me`, { signOutOn401: false }),
    reviewQueue: ({ limit = 50, offset = 0 } = {}) => request(`${catalog}/review-queue?limit=${limit}&offset=${offset}`),
    document: (id) => request(`${catalog}/documents/${id}`),
    transcriptions: (imageId) => request(`${catalog}/images/${imageId}/transcriptions`),
    imageContent: (imageId) => request(`${catalog}/images/${imageId}/content`, { as: "blob" }),
    uploadDocument: (form) => request(`${catalog}/documents`, { method: "POST", body: form }),
    saveCorrection: (imageId, text) =>
      request(`${catalog}/images/${imageId}/transcriptions`, { method: "POST", json: { source: "human", text } }),
    readAgain: (imageId) => request(`${catalog}/images/${imageId}/ocr`, { method: "POST" }),
  };
}
