import { h } from "../dom.js";
import { pathFor } from "../router.js";
import { candidateRows, candidatesSummary, referenceLine, validQuery } from "../wikidata.js";
import { link } from "../widgets.js";

/**
 * Staff page for one Ship. For now it holds the Wikidata step: ask for candidates, choose the one that is
 * this ship, or remove a wrong choice. Nothing is matched without a person choosing.
 */
export function shipEditView({ api, navigate, id }) {
  let disposed = false;
  let ship = null;
  let searching = 0;

  const title = h("h1", {}, "Loading…");
  const problem = h("p", { role: "alert", class: "error" });
  const stored = h("ul", { class: "stored-matches" });
  const storedHeading = h("h2", { id: "stored-heading" }, "Matches on Wikidata");
  const notice = h("p", { role: "status", class: "message" });
  const summary = h("p", { role: "status", class: "summary" });
  const list = h("ol", { class: "candidates" });

  const input = h("input", { id: "wikidata-query", name: "q", type: "search", maxlength: 200, autocomplete: "off" });
  const submit = h("button", { type: "submit", class: "primary" }, "Find on Wikidata");

  const storedIds = () => (ship?.external_refs ?? []).filter((ref) => ref.source === "wikidata").map((ref) => ref.id);

  function paintStored() {
    const refs = (ship?.external_refs ?? []).filter((ref) => ref.source === "wikidata");
    storedHeading.textContent = refs.length ? "Matches on Wikidata" : "No Wikidata match chosen yet";
    stored.replaceChildren(
      ...refs.map((ref) =>
        h(
          "li",
          { "data-wikidata-id": ref.id },
          h("a", { href: ref.url, rel: "noopener noreferrer", target: "_blank" }, referenceLine(ref)),
          ref.description ? ` – ${ref.description} ` : " ",
          h(
            "button",
            {
              type: "button",
              onclick: async (event) => {
                problem.textContent = "";
                event.target.disabled = true;
                try {
                  await api.removeWikidata(id, ref.id);
                  notice.textContent = `Removed ${ref.label} (${ref.id}).`;
                  await reload();
                } catch (error) {
                  problem.textContent = error.message;
                  event.target.disabled = false;
                }
              },
            },
            `Remove ${ref.label}`,
          ),
        ),
      ),
    );
  }

  function paintCandidates(found, query) {
    const rows = candidateRows(found, storedIds());
    summary.textContent = candidatesSummary(rows.length, query);
    list.replaceChildren(
      ...rows.map((row) =>
        h(
          "li",
          { "data-wikidata-id": row.id, class: "candidate" },
          h("strong", {}, row.label),
          " ",
          h("span", { class: "muted" }, `(${row.id})`),
          h("p", {}, row.description),
          row.url ? h("a", { href: row.url, rel: "noopener noreferrer", target: "_blank" }, "Open on Wikidata (new tab)") : null,
          " ",
          row.chosen
            ? h("span", { class: "badge badge-verified" }, "Already chosen")
            : h(
                "button",
                {
                  type: "button",
                  class: "primary",
                  "aria-label": `Choose ${row.label} (${row.id}) for this ship`,
                  onclick: async (event) => {
                    problem.textContent = "";
                    event.target.disabled = true;
                    try {
                      await api.chooseWikidata(id, row.id);
                      notice.textContent = `Stored ${row.label} (${row.id}) from Wikidata.`;
                      await reload();
                      paintCandidates(found, query);
                    } catch (error) {
                      problem.textContent = error.message;
                      event.target.disabled = false;
                    }
                  },
                },
                "Choose",
              ),
        ),
      ),
    );
  }

  async function reload() {
    ship = await api.ship(id);
    if (disposed) return;
    title.textContent = ship.name ?? "Unnamed ship";
    if (!input.value) input.value = ship.name ?? "";
    paintStored();
  }

  const form = h(
    "form",
    {
      class: "stack",
      onsubmit: async (event) => {
        event.preventDefault();
        const query = validQuery(input.value);
        problem.textContent = "";
        if (!query) {
          problem.textContent = "Type a name to look for.";
          input.focus();
          return;
        }
        const mine = (searching += 1);
        submit.disabled = true;
        summary.textContent = "Asking Wikidata…";
        list.replaceChildren();
        try {
          const answer = await api.wikidataCandidates(id, query);
          if (disposed || mine !== searching) return;
          paintCandidates(answer.candidates, answer.query);
        } catch (error) {
          if (disposed || mine !== searching) return;
          summary.textContent = "";
          // Wikidata being slow or down changes nothing else: the ship and its page keep working.
          problem.textContent = error.message;
        } finally {
          submit.disabled = false;
        }
      },
    },
    h("label", { for: input.id }, "Name to look for"),
    input,
    submit,
  );

  reload().catch((error) => {
    if (disposed) return;
    title.textContent = "Ship";
    problem.textContent = error.status === 404 ? "This ship does not exist." : error.message;
  });

  return {
    title: "Ship",
    element: h(
      "section",
      { class: "ship-edit" },
      h("p", {}, link(navigate, pathFor("ship", { id }), "← View the public page")),
      title,
      h("p", {}, "Match this ship with its item on Wikidata. Nothing is matched for you: you look at the candidates and choose."),
      problem,
      notice,
      h("section", { "aria-labelledby": "stored-heading" }, storedHeading, stored),
      h("section", { "aria-labelledby": "find-heading" }, h("h2", { id: "find-heading" }, "Find on Wikidata"), form, summary, list),
    ),
    focus: input,
    dispose() {
      disposed = true;
    },
  };
}
