import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const token = process.env.STAFF_TOKEN;
const blueprint = process.env.BLUEPRINT_FILE;
const sheetTwo = process.env.BLUEPRINT_FILE_2;

const ids = {};
const TILE_ROUTE = /\/iiif\/3\/[0-9a-f-]{36}\/\d+,\d+,\d+,\d+\/\d+,\d*\/0\/default\.jpg/;
const TILE = /\/iiif\/3\/([0-9a-f-]{36})\/(\d+),(\d+),(\d+),(\d+)\/(\d+),(\d*)\/0\/default\.jpg/;

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ playwright }) => {
  if (!token || !blueprint || !sheetTwo) throw new Error("Run through `make e2e`: STAFF_TOKEN, BLUEPRINT_FILE and BLUEPRINT_FILE_2 are required.");
  const api = await playwright.request.newContext({
    baseURL: process.env.ARCHIVE_URL ?? "http://localhost",
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
  const file = (path) => ({ name: "plan.tif", mimeType: "image/tiff", buffer: readFileSync(path) });
  const made = await api.post("/api/catalog/documents", { multipart: { file: file(blueprint), title: "Linjeritning", document_type: "blueprint", rights: "CC0" } });
  expect(made.status(), await made.text()).toBe(201);
  const document = await made.json();
  ids.document = document.id;
  ids.first = document.images[0].id;
  const added = await api.post(`/api/catalog/documents/${ids.document}/images`, { multipart: { file: file(sheetTwo), rights: "CC0" } });
  expect(added.status(), await added.text()).toBe(201);
  ids.second = (await added.json()).images[1].id;
  await expect.poll(async () => (await api.get(`/api/search/documents/${ids.document}`)).status(), { timeout: 60_000 }).toBe(200);
  await api.dispose();
});

/** Remembers every IIIF request and answer, and anything the browser complained about. */
function watch(page) {
  const seen = { tiles: [], answers: [], problems: [], infoUrls: [] };
  page.on("console", (message) => message.type() === "error" && seen.problems.push(message.text()));
  page.on("pageerror", (error) => seen.problems.push(error.message));
  page.on("requestfinished", async (request) => {
    if (!request.url().includes("/iiif/3/")) return;
    const response = await request.response();
    const timing = request.timing();
    seen.answers.push({ url: request.url(), status: response.status(), ms: timing.responseEnd });
    if (request.url().endsWith("/info.json")) seen.infoUrls.push(request.url());
    const match = request.url().match(TILE);
    if (match) {
      const [, id, , , regionWidth, , sizeWidth] = match;
      seen.tiles.push({ id, scale: Number(regionWidth) / Number(sizeWidth) });
    }
  });
  return seen;
}

test("a large blueprint opens in a viewer and zooming in loads finer tiles, all of them successfully and quickly", async ({ page }) => {
  const seen = watch(page);
  await page.goto(`/documents/${ids.document}`);

  const stage = page.locator(".viewer-stage");
  await expect(stage.locator("canvas")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("status").filter({ hasText: "Loading the scan" })).toHaveCount(0);
  await expect.poll(() => seen.tiles.length, { timeout: 20_000 }).toBeGreaterThan(0);
  const overview = Math.min(...seen.tiles.map((t) => t.scale));
  expect(overview, "the first tiles show the whole drawing, so each tile stands for many pixels").toBeGreaterThanOrEqual(4);

  for (let step = 0; step < 6; step += 1) {
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.waitForTimeout(500);
  }
  await expect.poll(() => Math.min(...seen.tiles.map((t) => t.scale)), { timeout: 20_000 }).toBeLessThanOrEqual(1);

  const refused = seen.answers.filter((answer) => answer.status >= 400);
  expect(refused, "no tile, and no information document, was refused").toEqual([]);
  const tiles = seen.answers.filter((answer) => TILE.test(answer.url)).map((answer) => answer.ms).sort((a, b) => a - b);
  expect(tiles.length).toBeGreaterThan(10);
  expect(tiles[Math.floor(tiles.length / 2)], "the typical tile arrives in well under a second").toBeLessThan(500);
  expect(tiles.at(-1), "even the slowest tile arrives in a few seconds").toBeLessThan(4000);
  expect(seen.problems, "the browser reported nothing wrong, such as a blocked script or style").toEqual([]);
});

test("the viewer can be driven from the keyboard and its buttons say what they do", async ({ page }) => {
  const seen = watch(page);
  await page.goto(`/documents/${ids.document}`);
  const stage = page.locator(".viewer-stage");
  await expect(stage.locator("canvas")).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => seen.tiles.length, { timeout: 20_000 }).toBeGreaterThan(0);

  const canvas = stage.locator(".openseadragon-canvas");
  await expect(canvas).toHaveAttribute("aria-label", /Zoomable scan of Linjeritning, page 1 of 2\. Use plus and minus to zoom/);
  for (const name of ["Zoom in", "Zoom out", "Reset view", "Full screen"]) await expect(page.getByRole("button", { name })).toBeVisible();

  const before = Math.min(...seen.tiles.map((t) => t.scale));
  // The picture is the next stop after the buttons, so a keyboard user reaches it by tabbing.
  await page.getByRole("button", { name: "Full screen" }).focus();
  await page.keyboard.press("Tab");
  await expect(canvas).toBeFocused();
  // Zooming is continuous while the key is held down, as it is for a person.
  for (let press = 0; press < 3; press += 1) {
    await page.keyboard.down("Equal");
    await page.waitForTimeout(900);
    await page.keyboard.up("Equal");
  }
  await expect.poll(() => Math.min(...seen.tiles.map((t) => t.scale)), { timeout: 20_000 }).toBeLessThan(before);

  await page.getByRole("button", { name: "Reset view" }).click();
  await page.keyboard.down("Minus");
  await page.waitForTimeout(300);
  await page.keyboard.up("Minus");
  expect(seen.answers.filter((answer) => answer.status >= 400)).toEqual([]);
  expect(seen.problems).toEqual([]);
});

