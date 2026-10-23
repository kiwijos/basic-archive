import { createApi, createSearchApi } from "./api.js";
import { h } from "./dom.js";
import { parseRoute, pathFor } from "./router.js";
import { session } from "./session.js";
import { link } from "./widgets.js";
import { recordView } from "./views/record.js";
import { searchView } from "./views/search.js";
import { queueView } from "./views/queue.js";
import { reviewView } from "./views/review.js";
import { signInView } from "./views/sign-in.js";
import { uploadView } from "./views/upload.js";

const bar = document.getElementById("bar");
const main = document.getElementById("main");
let current;

function navigate(path, { replace = false } = {}) {
  if (replace) history.replaceState(null, "", path);
  else history.pushState(null, "", path);
  render();
}

function signOut() {
  session.signOut();
  navigate(pathFor("search"));
}

const searchApi = createSearchApi({ fetch: (...args) => fetch(...args) });

const api = createApi({
  fetch: (...args) => fetch(...args),
  getToken: () => session.token(),
  onUnauthorized: (message) => {
    session.expire(message, location.pathname + location.search);
    render();
  },
});

function renderBar() {
  const signedIn = Boolean(session.token());
  bar.replaceChildren(
    h(
      "nav",
      { "aria-label": "Main" },
      link(navigate, pathFor("search"), "Ship Archive"),
      link(navigate, pathFor("search"), "Search"),
      signedIn
        ? [link(navigate, pathFor("queue"), "Review queue"), link(navigate, pathFor("upload"), "Upload")]
        : link(navigate, pathFor("queue"), "Staff sign-in"),
      signedIn
        ? h("span", { class: "who" }, `Signed in as ${session.name()} `, h("button", { type: "button", onclick: signOut }, "Sign out"))
        : null,
    ),
  );
}

function notFoundView() {
  return {
    title: "Not found",
    element: h("section", {}, h("h1", {}, "Page not found"), h("p", {}, link(navigate, pathFor("search"), "Search the archive"))),
  };
}

// Searching and every record's own page are open to everyone; only the staff pages ask for a token.
const STAFF_PAGES = new Set(["queue", "upload", "review"]);

function setTitle(text) {
  document.title = `${text} · Ship Archive`;
}

function render() {
  current?.dispose?.();
  const route = parseRoute(location.pathname);
  renderBar();

  let view;
  if (STAFF_PAGES.has(route.name) && !session.token()) {
    view = signInView({
      api,
      session,
      notice: session.takeNotice(),
      onSignedIn: () => {
        const back = session.takeReturnTo();
        if (back && parseRoute(back).name !== "notFound") navigate(back, { replace: true });
        else render();
      },
    });
  } else if (route.name === "search") view = searchView({ api: searchApi, navigate, setTitle });
  else if (["ship", "organisation", "document"].includes(route.name)) view = recordView({ api: searchApi, navigate, setTitle, kind: route.name, id: route.params.id });
  else if (route.name === "queue") view = queueView({ api, navigate });
  else if (route.name === "upload") view = uploadView({ api, navigate });
  else if (route.name === "review") view = reviewView({ api, navigate, documentId: route.params.documentId });
  else view = notFoundView();

  current = view;
  setTitle(view.title);
  main.replaceChildren(view.element);
  (view.focus ?? main).focus();
}

window.addEventListener("popstate", render);
render();
