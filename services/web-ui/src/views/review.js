import { describeProgress } from "../badges.js";
import { h } from "../dom.js";
import { pathFor } from "../router.js";
import { badge, formatTime, link } from "../widgets.js";

const POLL_MS = 2000;
const BROWSER_CANNOT_SHOW = new Set(["image/tiff"]);

/** One page: the scan beside its text, with the actions a reviewer has. */
function pagePanel({ api, image, number, total, onChanged }) {
  let shown = image;
  let loadedText = image.current_text ?? "";
  let objectUrl;

  const heading = h("h2", {}, total > 1 ? `Page ${number} of ${total}` : "Page");
  const badgeSlot = h("span", { class: "badge-slot" });
  const message = h("p", { role: "status", class: "message" });
  const problem = h("p", { role: "alert", class: "error" });
  const picture = h("div", { class: "scan" }, h("p", {}, "Loading the scan…"));

  const textId = `text-${image.id}`;
  const textarea = h("textarea", { id: textId, name: "text", rows: 18, spellcheck: "false" });
  textarea.value = loadedText;
  const save = h("button", { type: "submit", class: "primary" }, "Save as verified");
  const again = h("button", { type: "button" }, "Read again");
  const sourceNote = h("small", { class: "source" });

  const history = h("div", { class: "history-body" });
  const details = h(
    "details",
    {
      class: "history",
      ontoggle: () => {
        if (details.open) loadHistory();
      },
    },
    h("summary", {}, "History of this page's text"),
    history,
  );

  async function loadHistory() {
    try {
      const rows = await api.transcriptions(image.id);
      history.replaceChildren(
        rows.length === 0
          ? h("p", {}, "Nothing has been read or written yet.")
          : h(
              "ol",
              { class: "versions" },
              rows.map((row) =>
                h(
                  "li",
                  { "data-source": row.source },
                  h("strong", {}, row.source === "human" ? `Corrected by ${row.created_by}` : `Read by ${row.engine} ${row.engine_version}`),
                  ` · ${formatTime(row.created_at)}`,
                  h("pre", {}, row.text),
                ),
              ),
            ),
      );
    } catch (error) {
      history.replaceChildren(h("p", { class: "error" }, error.message));
    }
  }

  function show(next) {
    shown = next;
    badgeSlot.replaceChildren(badge(next.review_status));
    const dirty = textarea.value !== loadedText;
    loadedText = next.current_text ?? "";
    if (!dirty) textarea.value = loadedText;
    sourceNote.textContent =
      next.text_source === "human" ? "This text was written by a person." : next.text_source === "machine" ? "This text was read by the machine and not yet checked." : "";
    again.disabled = !["failed", "ocr_done"].includes(next.review_status);
    if (next.review_status === "pending" && !dirty) message.textContent = "Waiting for the machine to read this page…";
    else if (next.review_status === "failed") message.textContent = "The machine could not read this page. Type the text yourself, or try again.";
    else if (message.textContent.startsWith("Waiting") || message.textContent.startsWith("The machine could not")) message.textContent = "";
  }

  save.disabled = false;
  const form = h(
    "form",
    {
      class: "stack",
      onsubmit: async (event) => {
        event.preventDefault();
        problem.textContent = "";
        save.disabled = true;
        try {
          await api.saveCorrection(image.id, textarea.value);
          loadedText = textarea.value;
          message.textContent = "Saved. This page is now verified.";
          if (details.open) loadHistory();
          await onChanged();
        } catch (error) {
          problem.textContent = error.message;
        } finally {
          save.disabled = false;
        }
      },
    },
    h("label", { for: textId }, "Text on the page"),
    textarea,
    sourceNote,
    h("div", { class: "actions" }, save, again),
  );

  again.addEventListener("click", async () => {
    problem.textContent = "";
    again.disabled = true;
    try {
      await api.readAgain(image.id);
      message.textContent = "Reading the page again…";
      await onChanged();
    } catch (error) {
      problem.textContent = error.message;
      again.disabled = false;
    }
  });

  async function loadScan() {
    try {
      const blob = await api.imageContent(image.id);
      objectUrl = URL.createObjectURL(blob);
      if (BROWSER_CANNOT_SHOW.has(image.mime)) {
        picture.replaceChildren(
          h("p", {}, "Your browser cannot show TIFF scans."),
          h("a", { href: objectUrl, download: image.original_filename ?? "scan.tif" }, "Download the scan"),
        );
      } else {
        picture.replaceChildren(h("img", { src: objectUrl, alt: `Scan of page ${number}${image.original_filename ? `, ${image.original_filename}` : ""}` }));
      }
    } catch (error) {
      picture.replaceChildren(h("p", { class: "error" }, error.message));
    }
  }

  show(image);
  loadScan();

  return {
    element: h(
      "article",
      { class: "page", "data-image-id": image.id },
      h("header", {}, heading, badgeSlot),
      h("div", { class: "split" }, picture, h("div", { class: "editor" }, form, message, problem, details)),
    ),
    update: show,
    get pending() {
      return shown.review_status === "pending";
    },
    dispose() {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    },
  };
}

/** A Document's pages for review. Polls while any page is still waiting for the machine. */
export function reviewView({ api, navigate, documentId }) {
  let disposed = false;
  let timer;
  let panels = [];

  const title = h("h1", {}, "Loading…");
  const progress = h("p", { class: "progress-line" });
  const done = h("p", { class: "done", role: "status", hidden: true }, "Every page of this document is verified, so it has left the review queue. ", link(navigate, pathFor("queue"), "Back to the queue"));
  const problem = h("p", { role: "alert", class: "error" });
  const pages = h("div", { class: "pages" });

  async function refresh() {
    clearTimeout(timer);
    try {
      const document = await api.document(documentId);
      if (disposed) return;
      problem.textContent = "";
      title.textContent = document.title;
      progress.textContent = describeProgress(document.verified_images, document.image_count);
      done.hidden = !document.verified;
      if (panels.length !== document.images.length) {
        panels.forEach((panel) => panel.dispose());
        panels = document.images.map((image, index) =>
          pagePanel({ api, image, number: index + 1, total: document.images.length, onChanged: refresh }),
        );
        pages.replaceChildren(...panels.map((panel) => panel.element));
      } else {
        panels.forEach((panel, index) => panel.update(document.images[index]));
      }
      if (panels.some((panel) => panel.pending)) timer = setTimeout(refresh, POLL_MS);
    } catch (error) {
      if (disposed) return;
      title.textContent = "Document";
      problem.textContent = error.status === 404 ? "This document does not exist." : error.message;
    }
  }

  refresh();

  return {
    title: "Review",
    element: h("section", {}, h("p", {}, link(navigate, pathFor("queue"), "← Review queue")), title, progress, done, problem, pages),
    dispose() {
      disposed = true;
      clearTimeout(timer);
      panels.forEach((panel) => panel.dispose());
    },
  };
}