test("a document with two sheets lets you choose which one to zoom into, and the choice is in the address", async ({ page }) => {
  const seen = watch(page);
  await page.goto(`/documents/${ids.document}`);
  await expect(page.locator(".viewer-stage canvas")).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => seen.infoUrls.some((url) => url.includes(ids.first)), { timeout: 20_000 }).toBe(true);
  await expect(page.getByRole("button", { name: "Page 1" })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "Page 2" }).click();

  await expect(page.getByRole("button", { name: "Page 2" })).toBeFocused(); // a keyboard user keeps their place
  await expect(page).toHaveURL(/\?page=2$/);
  await expect(page.getByRole("button", { name: "Page 2" })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => seen.infoUrls.some((url) => url.includes(ids.second)), { timeout: 20_000 }).toBe(true);
  await expect(page.locator(".viewer-stage .openseadragon-canvas")).toHaveAttribute("aria-label", /page 2 of 2/);

  await page.reload();
  await expect(page.getByRole("button", { name: "Page 2" })).toHaveAttribute("aria-pressed", "true");
  expect(seen.problems).toEqual([]);
});

test("the scan is served through the site's own address, so the page works behind any host", async ({ page }) => {
  const origins = new Set();
  page.on("request", (request) => origins.add(new URL(request.url()).origin));
  await page.goto(`/documents/${ids.document}`);
  await expect(page.locator(".viewer-stage canvas")).toBeVisible({ timeout: 20_000 });

  expect([...origins]).toEqual([new URL(page.url()).origin]);
});

test("when the tiles keep failing the visitor is told, not left with an empty box", async ({ page }) => {
  await page.route(TILE_ROUTE, (route) => route.fulfill({ status: 500, body: "broken" }));
  await page.goto(`/documents/${ids.document}`);

  await expect(page.getByRole("alert").filter({ hasText: "could not be loaded" })).toBeVisible({ timeout: 20_000 });
});

test("when the scan's information cannot be fetched the visitor is told", async ({ page }) => {
  await page.route("**/iiif/3/*/info.json", (route) => route.fulfill({ status: 503, body: "down" }));
  await page.goto(`/documents/${ids.document}`);

  await expect(page.getByRole("alert").filter({ hasText: "could not be loaded" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("status").filter({ hasText: "Loading the scan" })).toHaveCount(0);
});

test("when the viewer itself cannot be loaded the visitor is told, and the rest of the page still works", async ({ page }) => {
  await page.route("**/assets/openseadragon-*.js", (route) => route.abort());
  await page.goto(`/documents/${ids.document}`);

  await expect(page.getByRole("alert").filter({ hasText: "could not be loaded" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Linjeritning");
  await expect(page.locator(".transcript, .page-text").first()).toBeVisible();
});
