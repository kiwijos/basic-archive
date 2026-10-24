import { expect, test } from "@playwright/test";

const token = process.env.STAFF_TOKEN;
const base = process.env.ARCHIVE_URL ?? "http://localhost";
const VASA = "Q219821";
const today = new Date().toISOString().slice(0, 10);

const ids = {};
let wikidataReachable = true;

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ playwright }) => {
  if (!token) throw new Error("Run through `make e2e`: STAFF_TOKEN is required.");
  // These tests talk to the real Wikidata, as the archive does in use, so they need the internet.
  try {
    const response = await fetch("https://www.wikidata.org/w/api.php?action=query&meta=siteinfo&format=json", { signal: AbortSignal.timeout(8000) });
    wikidataReachable = response.ok;
  } catch {
    wikidataReachable = false;
  }
  const api = await playwright.request.newContext({ baseURL: base, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const made = await api.post("/api/catalog/ships", { data: { name: "Vasa", ship_type: "warship" } });
  expect(made.status(), await made.text()).toBe(201);
  ids.ship = (await made.json()).id;
  await api.dispose();
});

test.afterAll(async ({ playwright }) => {
  if (!ids.ship) return;
  const api = await playwright.request.newContext({ baseURL: base, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  await api.delete(`/api/catalog/ships/${ids.ship}`);
  await api.dispose();
});

async function signIn(page) {
  await page.goto("/review");
  await page.getByLabel("Staff token").fill(token);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/Signed in as/)).toBeVisible();
}

test("staff ask Wikidata, see candidates with descriptions, and nothing is stored until they choose", async ({ page }) => {
  test.skip(!wikidataReachable, "Wikidata cannot be reached from this machine, so the real service cannot be tried");
  await signIn(page);
  await page.goto(`/ships/${ids.ship}/edit`);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Vasa");
  await expect(page.getByRole("heading", { name: "No Wikidata match chosen yet" })).toBeVisible();
  await expect(page.getByLabel("Name to look for")).toHaveValue("Vasa");

  await page.getByRole("button", { name: "Find on Wikidata" }).click();

  await expect(page.getByRole("status").filter({ hasText: /possible matches for "Vasa"/ })).toBeVisible({ timeout: 30_000 });
  const candidate = page.locator(`.candidate[data-wikidata-id="${VASA}"]`);
  await expect(candidate).toBeVisible();
  await expect(candidate.locator("p")).not.toBeEmpty();
  await expect(candidate.getByRole("link", { name: /Open on Wikidata/ })).toHaveAttribute("href", `https://www.wikidata.org/wiki/${VASA}`);
  // Asking changed nothing.
  await expect(page.getByRole("heading", { name: "No Wikidata match chosen yet" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "No Wikidata match chosen yet" })).toBeVisible();
});

test("choosing a candidate stores it with its source and the day it was fetched, and it survives a reload", async ({ page }) => {
  test.skip(!wikidataReachable, "Wikidata cannot be reached from this machine, so the real service cannot be tried");
  await signIn(page);
  await page.goto(`/ships/${ids.ship}/edit`);
  await page.getByRole("button", { name: "Find on Wikidata" }).click();
  const candidate = page.locator(`.candidate[data-wikidata-id="${VASA}"]`);
  await expect(candidate).toBeVisible({ timeout: 30_000 });

  await candidate.getByRole("button", { name: `Choose Vasa (${VASA}) for this ship` }).click();

  await expect(page.getByRole("status").filter({ hasText: `Stored Vasa (${VASA}) from Wikidata.` })).toBeVisible();
  const stored = page.locator(`.stored-matches li[data-wikidata-id="${VASA}"]`);
  await expect(stored).toContainText(`Vasa (Wikidata ${VASA}), fetched ${today}`);
  await expect(candidate).toContainText("Already chosen");
  await expect(candidate.getByRole("button", { name: /Choose/ })).toHaveCount(0);

  await page.reload();
  await expect(page.locator(`.stored-matches li[data-wikidata-id="${VASA}"]`)).toContainText(`fetched ${today}`);
});

test("the match reaches the public ship page, which also tells staff, and only staff, where to edit it", async ({ page, browser }) => {
  test.skip(!wikidataReachable, "Wikidata cannot be reached from this machine, so the real service cannot be tried");
  const visitor = await browser.newContext();
  const open = await visitor.newPage();

  // Search is fed by events, so it catches up within seconds.
  await expect(async () => {
    await open.goto(`/ships/${ids.ship}`);
    await expect(open.getByRole("heading", { name: "Elsewhere" })).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 45_000 });
  const link = open.getByRole("link", { name: "Vasa on Wikidata" });
  await expect(link).toHaveAttribute("href", `https://www.wikidata.org/wiki/${VASA}`);
  await expect(open.locator('[data-source="wikidata"]')).toContainText(`fetched ${today}`);
  await expect(open.getByRole("link", { name: /Staff: find this ship on Wikidata/ })).toHaveCount(0);
  await visitor.close();

  await signIn(page);
  await page.goto(`/ships/${ids.ship}`);
  await page.getByRole("link", { name: /Staff: find this ship on Wikidata/ }).click();
  await expect(page).toHaveURL(new RegExp(`/ships/${ids.ship}/edit$`));
});

test("a Wikidata that is slow or down is explained, and the ship's page and search keep working", async ({ page }) => {
  await signIn(page);
  await page.route("**/wikidata-candidates*", (route) =>
    route.fulfill({ status: 504, contentType: "application/json", body: JSON.stringify({ detail: "Wikidata did not answer in time. Try again in a moment." }) }),
  );
  await page.goto(`/ships/${ids.ship}/edit`);

  await page.getByRole("button", { name: "Find on Wikidata" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "Wikidata did not answer in time" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Find on Wikidata" })).toBeEnabled();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Vasa");
  await expect(page.locator(`.stored-matches li[data-wikidata-id="${VASA}"]`)).toBeVisible(); // what was stored is still there
  // Once Wikidata is back the same page works without starting over.
  await page.unroute("**/wikidata-candidates*");
  test.skip(!wikidataReachable, "Wikidata cannot be reached from this machine");
  await page.getByRole("button", { name: "Find on Wikidata" }).click();
  await expect(page.getByRole("status").filter({ hasText: /possible matches/ })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".ship-edit .error")).toBeEmpty();
});

test("a wrong choice can be removed, and then the public page stops showing it", async ({ page, browser }) => {
  test.skip(!wikidataReachable, "Wikidata cannot be reached from this machine, so the real service cannot be tried");
  await signIn(page);
  await page.goto(`/ships/${ids.ship}/edit`);

  await page.getByRole("button", { name: "Remove Vasa" }).click();

  await expect(page.getByRole("status").filter({ hasText: `Removed Vasa (${VASA}).` })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No Wikidata match chosen yet" })).toBeVisible();
  const visitor = await browser.newContext();
  const open = await visitor.newPage();
  await expect(async () => {
    await open.goto(`/ships/${ids.ship}`);
    await expect(open.getByRole("heading", { level: 1 })).toHaveText("Vasa");
    await expect(open.getByRole("heading", { name: "Elsewhere" })).toHaveCount(0);
  }).toPass({ timeout: 45_000 });
  await visitor.close();
});

test("the staff ship page is behind sign-in and an unknown ship is not found", async ({ page }) => {
  await page.goto(`/ships/${ids.ship}/edit`);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  await signIn(page);
  await page.goto("/ships/3f2504e0-4f89-41d3-9a0c-0305e82c3301/edit");
  await expect(page.getByRole("alert")).toContainText("does not exist");
});
