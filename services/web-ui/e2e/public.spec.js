import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

const token = process.env.STAFF_TOKEN;
const scan = process.env.SCAN_FILE;
// Random letters, not the run number: search forgives typos, so numbers that differ in a digit or two would match.
const run = Array.from({ length: 10 }, () => "abcdefghijklmnopqrstuvwxyz"[Math.floor(Math.random() * 26)]).join("");

// Words that exist nowhere else in the archive, so every search finds exactly this run's records.
const oldName = `Alfa${run}`;
const newName = `Beta${run}`;
const sister = `Gamma${run}`;
const yard = `Varv${run}`;
const verifiedTitle = `Brev ${run}`;
const unverifiedTitle = `Utkast ${run}`;
const word = `zebrafink${run}`;

const ids = {};

async function created(response) {
  expect(response.status(), await response.text()).toBeLessThan(300);
  return response.json();
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ playwright }) => {
  if (!token || !scan) throw new Error("Run through `make e2e`: STAFF_TOKEN and SCAN_FILE are required.");
  const api = await playwright.request.newContext({
    baseURL: process.env.ARCHIVE_URL ?? "http://localhost",
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
  const post = async (path, data) => created(await api.post(`/api/catalog${path}`, { data }));

  ids.yard = (await post("/organisations", { name: yard, place: "Lindholmen" })).id;
  ids.ship = (await post("/ships", { name: oldName, ship_type: "barque" })).id;
  await post(`/subjects/${ids.ship}/names`, { name: newName, date: { date_from: "1900-01-01" } });
  await post("/relations", { from_subject_id: ids.ship, predicate: "built_by", to_subject_id: ids.yard, date: { date_text: "1889–90", date_from: "1889-06-01", date_to: "1890-03-01" } });
  ids.sister = (await post("/ships", { name: sister, ship_type: "barque" })).id;
  await post("/relations", { from_subject_id: ids.sister, predicate: "rebuilt_from", to_subject_id: ids.ship, date: { date_text: "1912" } });

  const upload = async (title) =>
    created(await api.post("/api/catalog/documents", { multipart: { file: { name: "scan.png", mimeType: "image/png", buffer: readFileSync(scan) }, title, document_type: "letter", rights: "CC BY", date_text: "ca 1891", date_from: "1890-01-01", date_to: "1892-12-31" } }));
  const verified = await upload(verifiedTitle);
  ids.document = verified.id;
  await post(`/images/${verified.images[0].id}/transcriptions`, { source: "human", text: `Skeppet ${word} lämnade Göteborg` });
  const link = await api.put(`/api/catalog/documents/${ids.document}/subjects/${ids.ship}`, { data: { role: "depicted" } });
  expect(link.status()).toBe(200);
  ids.unverified = (await upload(unverifiedTitle)).id;

  // Wait for the index to catch up, as any visitor would.
  await expect.poll(async () => {
    const found = await (await api.get(`/api/search/documents?q=${word}&n=${Math.random()}`)).json();
    return found.hits.some((hit) => hit.id === ids.document && hit.verified);
  }, { timeout: 60_000 }).toBe(true);
  await expect.poll(async () => (await (await api.get(`/api/search/subjects/${ids.sister}`)).status()), { timeout: 60_000 }).toBe(200);
  await api.dispose();
});

test("searching finds a document, highlights the match and says the text is verified", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Search the archive").fill(word);
  await page.getByRole("button", { name: "Search" }).click();

  const result = page.locator(`.result[data-id="${ids.document}"]`);
  await expect(result).toBeVisible();
  await expect(result.getByRole("link", { name: verifiedTitle })).toBeVisible();
  await expect(result.locator("mark")).toHaveText(word);
  await expect(result.getByText("Verified by a person")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`\\?q=${word}$`));
  await expect(page.getByRole("status")).toContainText("1 result");
  await expect(page.getByRole("complementary", { name: "Filters" })).not.toContainText("null");
});

test("a document that nobody has checked says it is machine-transcribed, and verified-only removes it", async ({ page }) => {
  await page.goto(`/?q=${run}`);
  const unchecked = page.locator(`.result[data-id="${ids.unverified}"]`);
  await expect(unchecked).toBeVisible();
  await expect(unchecked.getByText("Machine-transcribed, not yet checked")).toBeVisible();
  await expect(page.locator(`.result[data-id="${ids.document}"]`)).toBeVisible();

  await page.getByLabel("Only Documents verified by a person").check();

  await expect(unchecked).toHaveCount(0);
  await expect(page.locator(`.result[data-id="${ids.document}"]`)).toBeVisible();
  await expect(page).toHaveURL(/verified_only=1/);
  await page.reload();
  await expect(page.getByLabel("Only Documents verified by a person")).toBeChecked();
  await expect(unchecked).toHaveCount(0);
});

