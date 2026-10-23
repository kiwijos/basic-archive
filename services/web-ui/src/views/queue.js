import { describeProgress } from "../badges.js";
import { h } from "../dom.js";
import { pageFromQuery, pageRequest, pageResult } from "../paging.js";
import { pathFor } from "../router.js";
import { badge, formatTime, link } from "../widgets.js";

const PAGE_SIZE = 50;
const REFRESH_MS = 5000;
const STATUS_ORDER = ["pending", "ocr_done", "failed", "verified"];

/** The Documents that are not fully verified, including partly verified ones, oldest first. */
export function queueView({ api, navigate }) {
  let disposed = false;
  let page = pageFromQuery(location.search);
  let shownSnapshot = "";

  const problem = h("p", { class: "error", role: "alert" });
  const rows = h("tbody");
  const empty = h("p", { class: "empty", hidden: true }, "Nothing is waiting for review. ", link(navigate, pathFor("upload"), "Upload a page"), " to begin.");
  const previous = h("button", { type: "button", onclick: () => go(page - 1) }, "Previous");
  const next = h("button", { type: "button", onclick: () => go(page + 1) }, "Next");
  const position = h("span", { class: "position" });
  const pager = h("nav", { class: "pager", "aria-label": "Review queue pages", hidden: true }, previous, position, next);
  const beyond = h("p", { class: "empty", hidden: true }, "There is nothing on this page.");
  const table = h(
    "table",
    { hidden: true },
    h("caption", {}, "Documents waiting for review"),
    h(
      "thead",
      {},
      h("tr", {}, ...["Document", "Type", "Progress", "Images", "Uploaded"].map((name) => h("th", { scope: "col" }, name))),
    ),
    rows,
  );

  function row(item) {
    return h(
      "tr",
      { "data-document-id": item.id },
      h("th", { scope: "row" }, link(navigate, pathFor("review", { documentId: item.id }), item.title)),
      h("td", {}, item.document_type ?? "—"),
      h(
        "td",
        {},
        h("progress", { max: item.image_count, value: item.verified_images }),
        " ",
        h("span", { class: "progress-text" }, describeProgress(item.verified_images, item.image_count)),
      ),
      h("td", { class: "badges" }, STATUS_ORDER.filter((status) => item.statuses[status] > 0).map((status) => badge(status, item.statuses[status]))),
      h("td", {}, formatTime(item.created_at)),
    );
  }

  function go(target) {
    page = target;
    history.replaceState(null, "", page === 1 ? pathFor("queue") : `${pathFor("queue")}?page=${page}`);
    load();
  }

  async function load() {
    try {
      const result = pageResult(await api.reviewQueue(pageRequest(page, PAGE_SIZE)), page, PAGE_SIZE);
      if (disposed) return;
      problem.textContent = "";
      // Only redraw when something changed, so the refresh does not take keyboard focus off a link.
      const snapshot = JSON.stringify(result.entries);
      if (snapshot !== shownSnapshot) {
        shownSnapshot = snapshot;
        rows.replaceChildren(...result.entries.map(row));
      }
      table.hidden = result.entries.length === 0;
      empty.hidden = !(result.entries.length === 0 && page === 1);
      beyond.hidden = !(result.entries.length === 0 && page > 1);
      previous.disabled = !result.hasPrevious;
      next.disabled = !result.hasNext;
      position.textContent = `Page ${page}`;
      pager.hidden = page === 1 && !result.hasNext;
    } catch (error) {
      if (!disposed) problem.textContent = error.message;
    }
  }

  load();
  const timer = setInterval(load, REFRESH_MS);

  return {
    title: "Review queue",
    element: h(
      "section",
      {},
      h("h1", {}, "Review queue"),
      h("p", {}, "Pages the machine has read, or tried to, that a person has not yet checked. Open one to read it against the scan and correct the text."),
      problem,
      empty,
      beyond,
      table,
      pager,
    ),
    dispose() {
      disposed = true;
      clearInterval(timer);
    },
  };
}
