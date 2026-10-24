import { expect, test } from "@playwright/test";

// Reads what `make demo` loads: the fictional fleet and the Chapman plates. It only reads, as a visitor would, and it
// says out loud when the data is not there, rather than passing or failing for a reason that is not the code's.
const FORMER_NAME = "Nordstjärnan";
const LATEST_NAME = "Havsörnen";
const PLATE_TITLE = "Hagbåt";
const TILE = /\/iiif\/3\/([0-9a-f-]{36})\/(\d+),(\d+),(\d+),(\d+)\/(\d+),(\d*)\/0\/default\.jpg/;

const found = {};

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext({ baseURL: process.env.ARCHIVE_URL ?? "http://localhost" });
  const ships = await (await api.get("/api/search/subjects", { params: { q: FORMER_NAME, kind: "ship" } })).json();
  found.ship = ships.hits.find((hit) => hit.name === LATEST_NAME);
  const plates = await (await api.get("/api/search/documents", { params: { q: PLATE_TITLE } })).json();
  found.plate = plates.hits.find((hit) => hit.title.startsWith(PLATE_TITLE));
  await api.dispose();
});

/** Remembers every IIIF answer, and anything the browser complained about. */
function watch(page) {
  const seen = { tiles: [], answers: [], problems: [] };
  page.on("console", (message) => message.type() === "error" && seen.problems.push(message.text()));
  page.on("pageerror", (error) => seen.problems.push(error.message));
  page.on("requestfinished", async (request) => {
    if (!request.url().includes("/iiif/3/")) return;
    const response = await request.response();
    seen.answers.push({ url: request.url(), status: response.status() });
    const match = request.url().match(TILE);
    if (match) seen.tiles.push({ scale: Number(match[4]) / Number(match[6]) });
  });
  return seen;
}

test("a former name of the seeded ship finds it, and its page shows its three names", async ({ page }) => {
  test.skip(!found.ship, "the demo data is not loaded: run `make demo` (or `make seed`) first");
  await page.goto("/");
  await page.getByRole("button", { name: "Ships and organisations" }).click();
  await page.getByLabel("Search the archive").fill(FORMER_NAME);
  await page.getByRole("button", { name: "Search" }).click();

  const result = page.locator(`.result[data-id="${found.ship.id}"]`);
  await expect(result.getByRole("link", { name: LATEST_NAME })).toBeVisible();
  await expect(result.locator(".matched-name")).toContainText(`Matched the former name "${FORMER_NAME}"`);

  await result.getByRole("link", { name: LATEST_NAME }).click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(LATEST_NAME);
  await expect(page.locator(".names li")).toHaveCount(3);
  await expect(page.locator(".names li[data-matched]")).toContainText(FORMER_NAME);
});

test("a seeded Chapman plate opens in the viewer and zooming loads finer tiles, every one answered", async ({ page }) => {
  test.skip(!found.plate, "the Chapman plates are not loaded (they need network access when seeding): run `make seed` with a connection");
  const seen = watch(page);
  await page.goto(`/documents/${found.plate.id}`);

  await expect(page.locator(".viewer-stage canvas")).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => seen.tiles.length, { timeout: 30_000 }).toBeGreaterThan(0);
  for (let step = 0; step < 6; step += 1) {
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.waitForTimeout(500);
  }
  await expect.poll(() => Math.min(...seen.tiles.map((t) => t.scale)), { timeout: 30_000 }).toBeLessThanOrEqual(1);

  expect(seen.answers.length).toBeGreaterThan(10);
  const refused = seen.answers.filter((answer) => answer.status >= 300);
  expect(refused, "every tile and information document was served").toEqual([]);
  expect(seen.problems, "the browser reported nothing wrong").toEqual([]);
});
