import { h } from "../dom.js";
import { parsePage, viewerLabel, viewerOptions, viewerPages } from "../viewer.js";

const ZOOM_STEP = 1.6;

/**
 * A deep-zoom viewer for a Document's scans. The library is loaded only when a Document page opens, so
 * searching stays light, and tiles come from the IIIF service through the same site.
 */
export function scanViewer({ title, images }) {
  const pages = viewerPages(images);
  if (pages.length === 0) return null;

  let page = parsePage(location.search, pages);
  let viewer = null;
  let disposed = false;

  const stage = h("div", { class: "viewer-stage" });
  const status = h("p", { role: "status", class: "viewer-status" }, "Loading the scan…");
  const problem = h("p", { role: "alert", class: "error" });

  const act = (action) => () => viewer && action(viewer);
  const button = (label, action, hint) => h("button", { type: "button", onclick: act(action), title: hint ?? label }, label);
  const controls = h(
    "div",
    { class: "viewer-controls", role: "toolbar", "aria-label": "Zoom controls" },
    button("Zoom in", (v) => { v.viewport.zoomBy(ZOOM_STEP); v.viewport.applyConstraints(); }, "Zoom in (plus key)"),
    button("Zoom out", (v) => { v.viewport.zoomBy(1 / ZOOM_STEP); v.viewport.applyConstraints(); }, "Zoom out (minus key)"),
    button("Reset view", (v) => v.viewport.goHome(), "Show the whole scan"),
    button("Full screen", (v) => v.setFullScreen(!v.isFullPage()), "Full screen on or off"),
  );

  const selector = h("div", { class: "viewer-pages", role: "group", "aria-label": "Pages" });

  function paintSelector() {
    if (pages.length < 2) return;
    selector.replaceChildren(
      ...pages.map((p) => h("button", { type: "button", "aria-pressed": String(p === page), onclick: () => show(p) }, p.label)),
    );
  }

  // The library listens for keys on its own canvas, which is what takes focus, so the label goes there.
  function describe() {
    const canvas = viewer?.canvas;
    if (!canvas) return;
    canvas.setAttribute("role", "group");
    canvas.setAttribute("aria-label", viewerLabel(title, page, pages.length));
  }

  function show(next) {
    page = next;
    describe();
    paintSelector();
    problem.textContent = "";
    status.textContent = "Loading the scan…";
    if (pages.length > 1) {
      const params = new URLSearchParams(location.search);
      params.set("page", String(page.pageNo));
      history.replaceState(history.state, "", `${location.pathname}?${params}`);
    }
    viewer?.open(viewerOptions(page.infoUrl).tileSources);
  }

  (async () => {
    const { default: OpenSeadragon } = await import("openseadragon");
    if (disposed) return;
    viewer = OpenSeadragon({ element: stage, ...viewerOptions(page.infoUrl) });
    describe();
    viewer.addHandler("open", () => {
      status.textContent = "";
    });
    viewer.addHandler("open-failed", () => {
      status.textContent = "";
      problem.textContent = "The scan could not be loaded. Try again in a moment.";
    });
  })();

  describe();
  paintSelector();

  return {
    element: h(
      "section",
      { class: "scan-viewer", "aria-labelledby": "scan-heading" },
      h("h2", { id: "scan-heading" }, "Scan"),
      selector,
      controls,
      status,
      problem,
      stage,
    ),
    dispose() {
      disposed = true;
      viewer?.destroy();
      viewer = null;
    },
  };
}
