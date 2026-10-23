// What the deep-zoom viewer is given and what it says about itself. Kept free of the viewer library, so
// the decisions about it can be tested without a browser.

/** Options for OpenSeadragon, which reads the image's own description (IIIF info.json) and fetches tiles from it. */
export function viewerOptions(infoUrl) {
  return {
    tileSources: infoUrl,
    // The page draws its own, labelled buttons; the library's would be pictures fetched from a folder.
    showNavigationControl: false,
    // A blueprint is read at its finest detail, so allow zooming well past one image pixel per screen pixel.
    maxZoomPixelRatio: 4,
    minZoomImageRatio: 0.9,
    visibilityRatio: 0.6,
    constrainDuringPan: true,
    // Movements glide instead of jumping, and a tile that is not there yet is drawn from a coarser one.
    animationTime: 0.7,
    springStiffness: 7,
    immediateRender: false,
    preserveImageSizeOnResize: true,
    gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: true },
  };
}

/** The pages of a Document that have an image service, in page order. */
export function viewerPages(images) {
  const shown = (images ?? []).filter((image) => image.iiif_info);
  const single = shown.length === 1;
  return shown
    .map((image) => ({ pageNo: image.page_no, label: single ? "Scan" : `Page ${image.page_no}`, infoUrl: image.iiif_info, imageId: image.id }))
    .sort((a, b) => a.pageNo - b.pageNo);
}

/** The page to open: the one the address names if there is such a page, otherwise the first. */
export function parsePage(queryString, pages) {
  if (pages.length === 0) return null;
  const wanted = new URLSearchParams(queryString).get("page");
  const match = wanted && /^\d+$/.test(wanted) ? pages.find((page) => page.pageNo === Number(wanted)) : undefined;
  return match ?? pages[0];
}

/** What a screen reader hears about the viewer. */
export function viewerLabel(title, page, total) {
  const which = total > 1 ? `, page ${page.pageNo} of ${total}` : "";
  return `Zoomable scan of ${title}${which}. Use plus and minus to zoom and the arrow keys to move around.`;
}

/** Shown when the scan cannot be displayed, whether the viewer never started or its tiles keep failing. */
export const VIEWER_FAILED = "The scan could not be loaded. Try again in a moment.";

/**
 * Tells when failed tiles are worth a message: several in a row, which is what a stopped service or a
 * refused request looks like, as opposed to one tile that failed and loads on the next try.
 */
export function createTileWatch(limit = 3) {
  let failures = 0;
  return {
    failed() {
      failures += 1;
      return failures >= limit;
    },
    loaded() {
      failures = 0;
    },
  };
}