test("facets narrow the results and the filters survive a reload", async ({ page }) => {
  await page.goto(`/?q=${run}`);
  await expect(page.locator(".result")).toHaveCount(2);

  await page.getByRole("group", { name: "Builder" }).getByLabel(new RegExp(yard)).check();

  await expect(page.locator(".result")).toHaveCount(1);
  await expect(page.locator(`.result[data-id="${ids.document}"]`)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`builder=${yard}`));
  await expect(page.getByRole("group", { name: "Builder" }).getByLabel(new RegExp(yard))).toBeFocused();

  await page.reload();
  await expect(page.getByRole("group", { name: "Builder" }).getByLabel(new RegExp(yard))).toBeChecked();
  await expect(page.locator(".result")).toHaveCount(1);

  await page.getByRole("button", { name: "Clear all filters" }).click();
  await expect(page.locator(".result")).toHaveCount(2);

  await page.getByLabel("From").fill("1950");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByRole("status")).toContainText("No results");
});

test("an old name finds the ship and the result says which name matched", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Ships and organisations" }).click();
  await page.getByLabel("Search the archive").fill(oldName);
  await page.getByRole("button", { name: "Search" }).click();

  const result = page.locator(`.result[data-id="${ids.ship}"]`);
  await expect(result.getByRole("link", { name: newName })).toBeVisible();
  await expect(result.locator(".matched-name")).toContainText(`Matched the former name "${oldName}"`);
  await expect(result.locator("mark")).toContainText(oldName);
});

test("suggestions appear as you type, including old names, and open the record", async ({ page }) => {
  await page.goto("/");
  const box = page.getByRole("combobox", { name: "Search the archive" });
  await box.fill(oldName.slice(0, oldName.length - 2));

  const option = page.getByRole("option", { name: new RegExp(newName) });
  await expect(option).toBeVisible();
  await expect(option).toContainText(`formerly ${oldName}`);
  await box.press("ArrowDown");
  await box.press("Enter");

  await expect(page).toHaveURL(new RegExp(`/ships/${ids.ship}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(newName);
});

test("a ship's page shows its names with dates and its relations, and a rebuilt-from link leads to the other ship", async ({ page }) => {
  await page.goto(`/ships/${ids.ship}`);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(newName);
  const names = page.locator(".names li");
  await expect(names).toHaveCount(2);
  await expect(names.nth(0)).toContainText(oldName);
  await expect(names.nth(1)).toContainText(newName);
  await expect(names.nth(1)).toContainText("current name");
  await expect(page.locator('[data-predicate="built_by"]')).toContainText(`Built by ${yard}`);
  await expect(page.locator('[data-predicate="built_by"]')).toContainText("1889–90");
  await expect(page.locator('[data-predicate="rebuilt_from"]')).toContainText(`Rebuilt as ${sister}`);
  await expect(page.getByRole("link", { name: verifiedTitle })).toBeVisible();

  await page.getByRole("link", { name: sister }).click();
  await expect(page).toHaveURL(new RegExp(`/ships/${ids.sister}$`));
  await expect(page.locator('[data-predicate="rebuilt_from"]')).toContainText(`Rebuilt from ${newName}`);

  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(sister);
  await page.getByRole("link", { name: newName }).click();
  await expect(page).toHaveURL(new RegExp(`/ships/${ids.ship}$`));
});

test("a document's page shows its rights, whether it is verified, its text and the records it is about", async ({ page }) => {
  await page.goto(`/documents/${ids.document}`);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(verifiedTitle);
  await expect(page.locator(".meta").first()).toContainText("Verified by a person");
  await expect(page.getByText("Rights:")).toBeVisible();
  await expect(page.getByRole("link", { name: "Creative Commons Attribution 4.0" })).toHaveAttribute("href", /creativecommons\.org\/licenses\/by\/4\.0/);
  await expect(page.locator(".transcript")).toContainText(`Skeppet ${word} lämnade Göteborg`);
  await expect(page.getByText("ca 1891")).toBeVisible();
  await page.getByRole("link", { name: newName }).click();
  await expect(page).toHaveURL(new RegExp(`/ships/${ids.ship}$`));

  await page.goto(`/documents/${ids.unverified}`);
  await expect(page.locator(".meta").first()).toContainText("Machine-transcribed, not yet checked");
});

test("the public pages need no sign-in and a record's address works in a fresh browser", async ({ browser }) => {
  const visitor = await browser.newContext();
  const page = await visitor.newPage();
  const failed = [];
  page.on("response", (response) => response.status() >= 400 && failed.push(`${response.status()} ${response.url()}`));

  await page.goto(`/documents/${ids.document}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(verifiedTitle);
  await page.goto(`/ships/${ids.sister}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(sister);
  await page.goto(`/?q=${word}`);
  await expect(page.locator(".result")).toHaveCount(1);

  expect(failed).toEqual([]);
  await visitor.close();
});

test("an address that is not a record gives a clear not-found page", async ({ page }) => {
  await page.goto("/ships/3f2504e0-4f89-41d3-9a0c-0305e82c3301");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.goto(`/documents/${ids.ship}`);
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.goto(`/organisations/${ids.ship}`);
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.goto("/documents/not-an-id");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
});

test("the staff pages are still behind sign-in", async ({ page }) => {
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Staff sign-in" })).toBeVisible();
});
