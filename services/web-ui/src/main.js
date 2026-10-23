import { createApi } from "./api.js";
import { h } from "./dom.js";
import { parseRoute, pathFor } from "./router.js";
import { session } from "./session.js";
import { link } from "./widgets.js";
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
  navigate(pathFor("home"));
}

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
      h("strong", {}, "Ship Archive"),
      signedIn ? [link(navigate, pathFor("queue"), "Review queue"), link(navigate, pathFor("upload"), "Upload")] : null,
      signedIn
        ? h("span", { class: "who" }, `Signed in as ${session.name()} `, h("button", { type: "button", onclick: signOut }, "Sign out"))
        : null,
    ),
  );
}

function homeView() {
  return {
    title: "Ship Archive",
    element: h(
      "section",
      {},
      h("h1", {}, "Ship Archive"),
      h("p", {}, "Review and correct the text of scanned ship documents."),
      h("ul", {}, h("li", {}, link(navigate, pathFor("queue"), "Open the review queue")), h("li", {}, link(navigate, pathFor("upload"), "Upload a scan"))),
    ),
  };
}

function notFoundView() {
  return {
    title: "Not found",
    element: h("section", {}, h("h1", {}, "Page not found"), h("p", {}, link(navigate, pathFor("home"), "Go to the start page"))),
  };
}

function render() {
  current?.dispose?.();
  const route = parseRoute(location.pathname);
  renderBar();

  let view;
  if (!session.token() && route.name !== "notFound") {
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
  } else if (route.name === "home") view = homeView();
  else if (route.name === "queue") view = queueView({ api, navigate });
  else if (route.name === "upload") view = uploadView({ api, navigate });
  else if (route.name === "review") view = reviewView({ api, navigate, documentId: route.params.documentId });
  else view = notFoundView();

  current = view;
  document.title = `${view.title} · Ship Archive`;
  main.replaceChildren(view.element);
  (view.focus ?? main).focus();
}

window.addEventListener("popstate", render);
render();
