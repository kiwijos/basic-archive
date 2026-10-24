import { h } from "../dom.js";
import { pathFor, pathForRecord } from "../router.js";
import { readContext } from "../record-context.js";
import { imageVerification, matchedNameOnPage, nameTimeline, periodText, relationSentence, rightsInfo, verification, yearsText } from "../view-models.js";
import { fetchedOn, safeWikidataUrl } from "../wikidata.js";
import { link, verificationBadge } from "../widgets.js";
import { scanViewer } from "./scan-viewer.js";

const KIND_NAMES = { ship: "Ship", organisation: "Organisation", document: "Document" };

function facts(rows) {
  const shown = rows.filter(([, value]) => value !== null && value !== undefined && value !== "");
  return shown.length
    ? h("dl", { class: "facts" }, shown.flatMap(([term, value]) => [h("dt", {}, term), h("dd", {}, value)]))
    : null;
}

function rights(code) {
  const info = rightsInfo(code);
  return info.url ? h("a", { href: info.url, rel: "license noopener" }, info.label) : info.label;
}

/** A Document's own page: what it is, who and what it is about, and the text of each page with how far to trust it. */
function documentPage({ record, navigate }) {
  const viewer = scanViewer({ title: record.title, images: record.images });
  const overall = verification(record);
  const date = record.date_text || yearsText(record.year_from, record.year_to);
  const nodes = [
    h("h1", {}, record.title),
    h("p", { class: "meta" }, verificationBadge(overall), h("span", {}, KIND_NAMES.document)),
    facts([
      ["Type", record.document_type],
      ["Date", date],
      ["Kept at", record.physical_location],
      ["Description", record.description],
    ]),
    record.subjects.length
      ? h(
          "section",
          { "aria-labelledby": "about" },
          h("h2", { id: "about" }, "About"),
          h("ul", { class: "links" }, record.subjects.map((subject) =>
            h("li", {}, link(navigate, pathForRecord(subject.kind, subject.id), subject.name ?? "Unnamed"), ` (${KIND_NAMES[subject.kind].toLowerCase()}${subject.role ? `, ${subject.role}` : ""})`),
          )),
        )
      : null,
    viewer?.element ?? null,
    h(
      "section",
      { "aria-labelledby": "text" },
      h("h2", { id: "text" }, record.images.length === 1 ? "Text" : "Text by page"),
      record.images.length === 0 ? h("p", {}, "This document has no pages yet.") : null,
      record.images.map((image) => {
        const state = imageVerification(image);
        return h(
          "article",
          { class: "page-text", "data-page": image.page_no },
          h("h3", {}, record.images.length > 1 ? `Page ${image.page_no}` : "Page"),
          h("p", { class: "meta" }, verificationBadge(state), h("span", { class: "rights" }, "Rights: ", rights(image.rights))),
          image.text ? h("div", { class: "transcript" }, image.text) : h("p", { class: "empty" }, "No text has been read for this page yet."),
        );
      }),
    ),
  ];
  return { nodes, dispose: () => viewer?.dispose() };
}

