import { h } from "../dom.js";
import { recordPath } from "../record-context.js";
import { pathFor } from "../router.js";
import { clearFilters, hasFilters, parseSearch, searchQuery, toggleValue, withChange } from "../search-state.js";
import { facetOptions, facetTitle, hasMatch, matchedNameNote, pagerInfo, resultsSummary, verification, yearsText } from "../view-models.js";
import { highlighted, link, verificationBadge } from "../widgets.js";

const SUGGEST_DELAY_MS = 200;
const MIN_SUGGEST_LENGTH = 2;

// Which part of the search each facet filters, per scope. "kind" holds a single value; the rest are lists.
const FACETS = {
  documents: [["ship_types", "shipType"], ["builders", "builder"], ["places", "place"], ["document_type", "documentType"]],
  subjects: [["entity", "kind"], ["ship_type", "shipType"], ["builders", "builder"], ["places", "place"]],
};
const KIND_LABELS = { ship: "Ships", organisation: "Organisations" };
const KIND_NAMES = { ship: "Ship", organisation: "Organisation", document: "Document" };

let uniqueId = 0;
const idFor = (name) => `${name}-${(uniqueId += 1)}`;

/** The public search page. Everything it shows is in the address, so reload and shared links give the same page. */
export function searchView({ api, navigate, setTitle }) {
  let state = parseSearch(location.search);
  let request = 0;
  let disposed = false;
  let suggestTimer;
  let suggestSeq = 0; // a response is used only if nothing closed or restarted the suggestions since it was asked for
  let suggestions = [];
  let active = -1;
  let refocus = null;

  const input = h("input", {
    id: idFor("q"), name: "q", type: "search", autocomplete: "off", spellcheck: "false", maxlength: 200,
    role: "combobox", "aria-autocomplete": "list", "aria-expanded": "false",
  });
  const list = h("ul", { id: idFor("suggestions"), role: "listbox", class: "suggestions", hidden: true, "aria-label": "Suggestions" });
  input.setAttribute("aria-controls", list.id);
  input.value = state.q;

  const status = h("p", { role: "status", class: "summary" });
  const problem = h("p", { role: "alert", class: "error" });
  const results = h("ol", { class: "results" });
  const facets = h("div", { class: "facets" });
  const pager = h("nav", { class: "pager", "aria-label": "Result pages", hidden: true });

  function go(next, { replace = false } = {}) {
    state = next;
    const address = pathFor("search") + searchQuery(state);
    if (replace) history.replaceState(null, "", address);
    else history.pushState(null, "", address);
    load();
  }

  // ---- suggestions -------------------------------------------------------------------------------------------------
  function closeSuggestions() {
    suggestSeq += 1;
    suggestions = [];
    active = -1;
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function paintSuggestions() {
    list.replaceChildren(
      ...suggestions.map((item, index) => {
        const option = h(
          "li",
          { id: `${list.id}-${index}`, role: "option", "aria-selected": String(index === active), class: index === active ? "active" : "" },
          h("span", { class: "suggestion-text" }, item.text),
          " ",
          h("span", { class: "suggestion-kind" }, KIND_NAMES[item.type] ?? item.type),
          item.matched_name && item.matched_name !== item.text ? h("span", { class: "suggestion-note" }, ` (formerly ${item.matched_name})`) : null,
        );
        // mousedown so the choice is made before the input loses focus and closes the list
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          choose(item);
        });
        return option;
      }),
    );
    list.hidden = suggestions.length === 0;
    input.setAttribute("aria-expanded", String(suggestions.length > 0));
    if (active >= 0) input.setAttribute("aria-activedescendant", `${list.id}-${active}`);
    else input.removeAttribute("aria-activedescendant");
  }

  function choose(item) {
    closeSuggestions();
    navigate(recordPath(item.type, item.id, { search: searchQuery(state), matchedName: item.matched_name && item.matched_name !== item.text ? item.matched_name : null }));
  }

  function askForSuggestions() {
    clearTimeout(suggestTimer);
    const text = input.value.trim();
    if (text.length < MIN_SUGGEST_LENGTH) {
      closeSuggestions();
      return;
    }
    suggestSeq += 1;
    const mine = suggestSeq;
    suggestTimer = setTimeout(async () => {
      try {
        const found = (await api.suggest(text)).suggestions;
        if (disposed || mine !== suggestSeq) return;
        suggestions = found;
        active = -1;
        paintSuggestions();
      } catch {
        closeSuggestions(); // suggestions are a convenience, so a failure is not worth a message
      }
    }, SUGGEST_DELAY_MS);
  }

  input.addEventListener("input", askForSuggestions);
  input.addEventListener("blur", closeSuggestions);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSuggestions();
    else if ((event.key === "ArrowDown" || event.key === "ArrowUp") && suggestions.length) {
      event.preventDefault();
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + suggestions.length) % suggestions.length;
      paintSuggestions();
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      choose(suggestions[active]);
    }
  });

  const form = h(
    "form",
    {
      role: "search",
      class: "search-form",
      onsubmit: (event) => {
        event.preventDefault();
        clearTimeout(suggestTimer);
        closeSuggestions();
        go(withChange(state, { q: input.value.trim() }));
      },
    },
    h("label", { for: input.id }, "Search the archive"),
    h("div", { class: "search-row" }, h("div", { class: "combo" }, input, list), h("button", { type: "submit", class: "primary" }, "Search")),
  );

  // ---- scope and filters -------------------------------------------------------------------------------------------
  const scopes = h("div", { class: "scopes", role: "group", "aria-label": "What to search" });
  const filters = h("div", { class: "filters" });

  function paintScopes() {
    scopes.replaceChildren(
      ...[["documents", "Documents"], ["subjects", "Ships and organisations"]].map(([scope, label]) =>
        h("button", { type: "button", "aria-pressed": String(state.scope === scope), onclick: () => go(withChange(clearFilters(state), { scope })) }, label),
      ),
    );
  }

  function paintFilters(answer) {
    const stats = answer?.facet_stats ?? {};
    const verifiedId = idFor("verified");
    const fromId = idFor("year-from");
    const toId = idFor("year-to");
    const from = h("input", { id: fromId, "data-control": "year-from", type: "number", min: 1, max: 9999, inputmode: "numeric", placeholder: stats.year_from ? String(stats.year_from.min) : "" });
    const to = h("input", { id: toId, type: "number", min: 1, max: 9999, inputmode: "numeric", placeholder: stats.year_to ? String(stats.year_to.max) : "" });
    from.value = state.yearFrom ?? "";
    to.value = state.yearTo ?? "";
    // replaceChildren would write a missing part as the text "null", so leave those out
    filters.replaceChildren(...[
      state.scope === "documents"
        ? h(
            "div",
            { class: "check" },
            h("input", {
              id: verifiedId, type: "checkbox", checked: state.verifiedOnly, "data-control": "verified",
              onchange: (event) => {
                refocus = { control: "verified" };
                go(withChange(state, { verifiedOnly: event.target.checked }));
              },
            }),
            h("label", { for: verifiedId }, "Only Documents verified by a person"),
          )
        : null,
      h(
        "form",
        {
          class: "years",
          onsubmit: (event) => {
            event.preventDefault();
            refocus = { control: "year-from" };
            go(withChange(state, { yearFrom: from.value ? Number(from.value) : null, yearTo: to.value ? Number(to.value) : null }));
          },
        },
        h("fieldset", {}, h("legend", {}, "Years"), h("label", { for: fromId }, "From"), from, h("label", { for: toId }, "To"), to, h("button", { type: "submit" }, "Apply")),
      ),
      hasFilters(state) ? h("button", { type: "button", class: "clear", onclick: () => go(clearFilters(state)) }, "Clear all filters") : null,
    ].filter(Boolean));
  }

  function paintFacets(answer) {
    const groups = [];
    for (const [name, key] of FACETS[state.scope]) {
      const selected = key === "kind" ? (state.kind ? [state.kind] : []) : state[key];
      const options = facetOptions(answer?.facets?.[name], selected);
      if (options.length === 0) continue;
      const legendId = idFor("facet");
      groups.push(
        h(
          "fieldset",
          { class: "facet" },
          h("legend", { id: legendId }, facetTitle(name)),
          h(
            "ul",
            {},
            options.map((option) => {
              const id = idFor("facet-option");
              return h(
                "li",
                {},
                h("input", {
                  id, type: "checkbox", checked: option.selected, "data-facet": `${key}:${option.value}`,
                  onchange: () => {
                    refocus = { facet: `${key}:${option.value}` };
                    go(key === "kind" ? withChange(state, { kind: option.selected ? "" : option.value }) : toggleValue(state, key, option.value));
                  },
                }),
                h("label", { for: id }, `${key === "kind" ? KIND_LABELS[option.value] ?? option.value : option.value} `, h("span", { class: "count" }, `(${option.count})`)),
              );
            }),
          ),
        ),
      );
    }
    facets.replaceChildren(...groups);
  }

  // ---- results -----------------------------------------------------------------------------------------------------
  const context = () => searchQuery(state);

  function documentResult(hit) {
    const date = hit.date_text || yearsText(hit.year_from, hit.year_to);
    return h(
      "li",
      { class: "result", "data-kind": "document", "data-id": hit.id },
      h("h2", {}, link(navigate, recordPath("document", hit.id, { search: context() }), hasMatch(hit.highlights.title) ? highlighted(hit.highlights.title) : hit.title)),
      h("p", { class: "meta" }, verificationBadge(verification(hit)), [hit.document_type, date, hit.ship_names.slice(0, 3).join(", ")].filter(Boolean).map((part) => h("span", {}, part))),
      // The start of a text where nothing matched would look like the reason it was found, so it is left out.
      hasMatch(hit.highlights.text) ? h("p", { class: "snippet" }, highlighted(hit.highlights.text)) : null,
    );
  }

  function subjectResult(hit) {
    const note = matchedNameNote(hit);
    const years = yearsText(hit.year_from, hit.year_to);
    const path = recordPath(hit.entity, hit.id, { search: context(), matchedName: note ? hit.matched_name : null });
    return h(
      "li",
      { class: "result", "data-kind": hit.entity, "data-id": hit.id },
      h("h2", {}, link(navigate, path, hasMatch(hit.highlights.name) ? highlighted(hit.highlights.name) : hit.name)),
      note ? h("p", { class: "matched-name" }, note, hit.highlights.names.length ? [": ", h("span", { class: "matched" }, highlighted(hit.highlights.names))] : null) : null,
      h("p", { class: "meta" }, h("span", { class: "badge badge-kind" }, KIND_NAMES[hit.entity]), [hit.ship_type ?? hit.organisation_type, years, hit.builders.length ? `Built by ${hit.builders.join(", ")}` : "", hit.places.join(", ")].filter(Boolean).map((part) => h("span", {}, part))),
    );
  }

  function paintPager(answer) {
    const info = pagerInfo(answer);
    pager.hidden = answer.total_pages <= 1;
    const move = (page) => (event) => {
      event.preventDefault();
      refocus = { pager: true };
      go(withChange(state, { page }));
      window.scrollTo?.(0, 0);
    };
    const address = (page) => pathFor("search") + searchQuery(withChange(state, { page }));
    pager.replaceChildren(
      info.hasPrevious ? h("a", { href: address(state.page - 1), rel: "prev", onclick: move(state.page - 1) }, "Previous") : h("span", { class: "disabled" }, "Previous"),
      h("span", { class: "position" }, info.text),
      info.hasNext ? h("a", { href: address(state.page + 1), rel: "next", onclick: move(state.page + 1) }, "Next") : h("span", { class: "disabled" }, "Next"),
    );
  }

  function restoreFocus() {
    if (!refocus) return;
    const target = refocus.control ? filters.querySelector(`[data-control="${refocus.control}"]`) : refocus.facet ? facets.querySelector(`[data-facet="${CSS.escape(refocus.facet)}"]`) : pager.querySelector("a");
    target?.focus();
    refocus = null;
  }

  async function load() {
    const mine = (request += 1);
    input.value = state.q;
    paintScopes();
    status.textContent = "Searching…";
    problem.textContent = "";
    setTitle(state.q ? `Search: ${state.q}` : "Search");
    let answer;
    try {
      answer = await api.search(state);
    } catch (error) {
      if (disposed || mine !== request) return;
      status.textContent = "";
      problem.textContent = error.message;
      return;
    }
    if (disposed || mine !== request) return;
    status.textContent = resultsSummary(answer.total);
    results.replaceChildren(...answer.hits.map((hit) => (state.scope === "documents" ? documentResult(hit) : subjectResult(hit))));
    paintFilters(answer);
    paintFacets(answer);
    paintPager(answer);
    restoreFocus();
  }

  load();

  return {
    title: "Search",
    element: h(
      "section",
      { class: "search-page" },
      h("h1", {}, "Search the archive"),
      form,
      scopes,
      h("div", { class: "search-layout" }, h("aside", { "aria-label": "Filters" }, filters, facets), h("div", { class: "search-results" }, status, problem, results, pager)),
    ),
    focus: input,
    dispose() {
      disposed = true;
      clearTimeout(suggestTimer);
    },
  };
}
