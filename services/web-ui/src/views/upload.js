import { h } from "../dom.js";
import { pathFor } from "../router.js";

const RIGHTS = [
  ["reserved", "All rights reserved"],
  ["CC0", "CC0"],
  ["PDM", "Public domain mark"],
  ["CC BY", "CC BY"],
];

function field(id, label, control, hint) {
  return h(
    "div",
    { class: "field" },
    h("label", { for: id }, label),
    control,
    hint ? h("small", { id: `${id}-hint` }, hint) : null,
  );
}

function input(id, type = "text", extra = {}) {
  return h("input", { id, name: id, type, ...extra });
}

/** Uploads one scan as a new Document, then opens it for review. */
export function uploadView({ api, navigate }) {
  const problem = h("p", { class: "error", role: "alert" });
  const status = h("p", { role: "status" });
  const submit = h("button", { type: "submit", class: "primary" }, "Upload");

  const file = input("file", "file", { accept: "image/tiff,image/jpeg,image/png", required: true, "aria-describedby": "file-hint" });
  const rights = h("select", { id: "rights", name: "rights" }, RIGHTS.map(([value, label]) => h("option", { value }, label)));
  const description = h("textarea", { id: "description", name: "description", rows: 3 });

  const form = h(
    "form",
    {
      class: "stack",
      onsubmit: async (event) => {
        event.preventDefault();
        problem.textContent = "";
        status.textContent = "";
        const chosen = file.files[0];
        if (!chosen) {
          problem.textContent = "Choose a scan to upload.";
          file.focus();
          return;
        }
        const body = new FormData(form);
        submit.disabled = true;
        status.textContent = "Uploading…";
        try {
          const document = await api.uploadDocument(body);
          navigate(pathFor("review", { documentId: document.id }));
        } catch (error) {
          status.textContent = "";
          problem.textContent = error.message;
          submit.disabled = false;
        }
      },
    },
    field("file", "Scan", file, "TIFF, JPEG or PNG."),
    field("title", "Title", input("title", "text", { required: true, maxlength: 500 })),
    field("document_type", "Document type", input("document_type", "text", { placeholder: "letter, ledger, photograph…" })),
    field("date_text", "Date as written", input("date_text", "text", { placeholder: "ca 1890" }), "Optional. Write it the way the document does."),
    h(
      "div",
      { class: "row" },
      field("date_from", "Earliest possible date", input("date_from", "date")),
      field("date_to", "Latest possible date", input("date_to", "date")),
    ),
    field("physical_location", "Where the original is kept", input("physical_location")),
    field("description", "Description", description),
    field("rights", "Rights", rights),
    submit,
    status,
    problem,
  );

  return {
    title: "Upload",
    element: h("section", { class: "narrow" }, h("h1", {}, "Upload a scan"), form),
    focus: file,
  };
}