/** A Ship's or Organisation's own page: its names over time, its relations to other records, and the Documents about it. */
function subjectPage({ record, navigate, kind, matchedName, staff }) {
  const names = nameTimeline(record.names);
  const years = yearsText(record.year_from, record.year_to);
  const former = names.filter((n) => !n.current);
  const found = matchedNameOnPage(matchedName, record.names);
  const matched = found && !record.names.some((n) => n.current && n.name === found) ? found : null;
  const kindOf = record.ship_type ?? record.organisation_type;
  return [
    h("h1", {}, record.name ?? "Unnamed"),
    h("p", { class: "meta" }, h("span", { class: "badge badge-kind" }, KIND_NAMES[kind]), kindOf ? h("span", {}, kindOf) : null),
    facts([
      ["Tonnage", record.tonnage != null ? `${record.tonnage} tons` : null],
      ["Launched", periodText(record.launched)],
      ["Built", years],
      ["Fate", [record.fate, periodText(record.fate_date)].filter(Boolean).join(", ")],
      ["Place", record.places.length ? record.places.join(", ") : null],
    ]),
    h(
      "section",
      { "aria-labelledby": "names" },
      h("h2", { id: "names" }, former.length ? "Names over time" : "Name"),
      // Reached by searching for an old name: say so, and mark that name in the list.
      matched ? h("p", { class: "matched-note" }, `Found by the former name "${matched}"`) : null,
      h("ol", { class: "names" }, names.map((n) =>
        h(
          "li",
          { class: [n.current ? "current" : "", n.name === matched ? "matched" : ""].join(" ").trim(), "data-matched": n.name === matched ? "true" : null },
          h("strong", {}, n.name),
          n.period ? ` ${n.period}` : "",
          n.current ? h("span", { class: "badge badge-current" }, "current name") : null,
          n.name === matched ? h("span", { class: "badge badge-matched" }, "matched your search") : null,
        ),
      )),
    ),
    record.external_refs?.length
      ? h(
          "section",
          { "aria-labelledby": "elsewhere" },
          h("h2", { id: "elsewhere" }, "Elsewhere"),
          h("ul", { class: "links" }, record.external_refs.map((ref) =>
            h(
              "li",
              { "data-source": ref.source },
              safeWikidataUrl(ref.url) ? h("a", { href: ref.url, rel: "noopener noreferrer" }, `${ref.label} on Wikidata`) : `${ref.label} on Wikidata`,
              ref.description ? ` – ${ref.description}` : "",
              h("small", { class: "muted" }, ` (matched by staff${fetchedOn(ref) ? `, fetched ${fetchedOn(ref)}` : ""})`),
            ),
          )),
        )
      : null,
    staff && kind === "ship" ? h("p", { class: "staff-link" }, link(navigate, pathFor("shipEdit", { id: record.id }), "Staff: find this ship on Wikidata")) : null,
    record.relations.length
      ? h(
          "section",
          { "aria-labelledby": "relations" },
          h("h2", { id: "relations" }, "Relations"),
          h("ul", { class: "relations" }, record.relations.map((relation) => {
            const sentence = relationSentence(relation);
            return h(
              "li",
              { "data-predicate": relation.predicate },
              `${sentence.label} `,
              link(navigate, pathForRecord(sentence.other.kind, sentence.other.id), sentence.other.name),
              [sentence.when, sentence.place].filter(Boolean).length ? ` (${[sentence.when, sentence.place].filter(Boolean).join(", ")})` : "",
            );
          })),
        )
      : null,
    h(
      "section",
      { "aria-labelledby": "documents" },
      h("h2", { id: "documents" }, "Documents"),
      record.documents.length === 0
        ? h("p", { class: "empty" }, "No documents are linked to this record yet.")
        : h("ul", { class: "links" }, record.documents.map((document) =>
            h(
              "li",
              {},
              link(navigate, pathForRecord("document", document.id), document.title),
              " ",
              verificationBadge(document.verified ? { status: "verified", label: "Verified by a person" } : { status: "machine", label: "Not fully verified" }),
              document.document_type ? ` ${document.document_type}` : "",
            ),
          )),
    ),
  ];
}

/** The permanent page of one record. It is read from the search index, so it is open to everyone. */
export function recordView({ api, navigate, setTitle, kind, id, staff = false }) {
  let disposed = false;
  let release = () => {};
  const body = h("div", {}, h("p", { role: "status" }, "Loading…"));
  const context = readContext(location.search);
  const back = h("p", { class: "back" }, link(navigate, context.back, context.back === pathFor("search") ? "← Search the archive" : "← Back to your search"));

  (async () => {
    try {
      const record = await api[kind](id);
      if (disposed) return;
      // A Ship's address shows a Ship; an Organisation's id at a Ship's address is not found.
      if (kind !== "document" && record.entity !== kind) throw Object.assign(new Error("That page does not exist."), { status: 404 });
      setTitle(record.title ?? record.name ?? "Record");
      if (kind === "document") {
        const page = documentPage({ record, navigate });
        release = page.dispose;
        body.replaceChildren(...page.nodes.filter(Boolean));
      } else {
        body.replaceChildren(...subjectPage({ record, navigate, kind, matchedName: context.name, staff }).filter(Boolean));
      }
    } catch (error) {
      if (disposed) return;
      setTitle(error.status === 404 ? "Not found" : "Problem");
      body.replaceChildren(h("h1", {}, error.status === 404 ? "Page not found" : "Something went wrong"), h("p", { role: "alert", class: "error" }, error.message));
    }
  })();

  return {
    title: "Loading",
    element: h("article", { class: "record" }, back, body),
    dispose() {
      disposed = true;
      release();
    },
  };
}
